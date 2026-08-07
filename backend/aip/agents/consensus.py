"""Multi-Agent Critic Consensus (MACC).

This is the platform's core methodological contribution and the answer to "why
is this better than one big model?".

A single model asked to design a building optimises a single, opaque, internal
objective. Architecture is irreducibly multi-objective: daylight fights privacy,
Vastu fights structural economy, generous rooms fight the budget. MACC makes
that conflict explicit and resolvable.

The procedure
-------------

Given candidate designs ``D`` and critics ``C`` (each owning one axis):

1. **Admissibility filter.** Any candidate carrying a ``CRITICAL`` finding -
   a statutory breach or a physical impossibility - is disqualified outright.
   No amount of aesthetic merit buys a way past a building code. If every
   candidate is inadmissible the filter is relaxed and the survivors are flagged,
   because returning nothing helps nobody.

2. **Pareto filtering.** Candidate *i* dominates *i'* when it is at least as good
   on every axis and strictly better on one. Dominated candidates are removed.
   What remains is the true trade-off frontier - this is the step a weighted-sum
   score alone would destroy, because summation lets a strong axis conceal a
   fatally weak one.

3. **Reliability-weighted Borda count.** Each critic ranks the frontier. Points
   are weighted by ``reliability x confidence x client priority``. Borda is
   deliberately ordinal: it is robust to critics that are well-ordered but badly
   calibrated in absolute terms, which describes most LLM critics.

4. **Cardinal utility.** A weighted mean of the axis scores, using the client's
   own stated priorities. Ordinal and cardinal views are blended, so neither a
   miscalibrated scale nor a knife-edge ranking can dominate alone.

5. **Agreement analysis.** Weighted dispersion per axis yields an agreement
   index. Low agreement is *not* averaged away - it is surfaced, and it is what
   triggers a debate round in which critics see each other's reasoning and may
   revise. Persistent disagreement is reported to the architect as a genuine
   design tension requiring a human decision.

Every number produced here is traceable to a critic, a model and a piece of
evidence, which is what makes the platform's explainability claim testable
rather than rhetorical.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from aip.agents.base import Critique, Evidence, Finding, Severity
from aip.core.logging import get_logger, log_event

logger = get_logger("aip.consensus")

TArtifact = TypeVar("TArtifact")

#: Blend between the ordinal (Borda) and cardinal (utility) views.
BORDA_WEIGHT = 0.42

#: Agreement below this triggers a debate round.
DEBATE_THRESHOLD = 0.68


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CriticCalibration:
    """Running reliability estimate for one critic.

    Reliability is learned, not assumed. When ground truth arrives - the client
    accepted a scheme, the build came in at a real cost, the architect overrode
    a recommendation - each critic's prediction is scored and its weight moves.
    A critic that consistently mispredicts loses influence over time.

    The update is a Brier-style exponential moving average, which is stable under
    the small, noisy sample sizes a single firm actually generates.
    """

    critic_id: str
    reliability: float = 0.8
    observations: int = 0
    brier_sum: float = 0.0
    alpha: float = 0.15          # EMA responsiveness

    def observe(self, predicted: float, actual: float) -> None:
        """Record one prediction/outcome pair, both in [0, 1]."""
        predicted = min(1.0, max(0.0, predicted))
        actual = min(1.0, max(0.0, actual))
        squared_error = (predicted - actual) ** 2
        self.brier_sum += squared_error
        self.observations += 1
        # Brier of 0 -> skill 1; Brier of 1 -> skill 0. Clamped to keep every
        # critic marginally in the conversation rather than silencing it.
        skill = 1.0 - squared_error
        self.reliability = min(
            0.99, max(0.15, (1 - self.alpha) * self.reliability + self.alpha * skill)
        )

    @property
    def mean_brier(self) -> float:
        return self.brier_sum / self.observations if self.observations else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "critic_id": self.critic_id,
            "reliability": round(self.reliability, 4),
            "observations": self.observations,
            "mean_brier": round(self.mean_brier, 4),
        }


class CalibrationLedger:
    """Persistent-ish store of critic reliabilities.

    Held in memory here and mirrored to the database by the learning service, so
    the committee's trust structure survives restarts and genuinely accumulates
    across a firm's projects.
    """

    def __init__(self, initial: dict[str, float] | None = None) -> None:
        self._entries: dict[str, CriticCalibration] = {}
        for critic_id, reliability in (initial or {}).items():
            self._entries[critic_id] = CriticCalibration(critic_id, reliability)

    def reliability_of(self, critic_id: str, default: float = 0.8) -> float:
        entry = self._entries.get(critic_id)
        return entry.reliability if entry else default

    def observe(self, critic_id: str, predicted: float, actual: float) -> None:
        entry = self._entries.setdefault(critic_id, CriticCalibration(critic_id))
        entry.observe(predicted, actual)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {cid: entry.to_dict() for cid, entry in self._entries.items()}

    def load(self, data: dict[str, dict[str, Any]]) -> None:
        for cid, payload in data.items():
            self._entries[cid] = CriticCalibration(
                critic_id=cid,
                reliability=float(payload.get("reliability", 0.8)),
                observations=int(payload.get("observations", 0)),
                brier_sum=float(payload.get("mean_brier", 0.0))
                * max(1, int(payload.get("observations", 0))),
            )


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Candidate(Generic[TArtifact]):
    """A proposal plus everything the committee said about it."""

    id: str
    artifact: TArtifact
    origin: str = ""                       # which generator produced it
    critiques: list[Critique] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def axis_scores(self) -> dict[str, float]:
        """Reliability-agnostic mean score per axis (used for Pareto ordering)."""
        buckets: dict[str, list[float]] = {}
        for critique in self.critiques:
            buckets.setdefault(critique.axis, []).append(critique.score)
        return {axis: statistics.fmean(scores) for axis, scores in buckets.items()}

    def all_findings(self) -> list[Finding]:
        return [f for c in self.critiques for f in c.findings]

    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.all_findings() if f.severity.blocks_delivery]

    @property
    def is_admissible(self) -> bool:
        return not self.blocking_findings()


class AxisAgreement(BaseModel):
    axis: str
    mean_score: float
    dispersion: float
    agreement: float = Field(ge=0.0, le=1.0)
    critic_count: int
    contested: bool = False


class ConsensusResult(BaseModel, Generic[TArtifact]):
    """The committee's decision, with the full reasoning attached."""

    model_config = {"arbitrary_types_allowed": True}

    winner_id: str
    winner_score: float
    ranking: list[dict[str, Any]] = Field(default_factory=list)
    pareto_front: list[str] = Field(default_factory=list)
    dominated: list[str] = Field(default_factory=list)
    disqualified: list[dict[str, Any]] = Field(default_factory=list)
    axis_agreement: list[AxisAgreement] = Field(default_factory=list)
    overall_agreement: float = 1.0
    contested_axes: list[str] = Field(default_factory=list)
    debate_triggered: bool = False
    debate_rounds: int = 0
    relaxed_admissibility: bool = False
    critic_weights: dict[str, float] = Field(default_factory=dict)
    method: str = "MACC/1.0"
    explanation: str = ""

    @property
    def is_confident(self) -> bool:
        return self.overall_agreement >= DEBATE_THRESHOLD and not self.relaxed_admissibility


# ---------------------------------------------------------------------------
# The algorithm
# ---------------------------------------------------------------------------


def dominates(a: dict[str, float], b: dict[str, float], axes: list[str]) -> bool:
    """Pareto dominance over the shared axis set."""
    at_least_as_good = all(a.get(ax, 0.0) >= b.get(ax, 0.0) - 1e-9 for ax in axes)
    strictly_better = any(a.get(ax, 0.0) > b.get(ax, 0.0) + 1e-9 for ax in axes)
    return at_least_as_good and strictly_better


def pareto_front(candidates: list[Candidate[Any]], axes: list[str]) -> tuple[list[Candidate[Any]], list[Candidate[Any]]]:
    """Split candidates into the non-dominated frontier and the dominated rest."""
    scores = {c.id: c.axis_scores() for c in candidates}
    front: list[Candidate[Any]] = []
    dominated: list[Candidate[Any]] = []
    for cand in candidates:
        if any(
            other.id != cand.id and dominates(scores[other.id], scores[cand.id], axes)
            for other in candidates
        ):
            dominated.append(cand)
        else:
            front.append(cand)
    return front, dominated


def _effective_weight(
    critique: Critique,
    ledger: CalibrationLedger,
    priorities: dict[str, float],
) -> float:
    reliability = ledger.reliability_of(critique.critic_id)
    priority = priorities.get(critique.axis, 1.0 / max(len(priorities), 1))
    # An analytical critic computing a code clause is not "confident" in the
    # same probabilistic sense as an LLM - it is simply correct. Give exact
    # computation a modest structural edge over sampled judgement.
    exactness = 1.12 if critique.analytical else 1.0
    penalty = 0.35 if critique.degraded else 1.0
    return max(1e-6, reliability * critique.confidence * priority * exactness * penalty)


def weighted_axis_scores(
    candidate: Candidate[Any],
    ledger: CalibrationLedger,
    priorities: dict[str, float],
) -> dict[str, float]:
    """Per-axis score, weighting each critic by learned reliability."""
    numer: dict[str, float] = {}
    denom: dict[str, float] = {}
    for critique in candidate.critiques:
        w = _effective_weight(critique, ledger, priorities)
        numer[critique.axis] = numer.get(critique.axis, 0.0) + w * critique.score
        denom[critique.axis] = denom.get(critique.axis, 0.0) + w
    return {axis: numer[axis] / denom[axis] for axis in numer if denom[axis] > 0}


def borda_scores(
    candidates: list[Candidate[Any]],
    ledger: CalibrationLedger,
    priorities: dict[str, float],
) -> dict[str, float]:
    """Reliability-weighted Borda count across every individual critique.

    Each critique is a voter. Ties share the average of the positions they span,
    which keeps the count fair when a critic genuinely cannot separate two
    designs rather than silently favouring insertion order.
    """
    if len(candidates) <= 1:
        return {c.id: 1.0 for c in candidates}

    points: dict[str, float] = {c.id: 0.0 for c in candidates}
    total_weight = 0.0

    # Group critiques by (critic, axis) - that pairing is one voter.
    voters: dict[tuple[str, str], list[tuple[str, Critique]]] = {}
    for cand in candidates:
        for critique in cand.critiques:
            voters.setdefault((critique.critic_id, critique.axis), []).append((cand.id, critique))

    n = len(candidates)
    for (_critic_id, _axis), ballots in voters.items():
        if len(ballots) < 2:
            continue
        weight = _effective_weight(ballots[0][1], ledger, priorities)
        total_weight += weight
        ordered = sorted(ballots, key=lambda pair: pair[1].score, reverse=True)

        i = 0
        while i < len(ordered):
            j = i
            while j + 1 < len(ordered) and abs(ordered[j + 1][1].score - ordered[i][1].score) < 1e-9:
                j += 1
            # Positions i..j are tied; share the Borda points across them.
            shared = statistics.fmean([n - 1 - k for k in range(i, j + 1)])
            for k in range(i, j + 1):
                points[ordered[k][0]] += weight * shared
            i = j + 1

    if total_weight <= 0:
        return {c.id: 0.0 for c in candidates}
    max_points = (n - 1) * total_weight
    if max_points <= 0:
        return {c.id: 0.0 for c in candidates}
    return {cid: value / max_points for cid, value in points.items()}


def agreement_analysis(
    candidate: Candidate[Any],
    ledger: CalibrationLedger,
    priorities: dict[str, float],
) -> tuple[list[AxisAgreement], float]:
    """Measure how much the committee actually agrees, axis by axis.

    Scores live in [0, 1], so the maximum possible standard deviation for a
    two-point split is 0.5. Dispersion is normalised against that bound, giving
    an agreement index that is comparable across axes with different critic
    counts.
    """
    grouped: dict[str, list[Critique]] = {}
    for critique in candidate.critiques:
        grouped.setdefault(critique.axis, []).append(critique)

    rows: list[AxisAgreement] = []
    for axis, critiques in sorted(grouped.items()):
        scores = [c.score for c in critiques]
        weights = [_effective_weight(c, ledger, priorities) for c in critiques]
        total_w = sum(weights) or 1.0
        mean = sum(s * w for s, w in zip(scores, weights, strict=True)) / total_w
        if len(scores) < 2:
            dispersion = 0.0
        else:
            variance = sum(w * (s - mean) ** 2 for s, w in zip(scores, weights, strict=True)) / total_w
            dispersion = math.sqrt(max(0.0, variance))
        agreement = max(0.0, 1.0 - min(1.0, dispersion / 0.5))
        rows.append(
            AxisAgreement(
                axis=axis,
                mean_score=round(mean, 4),
                dispersion=round(dispersion, 4),
                agreement=round(agreement, 4),
                critic_count=len(critiques),
                contested=agreement < DEBATE_THRESHOLD and len(critiques) > 1,
            )
        )

    if not rows:
        return [], 1.0
    # Weight the overall index by client priority: disagreement about something
    # the client cares about matters more than disagreement about something they
    # explicitly deprioritised.
    weights = [max(priorities.get(r.axis, 0.1), 0.02) for r in rows]
    overall = sum(r.agreement * w for r, w in zip(rows, weights, strict=True)) / (sum(weights) or 1.0)
    return rows, round(overall, 4)


def reach_consensus(
    candidates: list[Candidate[TArtifact]],
    *,
    priorities: dict[str, float] | None = None,
    ledger: CalibrationLedger | None = None,
    debate_rounds: int = 0,
) -> ConsensusResult[TArtifact]:
    """Run the full MACC procedure and return an auditable decision."""
    if not candidates:
        raise ValueError("reach_consensus requires at least one candidate")

    ledger = ledger or CalibrationLedger()
    axes = sorted({c.axis for cand in candidates for c in cand.critiques})
    priorities = _normalise_priorities(priorities, axes)

    # 1. Admissibility -----------------------------------------------------
    admissible = [c for c in candidates if c.is_admissible]
    relaxed = False
    disqualified: list[dict[str, Any]] = [
        {
            "candidate_id": c.id,
            "reasons": [f.render() for f in c.blocking_findings()[:6]],
        }
        for c in candidates
        if not c.is_admissible
    ]
    if not admissible:
        # Everything breaches something. Returning nothing is worse than
        # returning the least-bad option clearly labelled as non-compliant.
        relaxed = True
        admissible = sorted(candidates, key=lambda c: len(c.blocking_findings()))
        log_event(
            logger, "consensus.admissibility_relaxed", level=30,
            candidates=len(candidates), reason="all candidates carry critical findings",
        )

    # 2. Pareto ------------------------------------------------------------
    front, dominated = pareto_front(admissible, axes) if axes else (admissible, [])
    if not front:
        front = admissible

    # 3 & 4. Borda + utility ----------------------------------------------
    borda = borda_scores(front, ledger, priorities)
    ranking: list[dict[str, Any]] = []
    for cand in front:
        weighted = weighted_axis_scores(cand, ledger, priorities)
        utility = (
            sum(weighted.get(ax, 0.0) * priorities.get(ax, 0.0) for ax in axes)
            / (sum(priorities.get(ax, 0.0) for ax in axes) or 1.0)
        )
        combined = BORDA_WEIGHT * borda.get(cand.id, 0.0) + (1 - BORDA_WEIGHT) * utility
        rows, overall = agreement_analysis(cand, ledger, priorities)
        ranking.append(
            {
                "candidate_id": cand.id,
                "origin": cand.origin,
                "score": round(combined, 4),
                "utility": round(utility, 4),
                "borda": round(borda.get(cand.id, 0.0), 4),
                "agreement": overall,
                "axis_scores": {k: round(v, 4) for k, v in weighted.items()},
                "finding_counts": _severity_histogram(cand),
                "_agreement_rows": rows,
            }
        )

    ranking.sort(key=lambda r: (r["score"], r["agreement"]), reverse=True)
    best = ranking[0]
    best_rows: list[AxisAgreement] = best.pop("_agreement_rows")
    for row in ranking[1:]:
        row.pop("_agreement_rows", None)

    contested = [r.axis for r in best_rows if r.contested]
    result: ConsensusResult[TArtifact] = ConsensusResult(
        winner_id=str(best["candidate_id"]),
        winner_score=float(best["score"]),
        ranking=ranking,
        pareto_front=[c.id for c in front],
        dominated=[c.id for c in dominated],
        disqualified=disqualified,
        axis_agreement=best_rows,
        overall_agreement=float(best["agreement"]),
        contested_axes=contested,
        debate_triggered=float(best["agreement"]) < DEBATE_THRESHOLD,
        debate_rounds=debate_rounds,
        relaxed_admissibility=relaxed,
        critic_weights={
            cid: round(ledger.reliability_of(cid), 4)
            for cid in {c.critic_id for cand in candidates for c in cand.critiques}
        },
    )
    result.explanation = explain_consensus(result, candidates)
    log_event(
        logger, "consensus.decided",
        winner=result.winner_id, score=result.winner_score,
        agreement=result.overall_agreement, front=len(front),
        disqualified=len(disqualified), contested=len(contested),
    )
    return result


def _normalise_priorities(priorities: dict[str, float] | None, axes: list[str]) -> dict[str, float]:
    if not axes:
        return {}
    base = dict(priorities or {})
    # Any axis the client did not weight still gets a floor, so an unmentioned
    # but critical concern (structure, code compliance) is never zeroed out.
    floor = 0.5 / len(axes)
    filled = {ax: max(base.get(ax, 0.0), floor) for ax in axes}
    total = sum(filled.values()) or 1.0
    return {ax: value / total for ax, value in filled.items()}


def _severity_histogram(candidate: Candidate[Any]) -> dict[str, int]:
    counts = {s.value: 0 for s in Severity}
    for finding in candidate.all_findings():
        counts[finding.severity.value] += 1
    return {k: v for k, v in counts.items() if v}


def explain_consensus(result: ConsensusResult[Any], candidates: list[Candidate[Any]]) -> str:
    """Plain-language account of why this design won.

    Written for an architect defending the choice to a client, not for a
    developer reading a log.
    """
    by_id = {c.id: c for c in candidates}
    winner = by_id.get(result.winner_id)
    lines: list[str] = []

    total = len(candidates)
    lines.append(
        f"{total} candidate scheme{'s' if total != 1 else ''} were generated and "
        f"reviewed by an independent committee of critics."
    )

    if result.disqualified:
        lines.append(
            f"{len(result.disqualified)} were disqualified for critical issues "
            f"(statutory or physical), leaving {total - len(result.disqualified)} admissible."
        )
    if result.dominated:
        lines.append(
            f"{len(result.dominated)} were strictly out-performed on every measured "
            f"criterion and removed; {len(result.pareto_front)} remained on the trade-off frontier."
        )

    if winner is not None:
        top = sorted(
            result.axis_agreement, key=lambda r: r.mean_score, reverse=True
        )[:3]
        if top:
            strengths = ", ".join(f"{r.axis} ({r.mean_score:.2f})" for r in top)
            lines.append(f"The selected scheme scored highest on {strengths}.")
        weak = [r for r in result.axis_agreement if r.mean_score < 0.55]
        if weak:
            weaknesses = ", ".join(f"{r.axis} ({r.mean_score:.2f})" for r in weak)
            lines.append(f"It remains comparatively weak on {weaknesses}, which is where refinement should focus.")

    if result.contested_axes:
        lines.append(
            "The committee did not fully agree on "
            f"{', '.join(result.contested_axes)}. This signals a genuine design "
            "trade-off rather than an error, and is flagged for your decision."
        )
    else:
        lines.append(
            f"Committee agreement was high ({result.overall_agreement:.0%}), so the "
            "recommendation is stable across independent reviewers."
        )

    if result.relaxed_admissibility:
        lines.append(
            "WARNING: every candidate carried at least one critical finding. The "
            "least non-compliant option is shown, but it must not be issued for "
            "construction until those findings are resolved."
        )
    return " ".join(lines)


def merge_evidence(candidates: list[Candidate[Any]]) -> list[Evidence]:
    """Deduplicated evidence bundle across the whole committee, for the report."""
    seen: set[tuple[str, str, str]] = set()
    out: list[Evidence] = []
    for cand in candidates:
        for critique in cand.critiques:
            for item in [*critique.evidence, *(e for f in critique.findings for e in f.evidence)]:
                key = (item.kind.value, item.source, item.locator)
                if key not in seen:
                    seen.add(key)
                    out.append(item)
    return sorted(out, key=lambda e: (-e.relevance, e.source))
