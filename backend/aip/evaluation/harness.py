"""Evaluation harness.

Measures the metrics the research abstract commits to, and - more importantly -
runs the **ablations** that test whether the committee is actually doing
anything. A multi-agent system that performs identically to one agent is an
expensive way to build a single agent, so the headline experiment here is not
"does it work" but "does the committee beat its own parts".

Three ablations run against the same briefs and the same seeds:

* ``single_critic``  - one weighted-sum objective, the conventional design.
* ``no_pareto``      - the full committee, but ranked by weighted sum only.
* ``full``           - Pareto filtering plus reliability-weighted Borda.

What is honestly measurable without human subjects is measured. User
satisfaction and expert-rated design quality require a study this harness cannot
run alone, and are reported as ``requires_human_study`` rather than proxied by a
number that sounds like evidence.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aip.agents.consensus import Candidate, reach_consensus
from aip.core.logging import get_logger, log_event
from aip.domain.brief import (
    AccessibilityLevel,
    Budget,
    ClientBrief,
    DesignStyle,
    Occupant,
    RoomRequirement,
    StylePreference,
    VastuStance,
)
from aip.domain.geometry import Direction, Vec2
from aip.domain.plan import FloorPlan, RoomType, Site
from aip.engines.architecture.codes import compliance_analysis
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator
from aip.engines.architecture.metrics import analyse_all
from aip.engines.cost.estimator import estimate_cost
from aip.engines.vastu.engine import analyse_vastu

logger = get_logger("aip.evaluation")


# ---------------------------------------------------------------------------
# Benchmark briefs
# ---------------------------------------------------------------------------


def _site(width: float, depth: float, road: Direction, **kw: Any) -> Site:
    return Site(
        boundary=[Vec2(0, 0), Vec2(width, 0), Vec2(width, depth), Vec2(0, depth)],
        road_directions=[road],
        **kw,
    )


def benchmark_briefs() -> list[ClientBrief]:
    """Eight briefs spanning the cases an Indian practice actually receives.

    Chosen for coverage of the failure modes rather than for flattering results:
    a narrow urban plot, a south-facing road that puts Vastu and access in direct
    conflict, an over-constrained budget, and a multi-generational programme with
    an accessibility requirement.
    """
    return [
        ClientBrief(
            project_name="Compact 2BHK, north road",
            site=_site(9, 15, Direction.N),
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=18),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=9),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=14),
                RoomRequirement(type=RoomType.BEDROOM, preferred_area=11),
                RoomRequirement(type=RoomType.BATHROOM, count=2, preferred_area=4.5, needs_daylight=False),
            ],
            occupants=[Occupant(role="adult", count=2)],
            budget=Budget(amount=3_800_000),
            vastu=VastuStance.BALANCED,
        ),
        ClientBrief(
            project_name="Standard 3BHK, east road",
            site=_site(12, 18, Direction.E),
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=22),
                RoomRequirement(type=RoomType.DINING, preferred_area=13),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=11),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=18, attached_bathroom=True),
                RoomRequirement(type=RoomType.BEDROOM, count=2, preferred_area=13),
                RoomRequirement(type=RoomType.BATHROOM, count=2, preferred_area=5, needs_daylight=False),
                RoomRequirement(type=RoomType.PUJA, preferred_area=3.5, needs_external_wall=False),
            ],
            occupants=[Occupant(role="adult", count=2), Occupant(role="child", count=2)],
            budget=Budget(amount=6_500_000),
            vastu=VastuStance.BALANCED,
        ),
        ClientBrief(
            project_name="Vastu-orthodox, south road (rule conflict)",
            site=_site(13, 17, Direction.S),
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=22),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=11),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=17),
                RoomRequirement(type=RoomType.BEDROOM, count=2, preferred_area=12),
                RoomRequirement(type=RoomType.PUJA, preferred_area=4, needs_external_wall=False),
                RoomRequirement(type=RoomType.BATHROOM, count=2, preferred_area=5, needs_daylight=False),
            ],
            occupants=[Occupant(role="adult", count=2), Occupant(role="elder", count=2)],
            budget=Budget(amount=7_200_000),
            vastu=VastuStance.ORTHODOX,
        ),
        ClientBrief(
            project_name="Narrow urban plot",
            site=_site(6.5, 20, Direction.N, setback_left=0.6, setback_right=0.6),
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=16),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=8),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=13),
                RoomRequirement(type=RoomType.BEDROOM, preferred_area=10),
                RoomRequirement(type=RoomType.BATHROOM, count=2, preferred_area=4, needs_daylight=False),
            ],
            occupants=[Occupant(role="adult", count=2), Occupant(role="child", count=1)],
            budget=Budget(amount=4_200_000),
            vastu=VastuStance.ADVISORY,
        ),
        ClientBrief(
            project_name="Multi-generational, accessible",
            site=_site(15, 20, Direction.W),
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=26),
                RoomRequirement(type=RoomType.DINING, preferred_area=15),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=13),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=20, attached_bathroom=True),
                RoomRequirement(type=RoomType.BEDROOM, count=2, preferred_area=14),
                RoomRequirement(type=RoomType.GUEST_BEDROOM, preferred_area=13),
                RoomRequirement(type=RoomType.BATHROOM, count=3, preferred_area=6, needs_daylight=False),
                RoomRequirement(type=RoomType.PUJA, preferred_area=4, needs_external_wall=False),
                RoomRequirement(type=RoomType.UTILITY, preferred_area=6),
            ],
            occupants=[
                Occupant(role="adult", count=2),
                Occupant(role="child", count=2),
                Occupant(role="elder", count=2, needs_accessible=True),
            ],
            budget=Budget(amount=11_000_000),
            vastu=VastuStance.STRICT,
            accessibility=AccessibilityLevel.WHEELCHAIR,
        ),
        ClientBrief(
            project_name="Budget-constrained (deliberately under-funded)",
            site=_site(11, 14, Direction.NE),
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=20),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=10),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=16),
                RoomRequirement(type=RoomType.BEDROOM, count=2, preferred_area=12),
                RoomRequirement(type=RoomType.BATHROOM, count=2, preferred_area=4.5, needs_daylight=False),
            ],
            occupants=[Occupant(role="adult", count=2), Occupant(role="child", count=1)],
            budget=Budget(amount=2_600_000),
            vastu=VastuStance.IGNORE,
        ),
        ClientBrief(
            project_name="Two-storey villa",
            site=_site(14, 19, Direction.NW),
            levels=2,
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=26, level=0),
                RoomRequirement(type=RoomType.DINING, preferred_area=14, level=0),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=12, level=0),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=20, level=1),
                RoomRequirement(type=RoomType.BEDROOM, count=2, preferred_area=14, level=1),
                RoomRequirement(type=RoomType.BATHROOM, count=3, preferred_area=5, needs_daylight=False),
                RoomRequirement(type=RoomType.STUDY, preferred_area=10, level=1),
            ],
            occupants=[Occupant(role="adult", count=2, works_from_home=True), Occupant(role="child", count=2)],
            budget=Budget(amount=13_500_000),
            vastu=VastuStance.BALANCED,
            style=StylePreference(styles=[DesignStyle.TROPICAL_MODERN]),
        ),
        ClientBrief(
            project_name="Work-from-home couple",
            site=_site(10, 16, Direction.E),
            requirements=[
                RoomRequirement(type=RoomType.LIVING, preferred_area=20),
                RoomRequirement(type=RoomType.KITCHEN, preferred_area=10),
                RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=16),
                RoomRequirement(type=RoomType.HOME_OFFICE, count=2, preferred_area=10,
                                preferred_direction=Direction.N),
                RoomRequirement(type=RoomType.BATHROOM, count=2, preferred_area=5, needs_daylight=False),
            ],
            occupants=[Occupant(role="adult", count=2, works_from_home=True)],
            budget=Budget(amount=5_800_000),
            vastu=VastuStance.ADVISORY,
        ),
    ]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TrialResult:
    brief: str
    arm: str
    plan_id: str
    seconds: float

    compliance: float
    critical_breaches: int
    daylight: float
    ventilation: float
    privacy: float
    circulation: float
    accessibility: float
    spatial: float
    vastu: float
    programme_error: float
    cost_total: float
    budget_error: float
    explainability: float

    @property
    def composite(self) -> float:
        """Overall design quality, weighting the prerequisites highest.

        Compliance is doubled because a non-compliant scheme has no value at
        any level of comfort, and that asymmetry has to appear in the number.
        """
        return round(
            (2 * self.compliance + self.daylight + self.ventilation + self.privacy
             + self.circulation + self.accessibility + self.spatial) / 8,
            4,
        )


class EvaluationReport(dict):
    """A plain dict so it serialises straight to JSON for the paper."""


def _programme_error(plan: FloorPlan, brief: ClientBrief) -> float:
    """Mean absolute relative error between requested and delivered room areas."""
    wanted: dict[RoomType, list[float]] = {}
    for req in brief.expanded_requirements():
        wanted.setdefault(req.type, []).append(req.target_area)

    errors: list[float] = []
    for room_type, targets in wanted.items():
        got = sorted((r.area for r in plan.rooms_of(room_type)), reverse=True)
        for i, target in enumerate(sorted(targets, reverse=True)):
            actual = got[i] if i < len(got) else 0.0
            errors.append(abs(actual - target) / target)
    return round(statistics.fmean(errors), 4) if errors else 1.0


def _explainability(plan: FloorPlan, brief: ClientBrief) -> float:
    """Fraction of findings that carry both a citation and a concrete remedy.

    Explainability is the abstract's headline claim, so it needs an operational
    definition rather than a vibe. A finding is 'explained' when it names what
    is wrong, cites the authority for that judgement, and states the fix.
    """
    reports = analyse_all(plan, brief)
    compliance = compliance_analysis(plan, brief)
    vastu = analyse_vastu(plan, brief.tradition_weight)

    findings = [f for r in reports.values() for f in r.findings]
    findings += compliance.findings
    findings += vastu.to_findings()
    if not findings:
        return 1.0

    explained = sum(
        1 for f in findings
        if f.message and f.remedy and (f.evidence or f.metric)
    )
    return round(explained / len(findings), 4)


def _evaluate_plan(plan: FloorPlan, brief: ClientBrief, arm: str, seconds: float) -> TrialResult:
    reports = analyse_all(plan, brief)
    compliance = compliance_analysis(plan, brief)
    vastu = analyse_vastu(plan, brief.tradition_weight)
    cost = estimate_cost(plan, brief, monte_carlo_runs=600)

    budget_error = (
        abs(cost.total - brief.budget.amount) / brief.budget.amount
        if brief.budget.is_specified else float("nan")
    )

    return TrialResult(
        brief=brief.project_name,
        arm=arm,
        plan_id=plan.id,
        seconds=round(seconds, 3),
        compliance=compliance.score,
        critical_breaches=int(compliance.detail.get("critical_breaches", 0)),
        daylight=reports["daylight"].score,
        ventilation=reports["ventilation"].score,
        privacy=reports["privacy"].score,
        circulation=reports["circulation"].score,
        accessibility=reports["accessibility"].score,
        spatial=reports["spatial"].score,
        vastu=round(vastu.score / 100, 4),
        programme_error=_programme_error(plan, brief),
        cost_total=cost.total,
        budget_error=round(budget_error, 4) if budget_error == budget_error else -1.0,
        explainability=_explainability(plan, brief),
    )


# ---------------------------------------------------------------------------
# Ablation arms
# ---------------------------------------------------------------------------


def _candidates_from(plans: list[FloorPlan], brief: ClientBrief) -> list[Candidate[FloorPlan]]:
    """Build committee candidates using only the analytical critics.

    The ablation deliberately excludes generative critics so the comparison is
    reproducible and provider-independent: the question is whether *consensus
    structure* helps, not whether a particular model was available that day.
    """
    from aip.agents.base import Critique

    candidates: list[Candidate[FloorPlan]] = []
    for plan in plans:
        reports = analyse_all(plan, brief)
        compliance = compliance_analysis(plan, brief)
        vastu = analyse_vastu(plan, brief.tradition_weight)

        critiques = [
            Critique(critic_id=f"critic.{axis}", axis=axis, score=report.score,
                     confidence=0.95, analytical=True, findings=report.findings)
            for axis, report in reports.items()
        ]
        critiques.append(Critique(
            critic_id="critic.compliance", axis="compliance", score=compliance.score,
            confidence=0.97, analytical=True, findings=compliance.findings,
        ))
        critiques.append(Critique(
            critic_id="critic.vastu", axis="vastu", score=vastu.score / 100,
            confidence=0.9, analytical=True, findings=vastu.to_findings(),
        ))
        candidates.append(Candidate(id=plan.id, artifact=plan, origin=plan.name, critiques=critiques))
    return candidates


def _arm_single_critic(plans: list[FloorPlan], brief: ClientBrief) -> FloorPlan:
    """Baseline: one scalar objective, the conventional single-agent design."""
    def score(plan: FloorPlan) -> float:
        reports = analyse_all(plan, brief)
        return statistics.fmean([r.score for r in reports.values()])

    return max(plans, key=score)


def _arm_no_pareto(plans: list[FloorPlan], brief: ClientBrief) -> FloorPlan:
    """The full committee, but collapsed to a weighted sum with no Pareto step."""
    candidates = _candidates_from(plans, brief)
    priorities = brief.priority_weights()
    best, best_score = plans[0], -1.0
    for candidate in candidates:
        axis_scores = candidate.axis_scores()
        total = statistics.fmean([
            axis_scores.get(axis, 0.5) * priorities.get(axis, 0.15)
            for axis in axis_scores
        ]) if axis_scores else 0.0
        if total > best_score:
            best_score, best = total, candidate.artifact
    return best


def _arm_full(plans: list[FloorPlan], brief: ClientBrief) -> FloorPlan:
    """The shipped procedure: admissibility, Pareto, then weighted Borda."""
    candidates = _candidates_from(plans, brief)
    result = reach_consensus(candidates, priorities=brief.priority_weights())
    return next((c.artifact for c in candidates if c.id == result.winner_id), plans[0])


ARMS: dict[str, Callable[[list[FloorPlan], ClientBrief], FloorPlan]] = {
    "single_critic": _arm_single_critic,
    "no_pareto": _arm_no_pareto,
    "full": _arm_full,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_evaluation(
    *,
    briefs: list[ClientBrief] | None = None,
    candidates_per_brief: int = 4,
    seed: int = 4242,
    output: Path | None = None,
) -> EvaluationReport:
    """Run every arm over every brief and produce the report."""
    briefs = briefs or benchmark_briefs()
    trials: list[TrialResult] = []

    for index, brief in enumerate(briefs):
        started = time.perf_counter()
        generator = LayoutGenerator(
            brief, GeneratorConfig(population=48, generations=48, seed=seed + index * 31)
        )
        plans = generator.generate(count=candidates_per_brief)
        generation_time = time.perf_counter() - started
        if not plans:
            log_event(logger, "eval.no_plans", level=30, brief=brief.project_name)
            continue

        for arm, chooser in ARMS.items():
            arm_started = time.perf_counter()
            chosen = chooser(plans, brief)
            elapsed = generation_time + (time.perf_counter() - arm_started)
            trials.append(_evaluate_plan(chosen, brief, arm, elapsed))

        log_event(
            logger, "eval.brief_done",
            brief=brief.project_name, plans=len(plans), seconds=round(generation_time, 2),
        )

    report = _summarise(trials, briefs)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        log_event(logger, "eval.written", path=str(output))
    return report


def _summarise(trials: list[TrialResult], briefs: list[ClientBrief]) -> EvaluationReport:
    by_arm: dict[str, list[TrialResult]] = {}
    for trial in trials:
        by_arm.setdefault(trial.arm, []).append(trial)

    def agg(rows: list[TrialResult], attr: str) -> dict[str, float]:
        values = [getattr(r, attr) for r in rows if getattr(r, attr) >= 0]
        if not values:
            return {"mean": -1.0, "median": -1.0, "min": -1.0, "max": -1.0}
        return {
            "mean": round(statistics.fmean(values), 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }

    arms: dict[str, Any] = {}
    for arm, rows in by_arm.items():
        arms[arm] = {
            "trials": len(rows),
            "composite_quality": {
                "mean": round(statistics.fmean([r.composite for r in rows]), 4),
                "median": round(statistics.median([r.composite for r in rows]), 4),
                "min": round(min(r.composite for r in rows), 4),
                "max": round(max(r.composite for r in rows), 4),
            },
            "compliance": agg(rows, "compliance"),
            "critical_breaches_total": sum(r.critical_breaches for r in rows),
            "daylight": agg(rows, "daylight"),
            "ventilation": agg(rows, "ventilation"),
            "privacy": agg(rows, "privacy"),
            "circulation": agg(rows, "circulation"),
            "accessibility": agg(rows, "accessibility"),
            "spatial": agg(rows, "spatial"),
            "vastu": agg(rows, "vastu"),
            "programme_error": agg(rows, "programme_error"),
            "budget_error": agg(rows, "budget_error"),
            "explainability": agg(rows, "explainability"),
            "seconds": agg(rows, "seconds"),
        }

    full = arms.get("full", {})
    single = arms.get("single_critic", {})
    lift = {}
    if full and single:
        for metric in ("composite_quality", "compliance", "vastu", "explainability"):
            a = full[metric]["mean"]
            b = single[metric]["mean"]
            lift[metric] = {
                "full": a,
                "single_critic": b,
                "absolute_gain": round(a - b, 4),
                "relative_gain_pct": round((a - b) / b * 100, 2) if b else None,
            }
        lift["critical_breaches"] = {
            "full": full["critical_breaches_total"],
            "single_critic": single["critical_breaches_total"],
        }

    return EvaluationReport({
        "harness_version": "1.0",
        "briefs": len(briefs),
        "trials": len(trials),
        "arms": arms,
        "ablation_lift": lift,
        "per_trial": [asdict(t) | {"composite": t.composite} for t in trials],
        "cost_usd": 0.0,
        "not_measured_without_human_study": {
            "user_satisfaction":
                "Requires a study with practising architects and their clients. "
                "No proxy is reported, because a synthetic stand-in for user "
                "satisfaction would be indistinguishable from an invented result.",
            "expert_design_quality":
                "Requires blind rating by qualified architects against schemes "
                "produced by human designers for the same briefs.",
            "recommendation_relevance":
                "Requires ground-truth relevance judgements on retrieved "
                "precedent. The corpus shipped here is too small to support a "
                "meaningful retrieval benchmark.",
        },
        "notes": [
            "All arms share the same generated candidate pool and the same seed, "
            "so differences isolate the selection procedure rather than the "
            "generator's luck.",
            "Generative critics are excluded from the ablation so results are "
            "reproducible and independent of which free tier was reachable.",
            "Cost error is measured against the client's stated budget, which is "
            "a constraint rather than ground truth. Accuracy against delivered "
            "cost requires completed projects and is what the calibration "
            "endpoint accumulates.",
        ],
    })


def main() -> None:  # pragma: no cover - CLI entry point
    import argparse

    from aip.core.logging import configure_logging

    parser = argparse.ArgumentParser(description="Run the AIP evaluation harness.")
    parser.add_argument("--out", type=Path, default=Path("../docs/evaluation.json"))
    parser.add_argument("--candidates", type=int, default=4)
    parser.add_argument("--seed", type=int, default=4242)
    args = parser.parse_args()

    configure_logging("INFO")
    report = run_evaluation(
        candidates_per_brief=args.candidates, seed=args.seed, output=args.out
    )

    print(f"\n{'arm':<16} {'quality':>8} {'compliance':>11} {'vastu':>7} "
          f"{'explain':>8} {'crit':>5} {'sec':>7}")
    print("-" * 68)
    for arm, data in report["arms"].items():
        print(
            f"{arm:<16} {data['composite_quality']['mean']:>8.4f} "
            f"{data['compliance']['mean']:>11.4f} {data['vastu']['mean']:>7.4f} "
            f"{data['explainability']['mean']:>8.4f} "
            f"{data['critical_breaches_total']:>5d} {data['seconds']['mean']:>7.2f}"
        )

    print("\nAblation lift (full committee versus a single weighted objective):")
    for metric, values in report["ablation_lift"].items():
        if isinstance(values, dict) and "absolute_gain" in values:
            rel = values["relative_gain_pct"]
            print(f"  {metric:<20} {values['absolute_gain']:+.4f}"
                  + (f"  ({rel:+.2f}%)" if rel is not None else ""))
    print(f"\nTotal model spend: ${report['cost_usd']:.2f}")


if __name__ == "__main__":  # pragma: no cover
    main()
