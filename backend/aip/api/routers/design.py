"""Design generation endpoints."""

from __future__ import annotations

import asyncio

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from aip.agents.consensus import CalibrationLedger
from aip.agents.orchestrator import DesignPipeline, PipelineConfig
from aip.api.schemas import DesignRequest, DesignResponse
from aip.api.security import Principal, check_design_quota, get_principal
from aip.api.store import get_plan_store
from aip.core.logging import get_logger, log_event
from aip.db.models import DesignSession, Project
from aip.db.session import get_session
from aip.engines.architecture.layout import GeneratorConfig, InfeasibleBriefError

logger = get_logger("aip.api.design")
router = APIRouter(prefix="/design", tags=["design"])

# Drawing a scheme is CPU work. A small free instance that is asked for several
# at once slows every one of them and can run out of memory, so runs take turns:
# the ones waiting are told how many are ahead of them.
_GATE: asyncio.Semaphore | None = None
_WAITING = 0


def _name_schemes(result) -> None:
    """Scheme A, B, C in the order the studio lists them, and the winner under the
    letter of the candidate it came from - so the tab, the rail and the drawing
    title all say the same thing."""
    letters = {p.id: chr(65 + i) for i, p in enumerate(result.plans)}
    for p in result.plans:
        p.name = f"Scheme {letters[p.id]}"
    winner = result.winner
    if winner is not None and winner.id not in letters:
        origin = result.consensus.winner_id if result.consensus else ""
        if origin in letters:
            winner.name = f"Scheme {letters[origin]}"


def _design_gate() -> asyncio.Semaphore:
    global _GATE
    if _GATE is None:
        import os

        from aip.core.config import get_settings

        default = "1" if get_settings().public_demo else "3"
        _GATE = asyncio.Semaphore(max(1, int(os.environ.get("MAX_CONCURRENT_DESIGNS", default))))
    return _GATE


def _pipeline_config(request: DesignRequest) -> PipelineConfig:
    return PipelineConfig(
        candidate_count=request.candidates,
        include_generative_critics=request.include_generative_critics,
        enable_refinement=request.enable_refinement,
        generator=GeneratorConfig(seed=request.seed),
    )


async def _load_ledger(session: AsyncSession, firm_id: str) -> CalibrationLedger:
    """Restore this firm's learned critic reliabilities."""
    from sqlalchemy import select

    from aip.db.models import CriticCalibrationRow

    rows = (
        await session.execute(
            select(CriticCalibrationRow).where(CriticCalibrationRow.firm_id == firm_id)
        )
    ).scalars().all()
    ledger = CalibrationLedger()
    ledger.load(
        {
            row.critic_id: {
                "reliability": row.reliability,
                "observations": row.observations,
                "mean_brier": row.mean_brier,
            }
            for row in rows
        }
    )
    return ledger


async def _ensure_project(
    session: AsyncSession, principal: Principal, request: DesignRequest, brief
) -> Project:
    if request.project_id:
        project = await session.get(Project, request.project_id)
        if project is None or project.firm_id != principal.firm.id:
            raise HTTPException(status_code=404, detail="Project not found.")
        return project

    project = Project(
        firm_id=principal.firm.id,
        name=brief.project_name,
        client_name=request.client_name,
        client_email=request.client_email,
        source="widget" if principal.scope == "public" else "studio",
        brief=json.loads(brief.model_dump_json()),
    )
    session.add(project)
    await session.flush()
    return project


def _drawing_urls(prefix: str, plan) -> dict[str, str]:
    urls = {
        f"plan_level_{level.index}": f"{prefix}/plans/{plan.id}/drawings/plan_level_{level.index}.svg"
        for level in plan.levels
    }
    for name in ("elevation_N", "elevation_E", "elevation_S", "elevation_W",
                 "section_aa", "section_bb", "roof_plan", "site_plan"):
        urls[name] = f"{prefix}/plans/{plan.id}/drawings/{name}.svg"
    # Animated airflow, one per level: the ventilation analysis drawn rather
    # than tabulated, because a stagnant corner argues for itself.
    for level in plan.levels:
        urls[f"airflow_level_{level.index}"] = (
            f"{prefix}/plans/{plan.id}/drawings/airflow_level_{level.index}.svg"
        )
    return urls


def _export_urls(prefix: str, plan) -> dict[str, str]:
    """Editable formats, kept apart from the rendered drawings.

    `drawing_urls` is a contract for SVG the client can display inline. CAD and
    mesh exports are downloads with different media types, so mixing them into
    the same map would break any consumer that assumes it can render what it
    finds there.
    """
    urls = {
        f"dxf_level_{level.index}": f"{prefix}/plans/{plan.id}/level-{level.index}.dxf"
        for level in plan.levels
    }
    urls["model_glb"] = f"{prefix}/plans/{plan.id}/model.glb"
    urls["model_obj"] = f"{prefix}/plans/{plan.id}/model.obj"
    return urls


@router.post("", response_model=DesignResponse, status_code=status.HTTP_201_CREATED)
async def create_design(
    payload: DesignRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DesignResponse:
    """Run the full multi-agent design pipeline and return the selected scheme."""
    check_design_quota(principal.firm)

    try:
        brief = payload.resolved_brief()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    project = await _ensure_project(session, principal, payload, brief)
    ledger = await _load_ledger(session, principal.firm.id)

    pipeline = DesignPipeline(_pipeline_config(payload), ledger=ledger)
    try:
        result = await pipeline.run(brief)
    except InfeasibleBriefError as exc:
        # The plot cannot hold the programme. That is the client's answer, not a
        # server fault: 422 with the numbers and what to change.
        log_event(logger, "design.infeasible", level=30, error=str(exc))
        session.add(
            DesignSession(
                project_id=project.id, status="infeasible",
                brief=json.loads(brief.model_dump_json()), error=str(exc)[:2000],
            )
        )
        await session.flush()
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except Exception as exc:  # noqa: BLE001
        log_event(logger, "design.failed", level=40, error=f"{type(exc).__name__}: {exc}")
        session.add(
            DesignSession(
                project_id=project.id, status="failed",
                brief=json.loads(brief.model_dump_json()), error=str(exc)[:2000],
            )
        )
        raise HTTPException(
            status_code=500, detail=f"Design generation failed: {type(exc).__name__}"
        ) from exc

    store = get_plan_store()
    _name_schemes(result)
    store.put_many(principal.firm.id, result.plans)
    if result.winner is not None:
        store.put(principal.firm.id, result.winner)

    winner_dump = json.loads(result.winner.model_dump_json()) if result.winner else {}
    consensus_dump = json.loads(result.consensus.model_dump_json()) if result.consensus else {}

    design_session = DesignSession(
        project_id=project.id,
        trace_id=result.trace_id,
        status="completed",
        brief=json.loads(brief.model_dump_json()),
        result={
            "explanation": result.explanation,
            "recommendations": result.recommendations,
            "plan_ids": [p.id for p in result.plans],
            "winner_plan_id": result.winner.id if result.winner else "",
            "refinement_applied": result.refinement_applied,
        },
        critiques={
            plan_id: [json.loads(c.model_dump_json()) for c in critiques]
            for plan_id, critiques in result.critiques.items()
        },
        consensus=consensus_dump,
        duration_ms=result.duration_ms,
        model_cost_usd=result.total_cost_usd,
        degraded=result.degraded,
    )
    session.add(design_session)

    project.selected_plan = winner_dump
    project.vastu_report = result.vastu or {}
    project.cost_estimate = result.cost or {}
    project.status = "designed"
    principal.firm.designs_this_month += 1
    await session.flush()

    from aip.core.config import get_settings

    prefix = request.scope.get("root_path", "") + get_settings().api_prefix

    return DesignResponse(
        session_id=design_session.id,
        project_id=project.id,
        trace_id=result.trace_id,
        plan_ids=[p.id for p in result.plans],
        winner_plan_id=result.winner.id if result.winner else "",
        selected_candidate_id=result.consensus.winner_id if result.consensus else "",
        plan=winner_dump,
        consensus=consensus_dump,
        vastu=result.vastu,
        cost=result.cost,
        advisories=result.advisories,
        explanation=result.explanation,
        recommendations=result.recommendations,
        committee=result.committee,
        voices=result.voices,
        evidence=[json.loads(e.model_dump_json()) for e in result.evidence[:20]],
        negotiation=result.negotiation,
        negotiation_outcome=result.negotiation_outcome,
        duration_ms=round(result.duration_ms, 1),
        model_cost_usd=result.total_cost_usd,
        degraded=result.degraded,
        degraded_reason=result.degraded_reason,
        drawing_urls=_drawing_urls(prefix, result.winner) if result.winner else {},
        export_urls=_export_urls(prefix, result.winner) if result.winner else {},
        model_url=f"{prefix}/plans/{result.winner.id}/model.glb" if result.winner else "",
    )


@router.post("/stream")
async def stream_design(
    payload: DesignRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Server-sent events showing the committee working, then the final result.

    Design takes seconds, not milliseconds, and a client watching a spinner
    assumes the product is broken. Streaming each stage - which critics ran,
    what they found, whether a debate was needed - is also the clearest possible
    demonstration that a committee is genuinely at work rather than a single
    model call behind a progress bar.
    """
    check_design_quota(principal.firm)
    try:
        brief = payload.resolved_brief()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    project = await _ensure_project(session, principal, payload, brief)
    ledger = await _load_ledger(session, principal.firm.id)
    await session.commit()

    firm_id = principal.firm.id
    project_id = project.id
    pipeline = DesignPipeline(_pipeline_config(payload), ledger=ledger)

    from aip.core.config import get_settings

    prefix = request.scope.get("root_path", "") + get_settings().api_prefix

    async def events():
        def sse(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

        global _WAITING
        yield sse("open", {"project_id": project_id})
        gate = _design_gate()
        held = False
        try:
            if gate.locked():
                _WAITING += 1
                try:
                    while True:
                        try:
                            await asyncio.wait_for(gate.acquire(), 2.5)
                            held = True
                            break
                        except asyncio.TimeoutError:
                            yield sse("progress", {
                                "stage": "generate", "status": "running", "percent": 0.0,
                                "message": f"Other designs are being drawn first - you are {_WAITING} in the queue.",
                                "detail": {}, "elapsed_ms": 0.0,
                            })
                finally:
                    _WAITING = max(0, _WAITING - 1)
            else:
                await gate.acquire()
                held = True
            async for progress, result in pipeline.stream(brief):
                if progress is not None:
                    yield sse("progress", json.loads(progress.model_dump_json()))
                elif result is not None:
                    _name_schemes(result)
                    store = get_plan_store()
                    store.put_many(firm_id, result.plans)
                    if result.winner:
                        store.put(firm_id, result.winner)
                    yield sse(
                        "result",
                        {
                            "project_id": project_id,
                            "trace_id": result.trace_id,
                            "winner_plan_id": result.winner.id if result.winner else "",
                            "plan_ids": [p.id for p in result.plans],
                            "plan": json.loads(result.winner.model_dump_json()) if result.winner else {},
                            "consensus": json.loads(result.consensus.model_dump_json())
                            if result.consensus else {},
                            "vastu": result.vastu,
                            "cost": result.cost,
                            "advisories": result.advisories,
                            "explanation": result.explanation,
                            "recommendations": result.recommendations,
                            "committee": result.committee,
                            "voices": result.voices,
                            "evidence": [
                                json.loads(e.model_dump_json()) for e in result.evidence[:20]
                            ],
                            "negotiation": result.negotiation,
                            "negotiation_outcome": result.negotiation_outcome,
                            "drawing_urls": (
                                _drawing_urls(prefix, result.winner) if result.winner else {}
                            ),
                            "export_urls": (
                                _export_urls(prefix, result.winner) if result.winner else {}
                            ),
                            "selected_candidate_id": (
                                result.consensus.winner_id if result.consensus else ""
                            ),
                            "model_url": (
                                f"{prefix}/plans/{result.winner.id}/model.glb"
                                if result.winner else ""
                            ),
                            "duration_ms": round(result.duration_ms, 1),
                            "model_cost_usd": result.total_cost_usd,
                            "degraded": result.degraded,
                            "degraded_reason": result.degraded_reason,
                        },
                    )
        except InfeasibleBriefError as exc:
            # A clean, visible refusal: the message, the numbers and the code the
            # studio keys its "change the brief" panel on - not a stack trace.
            log_event(logger, "design.infeasible", level=30, error=str(exc))
            yield sse("error", {"message": str(exc), **exc.to_dict()})
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "design.stream_failed", level=40, error=str(exc))
            yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        finally:
            if held:
                gate.release()
        yield sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------- chat


@router.post("/chat")
async def design_chat(payload: dict[str, Any]) -> dict[str, Any]:
    """One turn of the brief conversation: what was understood, what to ask next.

    Body: {"message": str, "brief": {...so far}}. When `ready`, `request` is a
    `SimpleBriefRequest` the design endpoint accepts as is.
    """
    from aip.agents.brief_agent import converse, to_request

    message = str(payload.get("message", ""))[:4000]
    history = payload.get("history") or []
    turn = await converse(message, payload.get("brief") or {},
                          history=[h for h in history if isinstance(h, dict)][-12:])
    turn["request"] = to_request(turn["brief"]) if turn["ready"] else None
    return turn


@router.post("/revise")
async def design_revise(payload: dict[str, Any]) -> dict[str, Any]:
    """Change a finished design from a sentence: the new brief and what changed.

    Body: {"instruction": str, "brief": {...}}. The client re-runs the design
    with `request` to see the revision.
    """
    from aip.agents.brief_agent import revise, to_request

    out = await revise(str(payload.get("instruction", ""))[:2000], payload.get("brief") or {})
    out["request"] = to_request(out["brief"])
    return out
