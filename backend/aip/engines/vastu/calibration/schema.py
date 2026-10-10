"""Data structures for Vastu rule-weight calibration.

The engine already computes, for a given plan, each rule's satisfaction in [0,1]
and whether the rule was assessable at all. This module only describes how those
outputs, plus practitioner judgements, are carried into the fitting code.

Nothing here evaluates a rule. Rule evaluation stays in the reasoner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class RuleCard:
    """The fixed, non-learned facts about a rule.

    `modern_validity` is an editorial judgement recorded in the corpus, not a
    fitted parameter. It is deliberately excluded from calibration: if the fit
    were allowed to move it, the stance slider would stop meaning what the
    report says it means.
    """

    rule_id: str
    provenance: str            # "manasara" | "mayamata" | ... | "contemporary"
    modern_validity: float     # [0,1], from the corpus
    prior_weight: float = 1.0  # the hand-set weight the fit starts from

    def __post_init__(self) -> None:
        if not 0.0 <= self.modern_validity <= 1.0:
            raise ValueError(f"{self.rule_id}: modern_validity out of range")
        if self.prior_weight < 0.0:
            raise ValueError(f"{self.rule_id}: prior_weight must be >= 0")


@dataclass(frozen=True)
class PlanObservation:
    """One plan, as the reasoner scored it.

    satisfaction[r]  in [0,1]
    assessable[r]    True if the rule could be evaluated on this plan at all

    Unassessable rules are dropped from both numerator and denominator, exactly
    as the engine does. They must not be imputed here -- imputing them is the
    false-precision failure the corpus already refuses.
    """

    plan_id: str
    rule_ids: tuple[str, ...]
    satisfaction: np.ndarray   # shape (R,)
    assessable: np.ndarray     # shape (R,), bool

    def __post_init__(self) -> None:
        R = len(self.rule_ids)
        if self.satisfaction.shape != (R,) or self.assessable.shape != (R,):
            raise ValueError(f"{self.plan_id}: shape mismatch against rule_ids")
        if not self.assessable.any():
            raise ValueError(f"{self.plan_id}: no assessable rules, cannot score")
        s = self.satisfaction[self.assessable]
        if s.min() < 0.0 or s.max() > 1.0:
            raise ValueError(f"{self.plan_id}: satisfaction outside [0,1]")


@dataclass(frozen=True)
class PairwiseJudgement:
    """Practitioner K saw plans A and B and said which is more Vastu-compliant.

    Pairwise is the default instrument because absolute 0-100 ratings from
    practitioners carry a large, drifting per-rater offset, while "which of
    these two" is stable. `stance` records which reading the rater was asked
    for: 1.0 = strict classical, which is what an orthodox panel should be
    asked. Do not mix stances in one fit without saying so.
    """

    plan_a: str
    plan_b: str
    winner: str                # must equal plan_a or plan_b
    rater_id: str
    stance: float = 1.0
    confidence: float = 1.0    # (0,1]; downweights a rater's own "close call"

    def __post_init__(self) -> None:
        if self.winner not in (self.plan_a, self.plan_b):
            raise ValueError("winner must be one of the two plans")
        if self.plan_a == self.plan_b:
            raise ValueError("cannot compare a plan with itself")
        if not 0.0 < self.confidence <= 1.0:
            raise ValueError("confidence must be in (0,1]")


@dataclass(frozen=True)
class AbsoluteRating:
    """A 0-1 compliance rating. Supported, but weaker evidence than a pair."""

    plan_id: str
    rating: float
    rater_id: str
    stance: float = 1.0


@dataclass
class CalibrationSet:
    """Everything the fit consumes."""

    cards: tuple[RuleCard, ...]
    plans: dict[str, PlanObservation] = field(default_factory=dict)
    pairs: list[PairwiseJudgement] = field(default_factory=list)
    ratings: list[AbsoluteRating] = field(default_factory=list)

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(c.rule_id for c in self.cards)

    @property
    def modern_validity(self) -> np.ndarray:
        return np.array([c.modern_validity for c in self.cards], dtype=float)

    @property
    def prior_weights(self) -> np.ndarray:
        return np.array([c.prior_weight for c in self.cards], dtype=float)

    def add_plan(self, obs: PlanObservation) -> None:
        if obs.rule_ids != self.rule_ids:
            raise ValueError(
                f"{obs.plan_id}: rule ordering differs from the corpus. "
                "The design matrix is positional; reorder at the adapter."
            )
        self.plans[obs.plan_id] = obs

    def matrices(self) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
        """Stack plans into S (satisfaction) and M (assessability mask)."""
        ids = tuple(sorted(self.plans))
        S = np.stack([self.plans[p].satisfaction for p in ids])
        M = np.stack([self.plans[p].assessable for p in ids]).astype(float)
        return S, M, ids

    def validate(self) -> list[str]:
        """Return human-readable problems. Empty list means fit is safe to run."""
        problems: list[str] = []
        known = set(self.plans)
        for j in self.pairs:
            missing = {j.plan_a, j.plan_b} - known
            if missing:
                problems.append(f"pair references unscored plan(s): {sorted(missing)}")
        for r in self.ratings:
            if r.plan_id not in known:
                problems.append(f"rating references unscored plan: {r.plan_id}")
        if self.plans:
            S, M, _ = self.matrices()
            for i, rid in enumerate(self.rule_ids):
                seen = S[:, i][M[:, i] > 0]
                if seen.size == 0:
                    problems.append(f"{rid}: never assessable in the panel set")
                elif float(seen.std()) < 1e-9:
                    problems.append(f"{rid}: constant across the panel set, weight unidentified")
        return problems


def stance_scale(modern_validity: np.ndarray, stance: float) -> np.ndarray:
    """e_r(t) = t + (1-t) * modern_validity_r, per README."""
    if not 0.0 <= stance <= 1.0:
        raise ValueError("stance must be in [0,1]")
    return stance + (1.0 - stance) * modern_validity


def sequence_to_array(values: Sequence[float]) -> np.ndarray:
    return np.asarray(values, dtype=float)
