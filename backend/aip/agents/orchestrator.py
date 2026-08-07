"""The design pipeline.

Runs the full multi-agent cycle and emits progress events as it goes, so a
client watching in a browser sees the committee working rather than a spinner.

    brief -> interpret -> retrieve -> generate -> critique -> consensus
          -> [debate if contested] -> refine -> explain

The two conditional stages are what distinguish this from a linear chain:

* **Debate** fires only when the committee genuinely disagrees. Critics are
  shown each other's reasoning and may revise. Agreement reached after seeing
  opposing evidence is worth more than agreement reached in isolation, and
  persistent disagreement is reported to the architect as a real design tension
  rather than averaged into a misleadingly smooth number.

* **Refinement** fires only when the winning scheme carries fixable findings.
  The refiner applies the concrete remedies the critics named - widen this
  window, move that door - and the result is re-scored. A refinement that does
  not improve the score is discarded, so the loop cannot make things worse.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from aip.agents.base import (
    AgentContext,
    Critique,
    Evidence,
    Severity,
    collect_critiques,
    run_agents,
)
from aip.agents.consensus import (
    CalibrationLedger,
    Candidate,
    ConsensusResult,
    merge_evidence,
    reach_consensus,
)
from aip.agents.critics import build_committee, committee_charter
from aip.core.llm import LLMRouter, get_router, system, user
from aip.core.logging import get_logger, log_event, span, trace_context
from aip.core.providers import Capability
from aip.domain.brief import ClientBrief
from aip.domain.plan import FloorPlan
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator

logger = get_logger("aip.pipeline")


class ProgressEvent(BaseModel):
    """One step of the pipeline, streamed to the client."""

    stage: str
    status: str = "running"        # running | done | skipped | failed
    message: str = ""
    percent: float = 0.0
    detail: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: float = 0.0


class DesignResult(BaseModel):
    """Everything the pipeline produced."""

    model_config = {"arbitrary_types_allowed": True}

    session_id: str = ""
    trace_id: str = ""
    brief_summary: str = ""

    plans: list[FloorPlan] = Field(default_factory=list)
    winner: FloorPlan | None = None
    consensus: ConsensusResult | None = None
    critiques: dict[str, list[Critique]] = Field(default_factory=dict)

    vastu: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None

    explanation: str = ""
    recommendations: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    committee: list[dict[str, Any]] = Field(default_factory=list)

    debate_rounds: int = 0
    refinement_applied: bool = False
    refinement_delta: float = 0.0
    degraded: bool = False
    degraded_reason: str = ""

    duration_ms: float = 0.0
    model_usage: dict[str, Any] = Field(default_factory=dict)
    total_cost_usd: float = 0.0


@dataclass(slots=True)
class PipelineConfig:
    candidate_count: int = 3
    include_generative_critics: bool = True
    enable_debate: bool = True
    enable_refinement: bool = True
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    max_parallel_agents: int = 6
    agent_timeout_seconds: float = 90.0


ProgressCallback = Callable[[ProgressEvent], None] | None


class DesignPipeline:
    """Orchestrates generation, critique, consensus, refinement and explanation."""

    STAGES = (
        "interpret", "retrieve", "generate", "critique",
        "consensus", "debate", "refine", "explain",
    )

    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        router: LLMRouter | None = None,
        ledger: CalibrationLedger | None = None,
    ) -> None:
        self.config = config or PipelineConfig()
        self.router = router or get_router()
        self.ledger = ledger or CalibrationLedger()
        self._events: list[ProgressEvent] = []

    # ------------------------------------------------------------- public --

    async def run(
        self, brief: ClientBrief, *, on_progress: ProgressCallback = None
    ) -> DesignResult:
        """Execute the full pipeline."""
        started = time.perf_counter()
        with trace_context() as trace_id:
            result = DesignResult(trace_id=trace_id, brief_summary=brief.summary_text())
            ctx = AgentContext(
                brief=brief,
                trace_id=trace_id,
                router=self.router,
                budget_seconds=self.config.agent_timeout_seconds,
                allow_generative=self.config.include_generative_critics,
            )

            emit = self._emitter(on_progress)

            await self._stage_interpret(brief, ctx, emit)
            await self._stage_retrieve(brief, ctx, emit)
            plans = await self._stage_generate(brief, ctx, emit)
            result.plans = plans

            candidates = await self._stage_critique(plans, ctx, emit)
            result.critiques = {c.id: c.critiques for c in candidates}

            consensus = await self._stage_consensus(candidates, brief, emit)
            result.consensus = consensus

            if self.config.enable_debate and consensus.debate_triggered:
                consensus = await self._stage_debate(candidates, ctx, consensus, emit)
                result.consensus = consensus
                result.debate_rounds = consensus.debate_rounds
            else:
                emit("debate", "skipped", "Committee agreement was high; no debate needed.", 0.62)

            winner = next((c for c in candidates if c.id == consensus.winner_id), candidates[0])
            result.winner = winner.artifact

            if self.config.enable_refinement:
                refined, delta = await self._stage_refine(winner, ctx, emit)
                if refined is not None:
                    result.winner = refined
                    result.refinement_applied = True
                    result.refinement_delta = delta
            else:
                emit("refine", "skipped", "Refinement disabled for this run.", 0.82)

            await self._stage_explain(result, ctx, emit)

            # Attach the specialist reports the critics already computed, so the
            # API does not recompute them.
            plan_id = winner.artifact.id
            vastu_reports = ctx.shared.get("vastu_reports", {})
            cost_estimates = ctx.shared.get("cost_estimates", {})
            if plan_id in vastu_reports:
                result.vastu = vastu_reports[plan_id].model_dump()
            if plan_id in cost_estimates:
                result.cost = cost_estimates[plan_id].model_dump()

            result.evidence = merge_evidence(candidates)[:40]
            result.committee = committee_charter()
            result.duration_ms = (time.perf_counter() - started) * 1000
            result.model_usage = self.router.ledger.summary()
            result.total_cost_usd = self.router.ledger.total_cost_usd

            degraded = [c for cand in candidates for c in cand.critiques if c.degraded]
            if degraded:
                result.degraded = True
                result.degraded_reason = (
                    f"{len(degraded)} generative critique(s) ran in degraded mode "
                    f"because no model provider was reachable. All analytical "
                    f"results - geometry, code compliance, Vastu, cost - are "
                    f"unaffected and remain valid."
                )

            log_event(
                logger, "pipeline.complete",
                plans=len(plans), winner=consensus.winner_id,
                score=consensus.winner_score, agreement=consensus.overall_agreement,
                ms=round(result.duration_ms), cost_usd=result.total_cost_usd,
            )
            return result

    async def stream(
        self, brief: ClientBrief
    ) -> AsyncIterator[tuple[ProgressEvent | None, DesignResult | None]]:
        """Async generator yielding progress, then the final result.

        Drives the server-sent-events endpoint. The pipeline runs as a task while
        events drain from a queue, so progress reaches the browser as it happens
        rather than in one burst at the end.
        """
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()

        def on_progress(event: ProgressEvent) -> None:
            queue.put_nowait(event)

        task = asyncio.create_task(self.run(brief, on_progress=on_progress))

        while True:
            drain = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({drain, task}, return_when=asyncio.FIRST_COMPLETED)
            if drain in done:
                event = drain.result()
                if event is not None:
                    yield event, None
                continue
            drain.cancel()
            while not queue.empty():
                event = queue.get_nowait()
                if event is not None:
                    yield event, None
            yield None, await task
            return

    # ------------------------------------------------------------- stages --

    def _emitter(self, on_progress: ProgressCallback):
        start = time.perf_counter()

        def emit(
            stage: str, status: str, message: str, percent: float, **detail: Any
        ) -> None:
            event = ProgressEvent(
                stage=stage,
                status=status,
                message=message,
                percent=round(percent, 3),
                detail=detail,
                elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            self._events.append(event)
            if on_progress:
                on_progress(event)

        return emit

    async def _stage_interpret(self, brief: ClientBrief, ctx: AgentContext, emit) -> None:
        """Fill gaps in the brief that the client did not think to state."""
        emit("interpret", "running", "Interpreting the brief...", 0.03)
        with span("interpret"):
            gaps: list[str] = []
            if not brief.requirements:
                gaps.append("no accommodation schedule was provided")
            if not brief.site.boundary:
                gaps.append("no plot boundary was provided")
            if not brief.budget.is_specified:
                gaps.append("no budget was stated")
            ctx.shared["brief_gaps"] = gaps
        emit(
            "interpret", "done",
            f"Brief interpreted: {brief.total_rooms} rooms, "
            f"{brief.target_built_area:.0f} m2 target."
            + (f" Noted gaps: {'; '.join(gaps)}." if gaps else ""),
            0.08, gaps=gaps,
        )

    async def _stage_retrieve(self, brief: ClientBrief, ctx: AgentContext, emit) -> None:
        emit("retrieve", "running", "Retrieving precedent and style guidance...", 0.10)
        try:
            from aip.rag.retriever import retrieve_for_brief

            evidence = await retrieve_for_brief(brief)
            ctx.retrieved = evidence
            emit(
                "retrieve", "done",
                f"Retrieved {len(evidence)} reference passage(s) from the corpus.",
                0.16, count=len(evidence),
            )
        except Exception as exc:  # noqa: BLE001 - retrieval is an enhancement
            log_event(logger, "retrieve.unavailable", level=30, error=str(exc))
            emit("retrieve", "skipped", "Reference corpus unavailable; continuing without it.", 0.16)

    async def _stage_generate(
        self, brief: ClientBrief, ctx: AgentContext, emit
    ) -> list[FloorPlan]:
        emit("generate", "running", "Generating candidate schemes...", 0.18)
        with span("generate"):
            generator = LayoutGenerator(brief, self.config.generator)
            plans = await asyncio.to_thread(generator.generate, self.config.candidate_count)
        if not plans:
            raise RuntimeError("the layout generator produced no viable schemes")
        emit(
            "generate", "done",
            f"Generated {len(plans)} distinct scheme(s).",
            0.34,
            schemes=[
                {"id": p.id, "name": p.name, "area": p.total_built_area,
                 "fitness": p.metadata.get("fitness")}
                for p in plans
            ],
        )
        return plans

    async def _stage_critique(
        self, plans: list[FloorPlan], ctx: AgentContext, emit
    ) -> list[Candidate[FloorPlan]]:
        committee = build_committee(include_generative=self.config.include_generative_critics)
        emit(
            "critique", "running",
            f"{len(committee)} critics reviewing {len(plans)} scheme(s)...",
            0.36, critics=[c.id for c in committee],
        )

        candidates: list[Candidate[FloorPlan]] = []
        for index, plan in enumerate(plans):
            with span("critique", plan=plan.id):
                results = await run_agents(
                    committee, plan, ctx, max_parallel=self.config.max_parallel_agents
                )
            critiques = collect_critiques(results)
            candidates.append(
                Candidate(
                    id=plan.id,
                    artifact=plan,
                    origin=plan.name,
                    critiques=critiques,
                    metadata={"fitness": plan.metadata.get("fitness")},
                )
            )
            emit(
                "critique", "running",
                f"Reviewed {plan.name}: {len(critiques)} verdicts.",
                0.36 + 0.18 * (index + 1) / len(plans),
                plan=plan.id,
                scores={c.axis: round(c.score, 3) for c in critiques},
            )

        total = sum(len(c.critiques) for c in candidates)
        emit("critique", "done", f"{total} independent verdicts collected.", 0.56)
        return candidates

    async def _stage_consensus(
        self, candidates: list[Candidate[FloorPlan]], brief: ClientBrief, emit
    ) -> ConsensusResult:
        emit("consensus", "running", "Reconciling the committee's verdicts...", 0.58)
        priorities = _axis_priorities(brief)
        consensus = reach_consensus(candidates, priorities=priorities, ledger=self.ledger)
        emit(
            "consensus", "done",
            f"Selected {consensus.winner_id} with score {consensus.winner_score:.2f} "
            f"and {consensus.overall_agreement:.0%} committee agreement.",
            0.62,
            winner=consensus.winner_id,
            pareto_front=len(consensus.pareto_front),
            disqualified=len(consensus.disqualified),
            contested=consensus.contested_axes,
        )
        return consensus

    async def _stage_debate(
        self,
        candidates: list[Candidate[FloorPlan]],
        ctx: AgentContext,
        consensus: ConsensusResult,
        emit,
    ) -> ConsensusResult:
        """Re-poll the generative critics after showing them the disagreement.

        Only generative critics debate. An analytical critic has nothing to
        reconsider - its verdict is a measurement, and a measurement does not
        change because another agent disagrees with it.
        """
        emit(
            "debate", "running",
            f"Committee is split on {', '.join(consensus.contested_axes)}; opening a debate round.",
            0.64, contested=consensus.contested_axes,
        )

        winner = next((c for c in candidates if c.id == consensus.winner_id), candidates[0])
        contested = set(consensus.contested_axes)
        revisable = [c for c in winner.critiques if not c.analytical and c.axis in contested]

        if not revisable or not ctx.allow_generative:
            emit("debate", "skipped", "No revisable positions; disagreement stands as reported.", 0.68)
            return consensus

        transcript = "\n\n".join(
            f"[{c.critic_id} on {c.axis}] score {c.score:.2f}\n{c.rationale}"
            for c in winner.critiques
        )

        revised = 0
        for critique in revisable:
            try:
                new_score = await self._reconsider(critique, transcript, ctx)
            except Exception as exc:  # noqa: BLE001
                log_event(logger, "debate.failed", level=30, critic=critique.critic_id, error=str(exc))
                continue
            if new_score is not None and abs(new_score - critique.score) > 0.02:
                critique.rationale += (
                    f" [Revised from {critique.score:.2f} to {new_score:.2f} after "
                    f"reviewing the other critics' evidence.]"
                )
                critique.score = new_score
                revised += 1

        updated = reach_consensus(
            candidates,
            priorities=_axis_priorities(ctx.brief),
            ledger=self.ledger,
            debate_rounds=consensus.debate_rounds + 1,
        )
        emit(
            "debate", "done",
            f"{revised} position(s) revised; agreement moved from "
            f"{consensus.overall_agreement:.0%} to {updated.overall_agreement:.0%}.",
            0.70, revised=revised,
        )
        return updated

    async def _reconsider(
        self, critique: Critique, transcript: str, ctx: AgentContext
    ) -> float | None:
        class _Revision(BaseModel):
            revised_score: float = Field(ge=0.0, le=1.0)
            changed_mind: bool
            reason: str

        revision, _response = await ctx.llm().complete_model(
            [
                system(
                    "You previously reviewed an architectural scheme. Other "
                    "independent reviewers, including ones that measured the "
                    "building's physics and code compliance exactly, reached "
                    "different conclusions. Reconsider your score honestly. "
                    "Hold your position if their evidence does not bear on your "
                    "axis - independent judgement is the point of a committee, "
                    "and capitulating to the majority destroys its value. Change "
                    "only if they surfaced something you genuinely missed."
                ),
                user(
                    f"YOUR AXIS: {critique.axis}\n"
                    f"YOUR SCORE: {critique.score:.2f}\n"
                    f"YOUR REASONING: {critique.rationale}\n\n"
                    f"FULL COMMITTEE TRANSCRIPT:\n{transcript}\n\n"
                    "Give your revised score."
                ),
            ],
            _Revision,
            capability=Capability.REASONING,
            temperature=0.25,
            max_tokens=400,
        )
        return revision.revised_score if revision.changed_mind else None

    async def _stage_refine(
        self, winner: Candidate[FloorPlan], ctx: AgentContext, emit
    ) -> tuple[FloorPlan | None, float]:
        """Apply the critics' concrete remedies and keep the result only if better."""
        findings = [
            f for f in winner.all_findings()
            if f.severity in {Severity.CRITICAL, Severity.MAJOR} and f.target_id
        ]
        if not findings:
            emit("refine", "skipped", "No major findings to repair.", 0.82)
            return None, 0.0

        emit(
            "refine", "running",
            f"Repairing {len(findings)} finding(s) on the selected scheme...",
            0.74, findings=[f.code for f in findings[:8]],
        )

        from aip.engines.architecture.repair import repair_plan

        before = _analytical_score(winner.artifact, ctx.brief)
        repaired, applied = await asyncio.to_thread(
            repair_plan, winner.artifact, findings, ctx.brief
        )
        after = _analytical_score(repaired, ctx.brief)
        delta = after - before

        if delta <= 0.001 or not applied:
            emit(
                "refine", "done",
                "Repairs did not improve the scheme; the original was kept.",
                0.82, applied=0, delta=round(delta, 4),
            )
            return None, 0.0

        emit(
            "refine", "done",
            f"Applied {len(applied)} repair(s); analytical score improved by {delta:+.3f}.",
            0.82, applied=len(applied), delta=round(delta, 4), repairs=applied[:8],
        )
        return repaired, delta

    async def _stage_explain(self, result: DesignResult, ctx: AgentContext, emit) -> None:
        emit("explain", "running", "Writing the design rationale...", 0.86)

        consensus = result.consensus
        base = consensus.explanation if consensus else ""
        recommendations = _gather_recommendations(result)

        if not ctx.allow_generative:
            result.explanation = base
            result.recommendations = recommendations
            emit("explain", "done", "Rationale assembled from committee findings.", 1.0)
            return

        try:
            response = await ctx.llm().complete(
                [
                    system(
                        "You write the design rationale an architect sends to a "
                        "client. Plain language, no jargon, no marketing. Explain "
                        "what was chosen and why, name the trade-offs honestly "
                        "including where the scheme is weak, and never claim a "
                        "certainty the analysis does not support. Four short "
                        "paragraphs at most. Write in continuous prose without "
                        "headings or bullet points."
                    ),
                    user(
                        f"BRIEF\n{result.brief_summary}\n\n"
                        f"COMMITTEE DECISION\n{base}\n\n"
                        f"KEY RECOMMENDATIONS\n" + "\n".join(f"- {r}" for r in recommendations[:8])
                        + (f"\n\nVASTU\n{result.vastu.get('summary', '')}" if result.vastu else "")
                        + (f"\n\nCOST\n{result.cost.get('summary', '')}" if result.cost else "")
                    ),
                ],
                capability=Capability.REASONING,
                temperature=0.55,
                max_tokens=900,
            )
            result.explanation = (
                response.text if not response.degraded else base
            )
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "explain.failed", level=30, error=str(exc))
            result.explanation = base

        result.recommendations = recommendations
        emit("explain", "done", "Design rationale complete.", 1.0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _axis_priorities(brief: ClientBrief) -> dict[str, float]:
    """Map the client's stated priorities onto critic axes.

    Axes the client never mentioned still receive a floor weight inside
    `reach_consensus`, so code compliance and structural sanity are never
    zeroed out by a client who only cares about daylight.
    """
    weights = brief.priority_weights()
    return {
        "daylight": weights.get("daylight", 0.16),
        "ventilation": weights.get("ventilation", 0.16),
        "privacy": weights.get("privacy", 0.16),
        "circulation": weights.get("circulation", 0.16),
        "cost": weights.get("cost", 0.16),
        "vastu": weights.get("vastu", 0.1),
        "compliance": 0.22,
        "accessibility": 0.10,
        "spatial": 0.12,
        "structure": 0.10,
        "coherence": 0.10,
        "brief_fidelity": 0.14,
        "livability": 0.12,
    }


def _analytical_score(plan: FloorPlan, brief: ClientBrief) -> float:
    """Deterministic quality score used to accept or reject a refinement.

    Uses only analytical metrics, so the accept/reject decision is reproducible
    and free - a model-based comparison would be neither.
    """
    from aip.engines.architecture.codes import compliance_analysis
    from aip.engines.architecture.metrics import analyse_all

    reports = analyse_all(plan, brief)
    compliance = compliance_analysis(plan, brief)
    scores = [r.score for r in reports.values()] + [compliance.score * 2]
    return sum(scores) / (len(reports) + 2)


def _gather_recommendations(result: DesignResult) -> list[str]:
    """Deduplicated, priority-ordered actions from across the committee."""
    seen: set[str] = set()
    ranked: list[tuple[float, str]] = []

    for critiques in result.critiques.values():
        for critique in critiques:
            for finding in critique.findings:
                if not finding.remedy:
                    continue
                key = finding.remedy.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                ranked.append((finding.severity.weight, finding.remedy.strip()))
            for suggestion in critique.suggestions:
                key = suggestion.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    ranked.append((0.2, suggestion.strip()))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [text for _weight, text in ranked[:12]]


async def design(
    brief: ClientBrief,
    *,
    config: PipelineConfig | None = None,
    on_progress: ProgressCallback = None,
) -> DesignResult:
    """One-call entry point used by the API and the CLI."""
    return await DesignPipeline(config).run(brief, on_progress=on_progress)
