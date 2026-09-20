"""Whether a fit may be shipped.

A fitted weight vector is only allowed into the corpus if it clears all four:

1. It beats the hand-set prior on held-out pairs, split by *plan* not by pair.
   Splitting by pair leaks: the same plan appears on both sides and the fit can
   memorise its score.
2. Counterfactual monotonicity holds on every plan and every rule.
3. Held-out accuracy exceeds the panel's own self-agreement floor. A fit that
   predicts practitioners better than practitioners predict each other is
   overfitting, not insight.
4. Every weight the fit moved is identifiable -- the rule actually varied across
   the panel set and the bootstrap interval excludes the prior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .fit import fit_pairwise
from .model import score
from .schema import CalibrationSet, PairwiseJudgement


@dataclass
class CVResult:
    folds: int
    accuracy_fitted: float
    accuracy_prior: float
    per_fold: list[tuple[float, float]] = field(default_factory=list)

    @property
    def improvement(self) -> float:
        return self.accuracy_fitted - self.accuracy_prior


def _subset(cs: CalibrationSet, plan_ids: set[str]) -> CalibrationSet:
    sub = CalibrationSet(cards=cs.cards)
    for pid in plan_ids:
        sub.add_plan(cs.plans[pid])
    sub.pairs = [
        j for j in cs.pairs if j.plan_a in plan_ids and j.plan_b in plan_ids
    ]
    sub.ratings = [r for r in cs.ratings if r.plan_id in plan_ids]
    return sub


def _accuracy(w: np.ndarray, cs: CalibrationSet, pairs: list[PairwiseJudgement],
              stance: float) -> float:
    if not pairs:
        return float("nan")
    S, M, ids = cs.matrices()
    idx = {p: i for i, p in enumerate(ids)}
    sc = score(w, S, M, cs.modern_validity, stance)
    hits = [
        (sc[idx[j.plan_a]] > sc[idx[j.plan_b]]) == (j.winner == j.plan_a)
        for j in pairs
    ]
    return float(np.mean(hits))


def cross_validate(
    cs: CalibrationSet, folds: int = 5, stance: float = 1.0,
    ridge: float = 1.0, seed: int = 0,
) -> CVResult:
    """Grouped K-fold by plan. Pairs spanning a fold boundary are discarded."""
    rng = np.random.default_rng(seed)
    plan_ids = np.array(sorted(cs.plans))
    if len(plan_ids) < folds * 2:
        raise ValueError(
            f"{len(plan_ids)} plans is too few for {folds}-fold grouped CV; "
            "grow the panel set before trusting any held-out number"
        )
    rng.shuffle(plan_ids)
    chunks = np.array_split(plan_ids, folds)

    per_fold, fitted, priors = [], [], []
    for k in range(folds):
        test = set(chunks[k].tolist())
        train = set(plan_ids.tolist()) - test
        tr, te = _subset(cs, train), _subset(cs, test)
        if not tr.pairs or not te.pairs:
            continue
        res = fit_pairwise(tr, stance=stance, ridge=ridge)
        a_fit = _accuracy(res.weights, te, te.pairs, stance)
        a_pri = _accuracy(cs.prior_weights, te, te.pairs, stance)
        per_fold.append((a_fit, a_pri))
        fitted.append(a_fit)
        priors.append(a_pri)

    if not per_fold:
        raise ValueError("no fold produced both train and test pairs")
    return CVResult(
        folds=len(per_fold),
        accuracy_fitted=float(np.mean(fitted)),
        accuracy_prior=float(np.mean(priors)),
        per_fold=per_fold,
    )


def check_monotonicity(
    w: np.ndarray, cs: CalibrationSet, stance: float = 1.0, delta: float = 0.1,
) -> list[str]:
    """Raising any assessable rule's satisfaction must never lower the score.

    Guaranteed by w >= 0, but checked empirically anyway: the guarantee only
    holds if the shipped scorer uses this arithmetic, and this is the test that
    notices when it stops doing so.
    """
    S, M, ids = cs.matrices()
    mv = cs.modern_validity
    base = score(w, S, M, mv, stance)
    failures: list[str] = []
    for r in range(S.shape[1]):
        S2 = S.copy()
        S2[:, r] = np.minimum(S2[:, r] + delta, 1.0)
        after = score(w, S2, M, mv, stance)
        bad = np.where(after < base - 1e-9)[0]
        for i in bad:
            failures.append(
                f"{cs.rule_ids[r]} on {ids[i]}: score fell "
                f"{base[i]:.4f} -> {after[i]:.4f} when satisfaction rose"
            )
    return failures


def panel_agreement(cs: CalibrationSet) -> dict[str, float]:
    """How often two raters given the same unordered pair agree.

    This is the ceiling. A held-out accuracy above it is a warning sign, not an
    achievement -- there is no signal up there to have learned.
    """
    seen: dict[tuple[str, str], list[str]] = {}
    for j in cs.pairs:
        key = tuple(sorted((j.plan_a, j.plan_b)))
        seen.setdefault(key, []).append(j.winner)

    agree = total = 0
    for winners in seen.values():
        if len(winners) < 2:
            continue
        for i in range(len(winners)):
            for k in range(i + 1, len(winners)):
                total += 1
                agree += winners[i] == winners[k]
    return {
        "overlapping_pairs": float(sum(1 for v in seen.values() if len(v) > 1)),
        "comparisons": float(total),
        "agreement": float(agree / total) if total else float("nan"),
    }


def bootstrap_weights(
    cs: CalibrationSet, draws: int = 200, stance: float = 1.0,
    ridge: float = 1.0, seed: int = 0,
) -> dict[str, tuple[float, float, float]]:
    """Resample plans (not pairs) and refit. Returns rule -> (p05, median, p95).

    An interval straddling the prior means the panel did not tell you anything
    about that rule. Report it as unchanged rather than shipping the point
    estimate; a weight that moved on noise is a citation that will not survive
    an architect asking why.
    """
    rng = np.random.default_rng(seed)
    plan_ids = sorted(cs.plans)
    samples = []
    for _ in range(draws):
        keep = set(rng.choice(plan_ids, size=len(plan_ids), replace=True).tolist())
        sub = _subset(cs, keep)
        if len(sub.plans) < 4 or not sub.pairs:
            continue
        try:
            samples.append(fit_pairwise(sub, stance=stance, ridge=ridge).weights)
        except ValueError:
            continue
    if not samples:
        raise ValueError("every bootstrap draw failed; panel set is too small")
    Wb = np.stack(samples)
    q = np.percentile(Wb, [5, 50, 95], axis=0)
    return {
        rid: (float(q[0, i]), float(q[1, i]), float(q[2, i]))
        for i, rid in enumerate(cs.rule_ids)
    }


def identifiable(
    intervals: dict[str, tuple[float, float, float]], prior: dict[str, float],
) -> dict[str, bool]:
    """True where the bootstrap interval excludes the prior weight."""
    return {
        rid: not (lo <= prior.get(rid, 1.0) <= hi)
        for rid, (lo, _mid, hi) in intervals.items()
    }


def select_panel_plans(
    S: np.ndarray, M: np.ndarray, plan_ids: tuple[str, ...], n: int, seed: int = 0,
) -> list[str]:
    """Greedy D-optimal-ish choice of which plans to put in front of the panel.

    Practitioner time is the scarce input. Picking plans at random wastes it on
    near-duplicates; this picks the set whose rule-satisfaction patterns span
    the most directions, so each rule gets exercised and stays identifiable.
    """
    if n >= len(plan_ids):
        return list(plan_ids)
    X = S * M
    rng = np.random.default_rng(seed)
    chosen = [int(rng.integers(len(plan_ids)))]
    ridge = 1e-3 * np.eye(X.shape[1])
    while len(chosen) < n:
        cov = X[chosen].T @ X[chosen] + ridge
        inv = np.linalg.inv(cov)
        gains = np.einsum("ij,jk,ik->i", X, inv, X)
        gains[chosen] = -np.inf
        chosen.append(int(np.argmax(gains)))
    return [plan_ids[i] for i in chosen]
