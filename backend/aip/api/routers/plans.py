"""Plan retrieval: drawings, 3D model, walkthrough data and analysis re-runs."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from aip.api.schemas import CostRequest, VastuRequest
from aip.api.security import Principal, get_principal
from aip.api.store import get_plan_store
from aip.core.logging import get_logger
from aip.db.session import get_session
from aip.domain.geometry import Direction
from aip.domain.plan import FloorPlan
from aip.engines.architecture.airflow import airflow_svg
from aip.engines.architecture.codes import compliance_analysis
from aip.engines.architecture.drawings import (
    DrawingStyle,
    elevation_svg,
    floor_plan_svg,
    roof_plan_svg,
    section_svg,
    site_plan_svg,
)
from aip.engines.architecture.dxf import export_dxf
from aip.engines.architecture.metrics import analyse_all
from aip.engines.cost.estimator import estimate_cost
from aip.engines.cost.rates import FinishTier, default_schedule
from aip.engines.experience.model3d import (
    camera_waypoints,
    export_glb,
    export_obj,
    model_statistics,
)
from aip.engines.vastu.engine import analyse_vastu

logger = get_logger("aip.api.plans")
router = APIRouter(prefix="/plans", tags=["plans"])

SVG_CACHE = "public, max-age=3600"


def _load(plan_id: str, principal: Principal) -> FloorPlan:
    plan = get_plan_store().get(plan_id, principal.firm.id)
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Plan not found or expired. Generated schemes are cached for a "
                "limited time; re-run the design or use the saved project plan."
            ),
        )
    return plan


def _plan_from_payload(payload: dict[str, Any] | None, plan_id: str | None, principal: Principal) -> FloorPlan:
    if plan_id:
        return _load(plan_id, principal)
    if payload:
        try:
            return FloorPlan.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"Invalid plan payload: {exc}") from exc
    raise HTTPException(status_code=422, detail="Provide either 'plan_id' or 'plan'.")


@router.get("/{plan_id}")
async def get_plan(plan_id: str, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    return json.loads(_load(plan_id, principal).model_dump_json())


@router.get("/{plan_id}/drawings/{name}.svg", response_class=Response)
async def get_drawing(
    plan_id: str,
    name: str,
    principal: Principal = Depends(get_principal),
    dimensions: bool = Query(default=True),
    grid: bool = Query(default=False),
    furniture: bool = Query(default=True),
    dark: bool = Query(default=False),
) -> Response:
    """Render one drawing as SVG.

    `name` is one of `plan_level_<n>`, `elevation_<N|E|S|W>`, `section_aa`,
    `section_bb`, `roof_plan`, `site_plan`.
    """
    plan = _load(plan_id, principal)
    style = DrawingStyle()
    if dark:
        # Inverted palette for embedding in dark-themed practice websites.
        style.background = "#12161b"
        style.wall_fill = "#e6e9ec"
        style.wall_stroke = "#ffffff"
        style.room_fill = "#1c2229"
        style.room_fill_wet = "#182430"
        style.room_fill_outdoor = "#1a2620"
        style.room_fill_circulation = "#20262d"
        style.text = "#e6e9ec"
        style.text_muted = "#8f9aa6"
        style.grid = "#2a323b"

    try:
        if name.startswith("plan_level_"):
            level_index = int(name.rsplit("_", 1)[1])
            svg = floor_plan_svg(
                plan, level_index, style=style,
                show_dimensions=dimensions, show_grid=grid, show_furniture=furniture,
            )
        elif name.startswith("elevation_"):
            direction = Direction(name.rsplit("_", 1)[1].upper())
            svg = elevation_svg(plan, direction, style=style)
        elif name in {"section_aa", "section_bb"}:
            svg = section_svg(plan, axis="x" if name.endswith("aa") else "y", style=style)
        elif name == "roof_plan":
            svg = roof_plan_svg(plan, style=style)
        elif name == "site_plan":
            svg = site_plan_svg(plan, style=style)
        elif name.startswith("airflow_level_"):
            level_index = int(name.rsplit("_", 1)[1])
            svg = airflow_svg(plan, level_index, style=style)
        else:
            raise HTTPException(status_code=404, detail=f"Unknown drawing '{name}'.")
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail=f"Malformed drawing name '{name}'.") from exc

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": SVG_CACHE, "Content-Disposition": f'inline; filename="{name}.svg"'},
    )


@router.get("/{plan_id}/model.glb", response_class=Response)
async def get_model_glb(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    furniture: bool = Query(default=True),
    ground: bool = Query(default=True),
) -> Response:
    """Binary glTF for the 3D viewer, VR walkthrough and AR placement."""
    plan = _load(plan_id, principal)
    data = export_glb(plan, include_furniture=furniture, include_ground=ground)
    return Response(
        content=data,
        media_type="model/gltf-binary",
        headers={
            "Cache-Control": SVG_CACHE,
            "Content-Disposition": f'inline; filename="{plan_id}.glb"',
        },
    )


@router.get("/{plan_id}/level-{level_index}.dxf", response_class=Response)
async def get_level_dxf(
    plan_id: str,
    level_index: int,
    principal: Principal = Depends(get_principal),
) -> Response:
    """AutoCAD R12 DXF for one level.

    This is the export that makes the generated layout the practice's own: the
    walls, openings, grid and room schedule arrive as editable CAD entities on
    conventional layers, not as an image to trace over.
    """
    plan = _load(plan_id, principal)
    if plan.level_at(level_index) is None:
        raise HTTPException(status_code=404, detail=f"Plan has no level {level_index}.")
    return Response(
        content=export_dxf(plan, level_index),
        media_type="image/vnd.dxf",
        headers={
            "Cache-Control": SVG_CACHE,
            "Content-Disposition": f'attachment; filename="{plan_id}_level_{level_index}.dxf"',
        },
    )


@router.get("/{plan_id}/model.obj", response_class=Response)
async def get_model_obj(plan_id: str, principal: Principal = Depends(get_principal)) -> Response:
    """Wavefront OBJ, for import into the CAD tools a practice already owns."""
    plan = _load(plan_id, principal)
    return Response(
        content=export_obj(plan),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{plan_id}.obj"'},
    )


@router.get("/{plan_id}/walkthrough")
async def get_walkthrough(
    plan_id: str, principal: Principal = Depends(get_principal)
) -> dict[str, Any]:
    """Everything the WebXR viewer needs: waypoints, model stats and narration."""
    plan = _load(plan_id, principal)
    waypoints = camera_waypoints(plan)
    return {
        "plan_id": plan.id,
        "model_url": f"/api/v1/plans/{plan.id}/model.glb",
        "waypoints": waypoints,
        "statistics": model_statistics(plan),
        "narration": _narration(plan, waypoints),
        "ar": {
            "supported_formats": ["glb"],
            "placement": "floor",
            "scale_metres": 1.0,
            "note": (
                "GLB is placed directly by WebXR and Android Scene Viewer. "
                "iOS Quick Look additionally requires a USDZ conversion, which "
                "needs Apple's tooling and is not performed server-side."
            ),
        },
    }


def _narration(plan: FloorPlan, waypoints: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Per-room narration script for the voice assistant.

    Spoken client-side by the Web Speech API, so it costs nothing and needs no
    text-to-speech service.
    """
    lines: list[dict[str, str]] = [
        {
            "room_id": "",
            "text": (
                f"This is {plan.name}, a {plan.total_built_area:.0f} square metre "
                f"home across {len(plan.levels)} "
                f"{'level' if len(plan.levels) == 1 else 'levels'}. "
                f"Let me walk you through it."
            ),
        }
    ]
    for waypoint in waypoints:
        room = plan.room_by_id(str(waypoint["room_id"]))
        if room is None:
            continue
        direction = plan.direction_of_room(room)
        lines.append(
            {
                "room_id": room.id,
                "text": (
                    f"The {room.display_name().lower()} is {room.area:.0f} square "
                    f"metres and faces {direction.value}. "
                    + (
                        "It has windows on more than one side, so it will feel airy."
                        if len({o.id for w in plan.all_walls if room.id in w.rooms for o in w.openings if o.kind.is_glazed}) > 1
                        else "It takes daylight from one side."
                    )
                ),
            }
        )
    return lines


@router.get("/{plan_id}/analysis")
async def get_analysis(
    plan_id: str, principal: Principal = Depends(get_principal)
) -> dict[str, Any]:
    """Re-run the analytical metric suite for a plan."""
    plan = _load(plan_id, principal)
    reports = analyse_all(plan)
    compliance = compliance_analysis(plan)
    return {
        "plan_id": plan.id,
        "metrics": {
            axis: {
                "score": report.score,
                "summary": report.summary,
                "per_room": report.per_room,
                "detail": report.detail,
                "findings": [json.loads(f.model_dump_json()) for f in report.findings],
            }
            for axis, report in reports.items()
        },
        "compliance": {
            "score": compliance.score,
            "summary": compliance.summary,
            "detail": compliance.detail,
            "findings": [json.loads(f.model_dump_json()) for f in compliance.findings],
        },
    }


@router.post("/{plan_id}/interior")
async def run_interior(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    style: str | None = Query(default=None),
) -> dict[str, Any]:
    """Solve the furniture layout, palette, lighting and finishes for a plan."""
    from aip.domain.brief import ClientBrief, DesignStyle, StylePreference
    from aip.engines.interior.engine import design_interior

    plan = _load(plan_id, principal)
    brief = ClientBrief()
    chosen = style or plan.style
    try:
        brief.style = StylePreference(styles=[DesignStyle(chosen)])
    except ValueError:
        brief.style = StylePreference()

    scheme = design_interior(plan, brief)
    return json.loads(scheme.model_dump_json())


@router.post("/vastu")
async def run_vastu(
    payload: VastuRequest,
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    """Explainable Vastu assessment at any tradition/modern stance.

    Re-running at a different `tradition_weight` is cheap and instantaneous, so
    a client can move the slider and watch which rules gain or lose influence.
    """
    plan = _plan_from_payload(payload.plan, payload.plan_id, principal)
    report = analyse_vastu(plan, payload.tradition_weight)
    return json.loads(report.model_dump_json())


@router.post("/cost")
async def run_cost(
    payload: CostRequest,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Price a plan, optionally at a different region or specification level."""
    plan = _plan_from_payload(payload.plan, payload.plan_id, principal)

    from aip.domain.brief import Budget, ClientBrief

    brief = ClientBrief(budget=Budget(amount=payload.budget, currency=payload.currency))
    if payload.finish_tier:
        brief.metadata["finish_tier"] = payload.finish_tier
    region = payload.region or principal.firm.region

    schedule = default_schedule(
        region=region,
        finish_tier=FinishTier(payload.finish_tier) if payload.finish_tier else FinishTier.STANDARD,
    )
    # A firm's own tendered rates always beat the indicative schedule.
    if principal.firm.rate_overrides:
        for code, value in principal.firm.rate_overrides.items():
            existing = schedule.rates.get(code)
            if existing is not None:
                from dataclasses import replace

                schedule.rates[code] = replace(existing, rate=float(value))

    calibration = float(principal.firm.settings.get("cost_calibration", 1.0))
    estimate = estimate_cost(plan, brief, schedule=schedule, calibration_factor=calibration)
    return json.loads(estimate.model_dump_json())
