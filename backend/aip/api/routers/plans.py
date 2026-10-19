"""Plan retrieval: drawings, 3D model, walkthrough data and analysis re-runs."""

from __future__ import annotations

import json
from typing import Any

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
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


class RestoreRequest(BaseModel):
    plan: dict[str, Any]


@router.post("/restore")
async def restore_plan(payload: RestoreRequest, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """Put a plan the client still holds back in the server's memory.

    Schemes live in memory on the instance that drew them; a restart (a deploy,
    a free instance waking from sleep) forgets them while a browser still shows
    them. The client keeps each plan's JSON and sends it back on a 404, so the
    drawing, the model and the analyses carry on instead of failing.
    """
    try:
        plan = FloorPlan.model_validate(payload.plan)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid plan: {exc}") from exc
    if not plan.id or not plan.levels:
        raise HTTPException(status_code=422, detail="That is not a plan.")
    get_plan_store().put(principal.firm.id, plan)
    return {"plan_id": plan.id}


class EditRequest(BaseModel):
    """Edits to a finished plan, applied in order. See `editor` for the kinds."""

    ops: list[dict[str, Any]] = Field(default_factory=list, max_length=16)


@router.get("/{plan_id}/rooms")
async def plan_rooms(plan_id: str, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """The rooms of a plan as the editor lists them."""
    from aip.engines.architecture.editor import describe_rooms

    plan = _load(plan_id, principal)
    return {"plan_id": plan.id, "rooms": describe_rooms(plan),
            "levels": [{"index": lv.index, "name": lv.display_name()} for lv in plan.levels]}


@router.post("/{plan_id}/edit")
async def edit_plan(
    plan_id: str, payload: EditRequest, principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    """Change a finished plan in place - widen a room, swap two, rename, set a ceiling.

    Returns a new plan id (the original is kept, so an edit can be undone) with
    what was done and what was refused and why.
    """
    from aip.engines.architecture.editor import apply_edits, describe_rooms

    plan = _load(plan_id, principal)
    if not payload.ops:
        raise HTTPException(status_code=422, detail="No edits were given.")
    new, applied, refused = await asyncio.to_thread(apply_edits, plan, payload.ops)
    if not applied:
        raise HTTPException(status_code=422, detail=" ".join(refused) or "Nothing could be changed.")
    get_plan_store().put(principal.firm.id, new)
    return {"plan_id": new.id, "from_plan_id": plan.id, "applied": applied, "refused": refused,
            "rooms": describe_rooms(new)}


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
        # Inverted palette for dark themes: the studio's warm black and
        # cream, with wet rooms and circulation told apart by value alone.
        style.background = "#141312"
        style.wall_fill = "#ede6dc"
        style.wall_stroke = "#f6f1ea"
        style.room_fill = "#1d1c1a"
        style.room_fill_wet = "#22221f"
        style.room_fill_outdoor = "#1a1a17"
        style.room_fill_circulation = "#181715"
        style.text = "#ede6dc"
        style.text_muted = "#9a948b"
        style.dimension = "#8a847b"
        style.glass = "#a9b8c2"
        style.accent = "#c4553f"
        style.grid = "#2a2724"
        style.font = "'Geist', 'Segoe UI', system-ui, sans-serif"

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


@router.get("/{plan_id}/airflow/{level_index}")
async def get_airflow_field(
    plan_id: str,
    level_index: int,
    principal: Principal = Depends(get_principal),
    wind: str | None = Query(default=None, description="Compass point the wind blows from, or a bearing in degrees"),
    speed: float = Query(default=2.0, gt=0, le=15),
    doors_open: bool = Query(default=True),
    rank: bool = Query(default=False, description="Also score the floor for each of the eight winds"),
) -> dict[str, Any]:
    """The solved wind field through one floor, for the live airflow view."""
    import asyncio

    from aip.engines.architecture.windflow import best_wind, solve_level

    plan = _load(plan_id, principal)
    w: Direction | float | None = None
    if wind:
        try:
            w = Direction(wind.upper())
        except ValueError:
            try:
                w = float(wind) % 360
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"Unknown wind '{wind}'.") from exc
    try:
        result = await asyncio.to_thread(solve_level, plan, level_index, wind=w, speed=speed, doors_open=doors_open)
        if rank:
            result["ranking"] = await asyncio.to_thread(best_wind, plan, level_index, speed=speed, doors_open=doors_open)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=f"No level {level_index}.") from exc
    return result


@router.get("/{plan_id}/vastu3d")
async def get_vastu_placements(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    tradition: float = Query(default=0.5, ge=0.0, le=1.0),
) -> dict[str, Any]:
    """The Vastu zones and every assessed room's placement, as geometry for the 3D view."""
    from aip.engines.vastu.placements import placements

    return placements(_load(plan_id, principal), tradition)


@router.get("/{plan_id}/exteriors")
async def get_exteriors(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    prefs: str = Query(default="", max_length=1200, description="What the client said about the look they want"),
    seed: str | None = Query(default=None, max_length=40, description="Any value: a fresh batch from the grammar"),
    n: int = Query(default=12, ge=1, le=40, description="Designs in a fresh batch"),
    avoid: list[str] = Query(default=[], max_length=80, description="Design ids already shown, never repeated"),
    style: str | None = Query(default=None, max_length=40, description="Lead a fresh batch with this house style"),
) -> dict[str, Any]:
    """Distinct exterior designs for this plan, best first, with the grammar to
    customise them. Without `seed`, the exterior designer's set for what the
    client said; with one, a fresh batch kept far from everything in `avoid`."""
    from aip.engines.experience import registry
    from aip.engines.experience.exteriors import generate, grammar, heard, prefer_from_text

    plan = _load(plan_id, principal)
    if seed is not None:
        # The client's words steer the batch as well as the style, and no
        # building another house has claimed is offered again.
        designs = [e.to_dict() for e in generate(plan, n, seed=seed, avoid=set(avoid), style=style,
                                                 prefer=prefer_from_text(prefs), taken=registry.taken_forms(plan_id))]
    else:
        from aip.agents.exterior_agent import design_exteriors

        designs = await design_exteriors(plan, prefs)
    return {"designs": designs, "grammar": grammar(), "style": plan.style, "heard": heard(prefs)}


@router.get("/{plan_id}/exteriors/grammar")
async def exterior_grammar(plan_id: str, principal: Principal = Depends(get_principal)) -> dict[str, Any]:
    """The customising vocabulary and colour schemes, with the plan's style and
    the design its model shows when none is chosen: what a drawing sheet needs
    to offer colours without loading a gallery."""
    from aip.engines.experience.exteriors import generate, grammar

    plan = _load(plan_id, principal)
    return {"grammar": grammar(), "style": plan.style, "default": generate(plan, 1)[0].id}


@router.post("/{plan_id}/exteriors/claim")
async def claim_exterior(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    design: str = Query(..., max_length=240, description="The exterior this house settles on"),
) -> dict[str, Any]:
    """Claim an exact exterior for this house, so no other house is offered
    it; says whether another house already has it."""
    from aip.engines.experience import registry

    _load(plan_id, principal)
    return registry.claim(plan_id, design)


@router.get("/{plan_id}/exteriors/fit")
async def fit_exterior(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    design: str = Query(..., max_length=200, description="A design id (ex:...), possibly customised"),
) -> dict[str, Any]:
    """A customised design made buildable on this plan: its normalised id,
    name and story, and a note for anything that had to change."""
    from aip.engines.experience.exteriors import Exterior

    ex = Exterior.parse(design)
    if ex is None:
        raise HTTPException(status_code=422, detail="Not an exterior design id.")
    fitted, notes = ex.fitted(len(_load(plan_id, principal).levels) <= 1)
    return {"design": fitted.to_dict(), "notes": notes}


@router.get("/{plan_id}/palettes")
async def get_palettes(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    colours: str | None = Query(default=None, max_length=600, description="The client's colour preferences, in words"),
) -> dict[str, Any]:
    """Coordinated exterior and interior colour schemes for this plan, best first, with reasons."""
    from aip.engines.experience.palettes import ColourPrefs, preferences_from_text, rank

    plan = _load(plan_id, principal)
    prefs = preferences_from_text(colours) if colours else ColourPrefs.from_dict(
        (plan.metadata or {}).get("colour_preferences"))
    from aip.engines.experience.facades import DESIGNS, ranked_designs

    return {"preferences": prefs.as_dict(), "schemes": rank(plan, prefs),
            "designs": [{"id": k, "name": DESIGNS[k]["name"], "story": DESIGNS[k]["story"]} for k in ranked_designs(plan)]}


@router.get("/{plan_id}/model.glb", response_class=Response)
async def get_model_glb(
    plan_id: str,
    principal: Principal = Depends(get_principal),
    furniture: bool = Query(default=True),
    ground: bool = Query(default=True),
    palette: str | None = Query(default=None, description="Colour scheme id; the recommended one if omitted"),
    colours: str | None = Query(default=None, max_length=600, description="The client's colour preferences, in words"),
    design: str | None = Query(default=None, description="Facade design language; the recommended one if omitted"),
) -> Response:
    """Binary glTF for the 3D viewer, VR walkthrough and AR placement."""
    import asyncio

    plan = _load(plan_id, principal)
    data = await asyncio.to_thread(export_glb, plan, include_furniture=furniture, include_ground=ground,
                                   palette_id=palette, colour_text=colours, design_id=design)
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

    # How the plan is walked: the route from the front door to every room,
    # and whether each one is legal. This is the check a client makes on the
    # plan before reading a single number, so it is returned beside them.
    from aip.domain.brief import default_residence_brief
    from aip.engines.architecture.programme import evaluate as evaluate_programme

    layout = evaluate_programme(plan, default_residence_brief())
    return {
        "plan_id": plan.id,
        "layout": layout.to_dict(),
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
    out = json.loads(report.model_dump_json())
    if payload.compare_to:
        # What an edit did to the Vastu: scored at the same stance, rule by rule.
        from aip.engines.vastu.engine import vastu_changes

        before = analyse_vastu(_load(payload.compare_to, principal), payload.tradition_weight)
        out["since_edit"] = vastu_changes(before, report)
    return out


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
