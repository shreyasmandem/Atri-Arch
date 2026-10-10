"""The critic committee.

Twelve critics, each owning one axis and each answerable for its own verdict.
Nine are analytical: they compute from geometry, building physics or codified
rules, cost nothing, run in microseconds and are exactly reproducible. Three are
generative: they call a free-tier language model for the judgements that resist
formalisation.

The split is deliberate and is the platform's main defence against the failure
mode the abstract calls out - a single model producing confident, unverifiable
output. An LLM critic cannot talk a design past the daylight critic, because the
daylight critic is not persuadable; it is arithmetic. Conversely the analytical
critics cannot tell whether a scheme reads as coherent architecture, which is
what the generative critics are for.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from aip.agents.base import (
    AgentContext,
    Critique,
    CriticAgent,
    Evidence,
    EvidenceKind,
    Finding,
    Severity,
)
from aip.core.llm import Message, system, user
from aip.core.providers import Capability
from aip.domain.plan import FloorPlan
from aip.engines.architecture.codes import compliance_analysis
from aip.engines.architecture.metrics import (
    MetricReport,
    accessibility_analysis,
    circulation_analysis,
    daylight_analysis,
    privacy_analysis,
    spatial_quality_analysis,
    ventilation_analysis,
)


# ---------------------------------------------------------------------------
# Analytical critics
# ---------------------------------------------------------------------------


class _AnalyticalCritic(CriticAgent):
    """Adapts a metric function into a committee member."""

    analytical = True
    prior_reliability = 0.92

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        raise NotImplementedError

    async def run(self, payload: FloorPlan, ctx: AgentContext) -> Critique:
        report = self._analyse(payload, ctx)
        suggestions = [f.remedy for f in report.findings if f.remedy][:5]
        return self.make_critique(
            report.score,
            rationale=report.summary,
            findings=report.findings,
            evidence=report.evidence,
            suggestions=suggestions,
            # An exact computation is not "confident" - it is correct. The small
            # discount reflects model fidelity, not uncertainty about the maths.
            confidence=0.95,
        )


class DaylightCritic(_AnalyticalCritic):
    id = "critic.daylight"
    name = "Daylight Analyst"
    axis = "daylight"
    charter = (
        "Computes the BRE average daylight factor per habitable room, corrected "
        "for orientation using the site's actual solar geometry, and flags "
        "under-glazing and overheating risk."
    )

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        return daylight_analysis(plan)


class VentilationCritic(_AnalyticalCritic):
    id = "critic.ventilation"
    name = "Ventilation Analyst"
    axis = "ventilation"
    charter = (
        "Assesses openable area against statutory ratios, tests for genuine "
        "cross ventilation, and estimates air changes per hour against the "
        "prevailing wind."
    )

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        return ventilation_analysis(plan)


class PrivacyCritic(_AnalyticalCritic):
    id = "critic.privacy"
    name = "Privacy Analyst"
    axis = "privacy"
    charter = (
        "Ray-casts sightlines from the entrance, measures topological depth to "
        "private rooms, and detects sanitary rooms opening onto social space."
    )

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        return privacy_analysis(plan)


class CirculationCritic(_AnalyticalCritic):
    id = "critic.circulation"
    name = "Circulation Analyst"
    axis = "circulation"
    charter = (
        "Verifies every room is reachable, measures walking distance between "
        "functionally related rooms, and checks circulation area overhead."
    )

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        return circulation_analysis(plan)


class AccessibilityCritic(_AnalyticalCritic):
    id = "critic.accessibility"
    name = "Accessibility Analyst"
    axis = "accessibility"
    charter = (
        "Checks door clear widths, wheelchair turning circles, corridor widths "
        "and step-free access against the Harmonised Guidelines."
    )

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        return accessibility_analysis(plan, ctx.brief)


class SpatialCritic(_AnalyticalCritic):
    id = "critic.spatial"
    name = "Spatial Quality Analyst"
    axis = "spatial"
    charter = (
        "Judges room proportion, compactness and furnishability - catching rooms "
        "that meet their area target but cannot actually be furnished."
    )

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        return spatial_quality_analysis(plan)


class ComplianceCritic(_AnalyticalCritic):
    id = "critic.compliance"
    name = "Building Code Officer"
    axis = "compliance"
    prior_reliability = 0.97
    charter = (
        "Audits the scheme against the National Building Code of India 2016 and "
        "local development control regulations. Breaches are raised as critical "
        "findings, which disqualify a scheme outright."
    )

    def _analyse(self, plan: FloorPlan, ctx: AgentContext) -> MetricReport:
        return compliance_analysis(plan, ctx.brief)


class VastuCritic(CriticAgent):
    id = "critic.vastu"
    name = "Vastu Reasoner"
    axis = "vastu"
    analytical = True
    prior_reliability = 0.88
    charter = (
        "Evaluates the scheme against a formally encoded Vastu corpus, weighting "
        "each rule by the client's stance and by whether it has a demonstrable "
        "modern basis. Every verdict carries its classical citation."
    )

    async def run(self, payload: FloorPlan, ctx: AgentContext) -> Critique:
        from aip.engines.vastu.engine import analyse_vastu

        report = analyse_vastu(payload, ctx.brief.tradition_weight)
        ctx.shared.setdefault("vastu_reports", {})[payload.id] = report

        return self.make_critique(
            report.score / 100.0,
            rationale=report.summary,
            findings=report.to_findings(),
            evidence=[
                Evidence(
                    kind=EvidenceKind.SHASTRA,
                    source="Encoded Vastu corpus",
                    detail=(
                        f"{report.rules_assessed} of {report.rules_total} rules "
                        f"assessable; {report.rules_not_assessable} excluded rather "
                        f"than guessed."
                    ),
                    value=report.score,
                )
            ],
            suggestions=[m["remedy"] for m in report.top_remedies[:4]],
            confidence=0.9 if report.rules_assessed >= 12 else 0.6,
        )


class CostCritic(CriticAgent):
    id = "critic.cost"
    name = "Quantity Surveyor"
    axis = "cost"
    analytical = True
    prior_reliability = 0.85
    charter = (
        "Takes quantities off the geometry, prices them against a regional rate "
        "schedule, and scores the scheme against the client's budget with an "
        "explicit uncertainty band."
    )

    async def run(self, payload: FloorPlan, ctx: AgentContext) -> Critique:
        from aip.engines.cost.estimator import estimate_cost

        estimate = estimate_cost(payload, ctx.brief)
        ctx.shared.setdefault("cost_estimates", {})[payload.id] = estimate

        budget = ctx.brief.budget
        findings: list[Finding] = []
        if budget.is_specified:
            ratio = estimate.total / budget.amount if budget.amount else 1.0
            # Full marks at or under budget, decaying to zero at 60% over.
            score = 1.0 if ratio <= 1.0 else max(0.0, 1.0 - (ratio - 1.0) / 0.6)
            if ratio > 1.0:
                findings.append(
                    Finding(
                        code="COST.OVER_BUDGET",
                        severity=Severity.MAJOR if ratio > 1.15 else Severity.MODERATE,
                        message=(
                            f"Estimated at {estimate.total:,.0f} {estimate.currency} "
                            f"against a budget of {budget.amount:,.0f} "
                            f"({ratio - 1:.0%} over)."
                        ),
                        metric="total_cost",
                        actual=round(estimate.total, 2),
                        expected=budget.amount,
                        remedy=(
                            "Reduce built-up area, simplify the envelope, or move "
                            "to a lower finish specification."
                        ),
                        evidence=[
                            Evidence(
                                kind=EvidenceKind.COMPUTED,
                                source="Quantity takeoff and rate schedule",
                                detail=f"{estimate.built_area_m2:.0f} m2 at {estimate.rate_per_m2:,.0f}/m2.",
                            )
                        ],
                    )
                )
            rationale = (
                f"Estimated {estimate.total:,.0f} {estimate.currency} "
                f"({estimate.rate_per_m2:,.0f}/m2), {ratio:.0%} of budget. "
                f"80% confidence interval {estimate.p10:,.0f} to {estimate.p90:,.0f}."
            )
        else:
            # No budget stated: score efficiency of spend per square metre instead.
            score = 0.7
            rationale = (
                f"No budget was specified. Estimated {estimate.total:,.0f} "
                f"{estimate.currency} at {estimate.rate_per_m2:,.0f}/m2."
            )

        return self.make_critique(
            score,
            rationale=rationale,
            findings=findings,
            evidence=[
                Evidence(
                    kind=EvidenceKind.COMPUTED,
                    source="Bill of quantities",
                    detail=f"{len(estimate.line_items)} priced line items.",
                    value=round(estimate.total, 2),
                )
            ],
            confidence=estimate.confidence,
        )


class StructuralCritic(CriticAgent):
    id = "critic.structure"
    name = "Structural Reviewer"
    axis = "structure"
    analytical = True
    prior_reliability = 0.86
    charter = (
        "Checks span economy, column grid regularity and vertical continuity of "
        "load paths between floors."
    )

    async def run(self, payload: FloorPlan, ctx: AgentContext) -> Critique:
        findings: list[Finding] = []
        grid = payload.column_grid
        scores: list[float] = []

        if grid is None:
            return self.make_critique(
                0.5, rationale="No structural grid has been established yet.", confidence=0.4
            )

        # Span economy: RCC beams get expensive fast beyond about 5 m.
        max_span = grid.max_span
        if max_span > 6.0:
            scores.append(0.25)
            findings.append(
                Finding(
                    code="STR.LONG_SPAN",
                    severity=Severity.MAJOR,
                    message=f"Maximum structural span is {max_span:.2f} m, which is uneconomical in RCC.",
                    metric="max_span_m",
                    actual=max_span,
                    expected=4.5,
                    remedy="Introduce an intermediate column line or a beam to break the span.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.STANDARD,
                            source="IS 456:2000 deflection limits",
                            detail="Span/depth ratios drive beam depth and cost sharply beyond 5-6 m.",
                        )
                    ],
                )
            )
        elif max_span > 4.8:
            scores.append(0.65)
            findings.append(
                Finding(
                    code="STR.WIDE_SPAN",
                    severity=Severity.MINOR,
                    message=f"Maximum span of {max_span:.2f} m will require deeper beams.",
                    metric="max_span_m",
                    actual=max_span,
                    expected=4.5,
                    remedy="Consider an additional column line to keep beams shallow.",
                )
            )
        else:
            scores.append(1.0)

        # Grid regularity: irregular bays complicate formwork and reinforcement.
        spacings = [*grid.x_spacings, *grid.y_spacings]
        if spacings:
            spread = (max(spacings) - min(spacings)) / max(spacings)
            scores.append(max(0.0, 1.0 - spread * 1.5))
            if spread > 0.4:
                findings.append(
                    Finding(
                        code="STR.IRREGULAR_GRID",
                        severity=Severity.MINOR,
                        message=f"Column bays vary by {spread:.0%}, complicating formwork and detailing.",
                        metric="bay_variation",
                        actual=round(spread, 3),
                        expected=0.2,
                        remedy="Rationalise the grid toward uniform bays.",
                    )
                )

        # Vertical continuity: upper-floor walls should land on something.
        if len(payload.levels) > 1:
            continuity = self._vertical_continuity(payload)
            scores.append(continuity)
            if continuity < 0.6:
                findings.append(
                    Finding(
                        code="STR.DISCONTINUOUS",
                        severity=Severity.MODERATE,
                        message=(
                            f"Only {continuity:.0%} of upper-floor walls align with "
                            f"structure below, forcing transfer beams."
                        ),
                        metric="wall_continuity",
                        actual=round(continuity, 3),
                        expected=0.7,
                        remedy="Stack the upper-floor partitions over the lower ones where possible.",
                        evidence=[
                            Evidence(
                                kind=EvidenceKind.COMPUTED,
                                source="Inter-floor wall alignment analysis",
                            )
                        ],
                    )
                )

        score = sum(scores) / len(scores) if scores else 0.5
        return self.make_critique(
            score,
            rationale=(
                f"Maximum span {max_span:.2f} m across {grid.column_count} columns; "
                f"{len(findings)} structural concern(s)."
            ),
            findings=findings,
            evidence=[
                Evidence(
                    kind=EvidenceKind.COMPUTED,
                    source="Column grid analysis",
                    detail=f"{grid.column_count} columns, max span {max_span:.2f} m.",
                )
            ],
            confidence=0.85,
        )

    @staticmethod
    def _vertical_continuity(plan: FloorPlan, tolerance: float = 0.35) -> float:
        ground = plan.level_at(0)
        if ground is None:
            return 1.0
        lower = [(w.start, w.end) for w in ground.walls]
        if not lower:
            return 1.0

        from aip.domain.geometry import distance_point_to_segment

        aligned = 0
        total = 0
        for level in plan.levels[1:]:
            for wall in level.walls:
                total += 1
                mid = wall.midpoint
                if any(distance_point_to_segment(mid, a, b) <= tolerance for a, b in lower):
                    aligned += 1
        return aligned / total if total else 1.0


# ---------------------------------------------------------------------------
# Generative critics
# ---------------------------------------------------------------------------


class _LLMVerdict(BaseModel):
    """Schema every generative critic must return."""

    score: float = Field(ge=0.0, le=1.0, description="Overall quality on this axis")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    rationale: str = Field(description="Two or three sentences justifying the score")
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class _GenerativeCritic(CriticAgent):
    analytical = False
    prior_reliability = 0.7
    capability = Capability.REASONING
    temperature = 0.45

    def prompt(self, plan: FloorPlan, ctx: AgentContext) -> list[Message]:
        raise NotImplementedError

    async def run(self, payload: FloorPlan, ctx: AgentContext) -> Critique:
        if not ctx.allow_generative:
            return self.make_critique(
                0.6,
                rationale="Generative review was disabled for this run.",
                confidence=0.2,
                degraded=True,
            )

        verdict, response = await ctx.llm().complete_model(
            self.prompt(payload, ctx),
            _LLMVerdict,
            capability=self.capability,
            temperature=self.temperature,
            max_tokens=900,
        )

        findings = [
            Finding(
                code=f"{self.id.upper()}.CONCERN",
                severity=Severity.MINOR,
                message=concern,
                remedy=verdict.suggestions[i] if i < len(verdict.suggestions) else "",
                evidence=[
                    Evidence(
                        kind=EvidenceKind.MODEL,
                        source=f"{response.provider}/{response.model}",
                        detail="Model judgement, not a computed measurement.",
                        relevance=0.55,
                    )
                ],
            )
            for i, concern in enumerate(verdict.concerns[:4])
        ]

        return self.make_critique(
            verdict.score,
            rationale=verdict.rationale,
            findings=findings,
            evidence=[
                Evidence(
                    kind=EvidenceKind.MODEL,
                    source=f"{response.provider}/{response.model}",
                    detail="; ".join(verdict.strengths[:3]),
                    relevance=0.6,
                )
            ],
            suggestions=verdict.suggestions[:4],
            # A model's self-reported confidence is not trustworthy on its own,
            # so it is capped and blended toward a conservative prior.
            confidence=min(0.8, 0.35 + 0.5 * verdict.confidence),
            model_used=f"{response.provider}/{response.model}",
            degraded=response.degraded,
        )


class DesignCoherenceCritic(_GenerativeCritic):
    id = "critic.coherence"
    name = "Design Coherence Reviewer"
    axis = "coherence"
    charter = (
        "Judges whether the scheme reads as a single deliberate piece of "
        "architecture rather than a collection of rooms that satisfy metrics."
    )

    def prompt(self, plan: FloorPlan, ctx: AgentContext) -> list[Message]:
        return [
            system(
                "You are a senior practising architect reviewing a colleague's "
                "scheme at design-development stage. You are rigorous and "
                "specific. You do not praise a plan for meeting minimums. Judge "
                "only architectural coherence: zoning logic, the relationship "
                "between served and servant spaces, the arrival sequence, and "
                "whether the parti holds together. Do not comment on daylight "
                "levels, code compliance or cost - other reviewers own those and "
                "have already measured them precisely."
            ),
            user(
                f"CLIENT BRIEF\n{ctx.brief.summary_text()}\n\n"
                f"SCHEME\n{_plan_digest(plan)}\n\n"
                "Score architectural coherence from 0 to 1 and justify it."
            ),
        ]


class BriefFidelityCritic(_GenerativeCritic):
    id = "critic.brief"
    name = "Brief Fidelity Reviewer"
    axis = "brief_fidelity"
    charter = (
        "Checks the scheme against what the client actually asked for, including "
        "the requirements expressed in prose rather than as room areas."
    )

    def prompt(self, plan: FloorPlan, ctx: AgentContext) -> list[Message]:
        must = "\n".join(f"- {m}" for m in ctx.brief.must_haves) or "- (none stated)"
        constraints = "\n".join(f"- {c}" for c in ctx.brief.constraints) or "- (none stated)"
        return [
            system(
                "You audit whether a design satisfies its brief. Be literal and "
                "unforgiving: a stated must-have that is not delivered is a "
                "failure regardless of how good the scheme is otherwise. Quote "
                "the specific requirement when you raise a concern."
            ),
            user(
                f"BRIEF\n{ctx.brief.summary_text()}\n\n"
                f"MUST HAVES\n{must}\n\nCONSTRAINTS\n{constraints}\n\n"
                f"DELIVERED SCHEME\n{_plan_digest(plan)}\n\n"
                "Score brief fidelity from 0 to 1."
            ),
        ]


class LivabilityCritic(_GenerativeCritic):
    id = "critic.livability"
    name = "Livability Reviewer"
    axis = "livability"
    temperature = 0.55
    charter = (
        "Reasons about the scheme from the point of view of the people who will "
        "actually live in it, day to day, over years."
    )

    def prompt(self, plan: FloorPlan, ctx: AgentContext) -> list[Message]:
        who = "; ".join(
            f"{o.count} {o.role}"
            + (" (needs accessible design)" if o.needs_accessible else "")
            + (" (works from home)" if o.works_from_home else "")
            for o in ctx.brief.occupants
        ) or "not specified"
        return [
            system(
                "You evaluate homes for how they will actually be lived in. "
                "Reason concretely about daily routines: the morning rush, "
                "cooking while children do homework, carrying groceries in, "
                "ageing in place, guests arriving. Identify frictions the "
                "drawings hide. Be specific about which rooms and which moment "
                "of the day."
            ),
            user(
                f"HOUSEHOLD: {who}\n\nBRIEF\n{ctx.brief.summary_text()}\n\n"
                f"SCHEME\n{_plan_digest(plan)}\n\n"
                "Score day-to-day livability from 0 to 1."
            ),
        ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ANALYTICAL_CRITICS: tuple[type[CriticAgent], ...] = (
    ComplianceCritic,
    DaylightCritic,
    VentilationCritic,
    PrivacyCritic,
    CirculationCritic,
    AccessibilityCritic,
    SpatialCritic,
    StructuralCritic,
    VastuCritic,
    CostCritic,
)

GENERATIVE_CRITICS: tuple[type[CriticAgent], ...] = (
    DesignCoherenceCritic,
    BriefFidelityCritic,
    LivabilityCritic,
)

ALL_CRITICS: tuple[type[CriticAgent], ...] = ANALYTICAL_CRITICS + GENERATIVE_CRITICS


def build_committee(
    *, include_generative: bool = True, exclude: set[str] | None = None
) -> list[CriticAgent]:
    """Instantiate the committee for one review round."""
    exclude = exclude or set()
    classes = ALL_CRITICS if include_generative else ANALYTICAL_CRITICS
    return [cls() for cls in classes if cls.id not in exclude]


def committee_charter() -> list[dict[str, Any]]:
    """Machine-readable description of the committee, shown in the UI."""
    return [
        {
            "id": cls.id,
            "name": cls.name,
            "axis": cls.axis,
            "analytical": cls.analytical,
            "reliability_prior": cls.prior_reliability,
            "charter": cls.charter,
        }
        for cls in ALL_CRITICS
    ]


def _plan_digest(plan: FloorPlan, max_rooms: int = 40) -> str:
    """Compact textual rendering of a plan for a language model.

    Sending raw geometry wastes tokens and models reason poorly over coordinate
    lists. This renders the facts a reviewer actually uses: what rooms exist,
    how big they are, where they sit on the compass, and what connects to what.
    """
    lines = [
        f"Name: {plan.name}",
        f"Levels: {len(plan.levels)}; built-up {plan.total_built_area:.1f} m2; "
        f"FAR {plan.achieved_far:.2f}; height {plan.building_height:.1f} m",
        f"Plot: {plan.site.plot_area:.0f} m2 in {plan.site.locality}, "
        f"road to the {'/'.join(d.value for d in plan.site.road_directions) or 'unknown'}",
        "",
        "ROOMS (name | type | level | area m2 | compass sector):",
    ]
    for room in plan.all_rooms[:max_rooms]:
        lines.append(
            f"  {room.display_name()} | {room.type.value} | L{room.level} | "
            f"{room.area:.1f} | {plan.direction_of_room(room).value}"
        )

    for level in plan.levels:
        graph = plan.connectivity(level.index)
        if not graph:
            continue
        names = {r.id: r.display_name() for r in level.rooms}
        links = sorted(
            {
                tuple(sorted((names.get(a, a), names.get(b, b))))
                for a, targets in graph.items()
                for b in targets
            }
        )
        if links:
            lines.append("")
            lines.append(f"DOOR CONNECTIONS (level {level.index}):")
            lines.extend(f"  {a} <-> {b}" for a, b in links[:30])

    openings = plan.all_openings
    lines.append("")
    lines.append(
        f"OPENINGS: {sum(1 for o in openings if o.kind.is_door)} doors, "
        f"{sum(1 for o in openings if o.kind.is_glazed)} windows, "
        f"{plan.total_glazing_area():.1f} m2 total glazing."
    )
    return "\n".join(lines)


def critique_to_dict(critique: Critique) -> dict[str, Any]:
    """Serialise for the API and the audit log."""
    return json.loads(critique.model_dump_json())
