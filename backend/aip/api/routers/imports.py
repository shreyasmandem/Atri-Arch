"""Upload an existing floor plan and put it through the same committee.

An architect's own drawing, a client's brochure plan, a scan of a sanctioned
set: any of them becomes a `FloorPlan` and from there gets everything the
platform gives its own schemes - thirteen critics, the Vastu graph, the cost
takeoff, the airflow solve, the negotiation, the drawings, the CAD export.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from aip.agents.orchestrator import DesignPipeline, PipelineConfig
from aip.api.routers.design import _drawing_urls, _export_urls, _load_ledger
from aip.api.security import Principal, check_design_quota, get_principal
from aip.api.store import get_plan_store
from aip.core.logging import get_logger, log_event
from aip.db.models import Project
from aip.db.session import get_session
from aip.domain.brief import Budget, ClientBrief, RoomRequirement, VastuStance
from aip.domain.geometry import Direction
from aip.domain.plan import FloorPlan, RoomType
from aip.engines.architecture.importer import ImportError_, import_floorplan

logger = get_logger("aip.api.imports")
router = APIRouter(prefix="/plans", tags=["plans"])

#: Uploads are read whole; a plan scan is a few megabytes at most, and a
#: bound stops one request holding memory for everyone else.
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


def _brief_for(plan: FloorPlan, *, vastu: VastuStance, budget: float, name: str) -> ClientBrief:
    """Describe the uploaded plan as a brief, so the critics have a programme.

    The rooms are what was drawn; the areas are what they measure. That is
    the honest brief for an existing plan - it asks the committee to judge
    the building as it is, not against some other building it might have been.
    """
    counts: dict[RoomType, list[float]] = {}
    for room in plan.all_rooms:
        counts.setdefault(room.type, []).append(room.area)
    requirements = [
        RoomRequirement(
            type=kind, count=len(areas),
            preferred_area=round(sum(areas) / len(areas), 2),
            needs_daylight=kind.is_habitable,
            attached_bathroom=(kind is RoomType.MASTER_BEDROOM),
        )
        for kind, areas in counts.items()
        if kind is not RoomType.OTHER
    ]
    return ClientBrief(
        project_name=name, site=plan.site, levels=max(1, len(plan.levels)),
        requirements=requirements, vastu=vastu,
        budget=Budget(amount=budget) if budget else Budget(),
    )


@router.post("/import", status_code=201)
async def import_plan(
    request: Request,
    file: UploadFile = File(...),
    plot_width: float | None = Form(default=None),
    plot_depth: float | None = Form(default=None),
    road_direction: str = Form(default="N"),
    north_angle: float = Form(default=0.0),
    name: str = Form(default=""),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    """Read a DXF, SVG, image or plan JSON into a plan the platform can analyse.

    The response says exactly what was read, what was assumed about scale,
    which labels could not be classified, and whether doors and windows had
    to be added. Nothing about an upload is silent.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds 12 MB.")

    try:
        road = Direction(road_direction.upper())
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown road direction {road_direction!r}."
        ) from exc

    try:
        result = await import_floorplan(
            data, file.filename or "upload",
            plot_width=plot_width, plot_depth=plot_depth,
            road=road, north_angle=north_angle,
            name=name or (file.filename or "Imported plan").rsplit(".", 1)[0],
            mime=file.content_type or "",
        )
    except ImportError_ as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log_event(logger, "import.failed", level=40, filename=file.filename, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail=(
                "The plan could not be read. For an image this usually means no free "
                "vision model was reachable just now; try again shortly, or upload the "
                "DXF or SVG instead, which needs no model at all."
            ),
        ) from exc

    plan = result.plan
    get_plan_store().put(principal.firm.id, plan)

    from aip.core.config import get_settings

    prefix = request.scope.get("root_path", "") + get_settings().api_prefix
    log_event(logger, "import.ok", source=result.source, rooms=result.rooms_kept,
              unrecognised=len(result.unrecognised))
    return {
        "plan_id": plan.id,
        "plan": json.loads(plan.model_dump_json()),
        "import": result.to_dict(),
        "rooms": [
            {"id": r.id, "name": r.name, "type": r.type.value, "area": round(r.area, 2),
             "confidence": r.metadata.get("confidence", 1.0)}
            for r in plan.all_rooms
        ],
        "drawing_urls": _drawing_urls(prefix, plan),
        "export_urls": _export_urls(prefix, plan),
        "model_url": f"{prefix}/plans/{plan.id}/model.glb",
    }


@router.post("/{plan_id}/review/stream")
async def review_stream(
    plan_id: str,
    request: Request,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    vastu: str = "balanced",
    budget: float = 0.0,
    include_generative_critics: bool = True,
) -> StreamingResponse:
    """Run the committee, negotiation and rationale on an uploaded plan.

    The same events the design stream emits, so the studio shows the same
    critics sitting on the same bench - only the generate stage reports that
    it reviewed what was uploaded instead of drawing something new.
    """
    check_design_quota(principal.firm)
    plan = get_plan_store().get(plan_id, principal.firm.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found or expired.")

    try:
        stance = VastuStance(vastu)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown Vastu stance {vastu!r}.") from exc

    brief = _brief_for(plan, vastu=stance, budget=budget, name=plan.name)
    project = Project(
        firm_id=principal.firm.id, name=plan.name, source="upload",
        brief=json.loads(brief.model_dump_json()),
    )
    session.add(project)
    await session.flush()
    ledger = await _load_ledger(session, principal.firm.id)
    await session.commit()

    firm_id = principal.firm.id
    project_id = project.id
    pipeline = DesignPipeline(
        PipelineConfig(candidate_count=1, include_generative_critics=include_generative_critics),
        ledger=ledger,
    )
    from aip.core.config import get_settings

    prefix = request.scope.get("root_path", "") + get_settings().api_prefix

    async def events():
        def sse(event: str, data: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

        yield sse("open", {"project_id": project_id, "plan_id": plan.id})
        try:
            async for progress, result in pipeline.stream(brief, plans=[plan]):
                if progress is not None:
                    yield sse("progress", json.loads(progress.model_dump_json()))
                elif result is not None:
                    store = get_plan_store()
                    store.put_many(firm_id, result.plans)
                    if result.winner:
                        store.put(firm_id, result.winner)
                    winner = result.winner
                    yield sse("result", {
                        "project_id": project_id,
                        "trace_id": result.trace_id,
                        "winner_plan_id": winner.id if winner else "",
                        "selected_candidate_id": result.consensus.winner_id if result.consensus else "",
                        "plan_ids": [p.id for p in result.plans],
                        "plan": json.loads(winner.model_dump_json()) if winner else {},
                        "consensus": json.loads(result.consensus.model_dump_json())
                        if result.consensus else {},
                        "vastu": result.vastu,
                        "cost": result.cost,
                        "explanation": result.explanation,
                        "recommendations": result.recommendations,
                        "committee": result.committee,
                        "evidence": [json.loads(e.model_dump_json()) for e in result.evidence[:20]],
                        "negotiation": result.negotiation,
                        "negotiation_outcome": result.negotiation_outcome,
                        "drawing_urls": _drawing_urls(prefix, winner) if winner else {},
                        "export_urls": _export_urls(prefix, winner) if winner else {},
                        "model_url": f"{prefix}/plans/{winner.id}/model.glb" if winner else "",
                        "duration_ms": round(result.duration_ms, 1),
                        "model_cost_usd": result.total_cost_usd,
                        "degraded": result.degraded,
                        "degraded_reason": result.degraded_reason,
                        "imported": True,
                    })
        except Exception as exc:  # noqa: BLE001
            log_event(logger, "review.stream_failed", level=40, error=str(exc))
            yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        yield sse("done", {})

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )
