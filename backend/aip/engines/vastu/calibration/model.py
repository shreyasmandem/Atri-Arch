"""The scored quantity being calibrated, and its gradient.

    a_ir      = M_ir * e_r(t) * w_r          effective weight of rule r on plan i
    score_i   = sum_r a_ir * S_ir / sum_r a_ir

This is exactly the engine's arithmetic: unassessable rules leave the
denominator, and the stance scales each rule by t + (1-t)*modern_validity.

Two properties of this form matter, and both are asserted in the tests:

1. `score` is invariant to rescaling w. Only the *ratios* between rule weights
   are identifiable from judgement data. The fit therefore pins the scale with
   a prior rather than pretending to measure it.

2. With w >= 0, d(score_i)/d(S_ir) = a_ir / sum_r a_ir >= 0. Improving any
   assessable rule can never lower the score. That is a structural guarantee of
   the non-negativity bound, not something the data has to be trusted to teach.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-12


def effective_weights(
    w: np.ndarray, M: np.ndarray, modern_validity: np.ndarray, stance: float
) -> np.ndarray:
    """a_ir, shape (N, R)."""
    e = stance + (1.0 - stance) * modern_validity
    return M * (e * w)[None, :]


def score(
    w: np.ndarray, S: np.ndarray, M: np.ndarray,
    modern_validity: np.ndarray, stance: float,
) -> np.ndarray:
    """Vastu score per plan, shape (N,)."""
    A = effective_weights(w, M, modern_validity, stance)
    D = A.sum(axis=1)
    if np.any(D <= EPS):
        raise ValueError(
            "a plan has zero total effective weight: every assessable rule was "
            "driven to weight ~0, or no rule is assessable"
        )
    return (A * S).sum(axis=1) / D


def score_and_jacobian(
    w: np.ndarray, S: np.ndarray, M: np.ndarray,
    modern_validity: np.ndarray, stance: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return score (N,) and d(score_i)/d(w_r) as (N, R).

        d score_i / d w_r = M_ir * e_r * (S_ir - score_i) / D_i

    A rule pulls the score toward its own satisfaction; a rule that already
    agrees with the consensus score has no gradient. That is why rules with no
    variance across the panel set are unidentifiable rather than merely noisy.
    """
    e = stance + (1.0 - stance) * modern_validity
    A = M * (e * w)[None, :]
    D = A.sum(axis=1)
    if np.any(D <= EPS):
        raise ValueError("zero total effective weight on at least one plan")
    sc = (A * S).sum(axis=1) / D
    J = M * e[None, :] * (S - sc[:, None]) / D[:, None]
    return sc, J


def normalise(w: np.ndarray) -> np.ndarray:
    """Fix the unidentified scale so fitted weights are comparable run to run.

    Mean weight 1.0, which keeps a fitted corpus readable next to a hand-set one
    where every weight was 1.0.
    """
    m = float(np.mean(w))
    if m <= EPS:
        raise ValueError("cannot normalise an all-zero weight vector")
    return w / m
