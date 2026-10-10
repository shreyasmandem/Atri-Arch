"""Fitting rule weights to practitioner judgement.

Default instrument is pairwise. For a pair (a, b) judged in favour of a:

    P(a beats b) = sigmoid( beta * (score_a - score_b) )

beta is a fitted scale, jointly estimated, that absorbs how decisively the panel
separates plans. It is not a rule weight and is reported separately.

Three deliberate restrictions:

* w >= 0, always. A negative weight would mean satisfying a classical rule made
  a plan *less* compliant, which is not a claim the corpus can make and not one
  a report could cite. The bound also buys the monotonicity guarantee outright.
* Ridge toward the prior weights, not toward zero. With 29 parameters and a
  panel of a few hundred pairs, shrinking to the hand-set corpus is the honest
  default: a rule the panel never exercised keeps the weight an editor gave it.
* modern_validity is frozen. Only w moves.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from .model import normalise, score_and_jacobian
from .schema import CalibrationSet

W_FLOOR = 1e-4  # keeps denominators away from zero; effectively "switched off"


@dataclass
class FitResult:
    weights: np.ndarray
    rule_ids: tuple[str, ...]
    beta: float
    stance: float
    n_pairs: int
    n_plans: int
    train_accuracy: float
    converged: bool
    message: str
    ridge: float
    frozen: tuple[str, ...] = ()   # held at prior: unidentifiable from this panel

    def as_dict(self) -> dict[str, float]:
        return {r: float(w) for r, w in zip(self.rule_ids, self.weights)}

    def moved(self, prior: np.ndarray, tol: float = 0.05) -> list[tuple[str, float, float]]:
        """Rules whose weight the data actually moved, largest change first."""
        out = [
            (rid, float(p), float(w))
            for rid, p, w in zip(self.rule_ids, prior, self.weights)
            if abs(w - p) > tol
        ]
        return sorted(out, key=lambda t: -abs(t[2] - t[1]))


def _pair_arrays(cs: CalibrationSet, index: dict[str, int]):
    ia, ib, y, conf = [], [], [], []
    for j in cs.pairs:
        ia.append(index[j.plan_a])
        ib.append(index[j.plan_b])
        y.append(1.0 if j.winner == j.plan_a else 0.0)
        conf.append(j.confidence)
    return (
        np.asarray(ia, dtype=int),
        np.asarray(ib, dtype=int),
        np.asarray(y, dtype=float),
        np.asarray(conf, dtype=float),
    )


def fit_pairwise(
    cs: CalibrationSet,
    stance: float = 1.0,
    ridge: float = 1.0,
    max_iter: int = 500,
    strict: bool = True,
) -> FitResult:
    """Fit w (and beta) to the pairwise judgements in `cs`."""
    problems = cs.validate()
    hard = [p for p in problems if "unscored" in p]
    if hard:
        raise ValueError("calibration set is inconsistent:\n  " + "\n  ".join(hard))
    if strict and not cs.pairs:
        raise ValueError("no pairwise judgements: nothing to fit")

    S, M, plan_ids = cs.matrices()
    index = {p: i for i, p in enumerate(plan_ids)}
    ia, ib, y, conf = _pair_arrays(cs, index)
    mv = cs.modern_validity
    prior = cs.prior_weights
    R = S.shape[1]

    def unpack(theta):
        return theta[:R], float(np.exp(theta[R]))

    def objective(theta):
        w, beta = unpack(theta)
        sc, J = score_and_jacobian(w, S, M, mv, stance)
        d = sc[ia] - sc[ib]
        p = expit(beta * d)
        resid = conf * (p - y)

        nll = -float(np.sum(conf * (y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12))))
        pen = ridge * float(np.sum((w - prior) ** 2))

        gd = beta * resid                       # dNLL/dd per pair
        gw = gd @ (J[ia] - J[ib]) + 2.0 * ridge * (w - prior)
        gbeta = float(np.sum(resid * d)) * beta  # chain through beta = exp(theta_R)
        return nll + pen, np.concatenate([gw, [gbeta]])

    # A rule with no variance across the panel still has a non-zero gradient:
    # it pulls every plan toward its own fixed satisfaction, which compresses
    # the score spread -- an effect beta can absorb almost exactly. Its weight
    # is therefore confounded with beta, and the optimiser will happily move it
    # on that degenerate direction. Freeze it at the editor's value instead.
    frozen_idx = [
        i for i in range(R)
        if (M[:, i] > 0).sum() == 0 or float(S[:, i][M[:, i] > 0].std()) < 1e-9
    ]
    frozen = tuple(cs.rule_ids[i] for i in frozen_idx)

    theta0 = np.concatenate([np.maximum(prior, W_FLOOR), [np.log(8.0)]])
    bounds: list[tuple[float, float | None]] = [(W_FLOOR, None)] * R
    for i in frozen_idx:
        p = max(float(prior[i]), W_FLOOR)
        bounds[i] = (p, p)
        theta0[i] = p
    bounds.append((np.log(0.05), np.log(500.0)))

    res = minimize(
        objective, theta0, jac=True, method="L-BFGS-B",
        bounds=bounds, options={"maxiter": max_iter},
    )
    w, beta = unpack(res.x)
    # Scale is unidentified, so it is normally re-pinned to mean 1. When rules
    # are frozen that would silently rescale them off their priors, so the
    # ridge is left to pin the scale instead.
    if not frozen_idx:
        w = normalise(w)

    sc = score_and_jacobian(w, S, M, mv, stance)[0]
    pred = (sc[ia] > sc[ib]).astype(float)
    acc = float(np.mean(pred == y)) if len(y) else float("nan")

    return FitResult(
        weights=w, rule_ids=cs.rule_ids, beta=beta, stance=stance,
        n_pairs=len(y), n_plans=len(plan_ids), train_accuracy=acc,
        converged=bool(res.success), message=str(res.message), ridge=ridge,
        frozen=frozen,
    )


def fit_absolute(
    cs: CalibrationSet, stance: float = 1.0, ridge: float = 1.0, max_iter: int = 500,
) -> FitResult:
    """Fit to 0-1 ratings, with a per-rater affine calibration.

    Each rater k gets an offset and a positive slope, so a systematically harsh
    rater does not push every rule weight around. The slope is bounded positive
    so no rater can be fitted into rating the scale backwards.
    """
    if not cs.ratings:
        raise ValueError("no absolute ratings: nothing to fit")

    S, M, plan_ids = cs.matrices()
    index = {p: i for i, p in enumerate(plan_ids)}
    raters = sorted({r.rater_id for r in cs.ratings})
    rindex = {r: i for i, r in enumerate(raters)}
    K = len(raters)
    R = S.shape[1]

    pi = np.array([index[r.plan_id] for r in cs.ratings])
    ri = np.array([rindex[r.rater_id] for r in cs.ratings])
    target = np.array([r.rating for r in cs.ratings], dtype=float)
    mv, prior = cs.modern_validity, cs.prior_weights

    def objective(theta):
        w = theta[:R]
        off = theta[R:R + K]
        slope = theta[R + K:]
        sc, J = score_and_jacobian(w, S, M, mv, stance)
        pred = off[ri] + slope[ri] * sc[pi]
        resid = pred - target

        loss = float(np.sum(resid ** 2)) + ridge * float(np.sum((w - prior) ** 2))
        gw = (resid * slope[ri]) @ J[pi] * 2.0 + 2.0 * ridge * (w - prior)
        goff = np.bincount(ri, weights=2.0 * resid, minlength=K)
        gsl = np.bincount(ri, weights=2.0 * resid * sc[pi], minlength=K)
        return loss, np.concatenate([gw, goff, gsl])

    theta0 = np.concatenate([np.maximum(prior, W_FLOOR), np.zeros(K), np.ones(K)])
    bounds = [(W_FLOOR, None)] * R + [(-0.5, 0.5)] * K + [(0.1, 3.0)] * K
    res = minimize(objective, theta0, jac=True, method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": max_iter})

    w = normalise(res.x[:R])
    return FitResult(
        weights=w, rule_ids=cs.rule_ids, beta=float("nan"), stance=stance,
        n_pairs=0, n_plans=len(plan_ids), train_accuracy=float("nan"),
        converged=bool(res.success), message=str(res.message), ridge=ridge,
    )
