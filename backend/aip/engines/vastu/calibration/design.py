"""Which comparisons to buy.

Practitioner time is the binding constraint, and random pairs spend it badly.
Averaging 29 rules compresses plans into a narrow band -- on a representative
set the median score gap between two plans is around 0.05 -- so a randomly drawn
pair is close to a coin flip and carries almost no information about any
individual rule's weight.

Two properties make a pair worth asking about:

* **Separation.** The plans must be far enough apart that a practitioner has an
  opinion at all. Near-ties return noise dressed as data.
* **Direction.** The pair's rule-by-rule difference must point somewhere the
  existing pairs do not already cover. Twenty pairs that all differ on the same
  three rules identify three weights, not twenty.

`select_pairs` maximises both: greedy D-optimality over the Bradley-Terry design
vectors, with near-ties filtered out first.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np

from .model import score_and_jacobian
from .schema import CalibrationSet


def pair_design_matrix(
    cs: CalibrationSet, w: np.ndarray | None = None, stance: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, list[tuple[str, str]]]:
    """For every candidate pair return its design vector and score separation.

    The Bradley-Terry gradient with respect to w for a pair (a,b) is
    proportional to J_a - J_b, so that difference is the direction the pair
    informs. Evaluated at the current weights, which is the standard local
    design approximation -- redo it after a first round if the weights moved.
    """
    S, M, ids = cs.matrices()
    if w is None:
        w = cs.prior_weights
    sc, J = score_and_jacobian(w, S, M, cs.modern_validity, stance)

    pairs = list(combinations(range(len(ids)), 2))
    X = np.stack([J[a] - J[b] for a, b in pairs])
    sep = np.array([abs(sc[a] - sc[b]) for a, b in pairs])
    return X, sep, [(ids[a], ids[b]) for a, b in pairs]


def select_pairs(
    cs: CalibrationSet, n: int, w: np.ndarray | None = None, stance: float = 1.0,
    min_separation: float = 0.02, seed: int = 0,
) -> list[tuple[str, str]]:
    """Greedy D-optimal selection of `n` comparisons.

    `min_separation` drops pairs a practitioner would call a tie. Set it from
    the panel's own behaviour once you have a pilot round: the gap at which
    raters start disagreeing with themselves is the floor.
    """
    X, sep, labels = pair_design_matrix(cs, w, stance)
    eligible = np.where(sep >= min_separation)[0]
    if len(eligible) < n:
        eligible = np.argsort(-sep)[: max(n, 1)]

    rng = np.random.default_rng(seed)
    Xe, lab = X[eligible], [labels[i] for i in eligible]
    R = Xe.shape[1]

    chosen = [int(rng.integers(len(Xe)))]
    cov = np.eye(R) * 1e-3 + np.outer(Xe[chosen[0]], Xe[chosen[0]])
    while len(chosen) < min(n, len(Xe)):
        inv = np.linalg.inv(cov)
        gains = np.einsum("ij,jk,ik->i", Xe, inv, Xe)
        gains[chosen] = -np.inf
        k = int(np.argmax(gains))
        chosen.append(k)
        cov += np.outer(Xe[k], Xe[k])
    return [lab[i] for i in chosen]


def coverage(cs: CalibrationSet, pairs: list[tuple[str, str]],
             w: np.ndarray | None = None, stance: float = 1.0) -> dict[str, float]:
    """How well a chosen pair set illuminates each rule.

    Returns per-rule leverage: the total squared design weight pointing at that
    rule. A rule near zero will not be identified no matter how many raters you
    hire -- fix it by adding plans that vary on it, not by adding judgements.
    """
    S, M, ids = cs.matrices()
    idx = {p: i for i, p in enumerate(ids)}
    if w is None:
        w = cs.prior_weights
    _sc, J = score_and_jacobian(w, S, M, cs.modern_validity, stance)
    X = np.stack([J[idx[a]] - J[idx[b]] for a, b in pairs])
    lev = (X ** 2).sum(axis=0)
    lev = lev / (lev.max() + 1e-12)
    return {rid: float(lev[i]) for i, rid in enumerate(cs.rule_ids)}
