"""3D model generation.

Extrudes a `FloorPlan` into a watertight-enough polygonal model and exports
glTF/GLB - the format every browser, phone and XR headset reads natively.

The interesting problem is openings. Cutting a hole in a wall properly needs
constructive solid geometry, which needs a boolean backend (manifold3d, Blender
or OpenSCAD) that would be another dependency and another failure mode. Instead
the wall is *decomposed*: for each opening the wall is split into the pieces
around it - a section below the sill, one above the head, and full-height
sections between openings. The result is identical geometry to a boolean
subtraction, produced with nothing but box primitives, and it is fast, exact and
dependency-free.

The Y axis is up in the exported model, matching the glTF convention, so the
plan's Z becomes Y and the plan's Y becomes -Z.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from aip.core.logging import get_logger, log_event
from aip.domain.geometry import BoundingBox, Vec2
from aip.domain.plan import FloorPlan, Level, Opening, Room, RoomType, Wall

logger = get_logger("aip.experience.model3d")


#: RGBA colours by room type, used for the floor finishes in the 3D view.
ROOM_COLOURS: dict[RoomType, tuple[int, int, int, int]] = {
    RoomType.LIVING: (222, 210, 190, 255),
    RoomType.DRAWING: (222, 210, 190, 255),
    RoomType.FAMILY: (218, 206, 186, 255),
    RoomType.DINING: (214, 199, 176, 255),
    RoomType.KITCHEN: (206, 212, 208, 255),
    RoomType.MASTER_BEDROOM: (196, 176, 152, 255),
    RoomType.BEDROOM: (200, 182, 158, 255),
    RoomType.GUEST_BEDROOM: (200, 182, 158, 255),
    RoomType.CHILDREN_BEDROOM: (205, 190, 170, 255),
    RoomType.BATHROOM: (186, 204, 212, 255),
    RoomType.TOILET: (186, 204, 212, 255),
    RoomType.POWDER: (190, 206, 214, 255),
    RoomType.PUJA: (226, 200, 150, 255),
    RoomType.STUDY: (198, 190, 176, 255),
    RoomType.HOME_OFFICE: (198, 190, 176, 255),
    RoomType.CORRIDOR: (212, 206, 196, 255),
    RoomType.FOYER: (212, 206, 196, 255),
    RoomType.LOBBY: (212, 206, 196, 255),
    RoomType.STAIRCASE: (176, 172, 166, 255),
    RoomType.BALCONY: (170, 186, 162, 255),
    RoomType.TERRACE: (170, 186, 162, 255),
    RoomType.COURTYARD: (162, 184, 152, 255),
    RoomType.VERANDAH: (176, 190, 168, 255),
    RoomType.UTILITY: (196, 200, 196, 255),
    RoomType.STORE: (190, 186, 180, 255),
    RoomType.GARAGE: (170, 170, 172, 255),
}

WALL_COLOUR = (238, 236, 231, 255)
SLAB_COLOUR = (204, 200, 194, 255)
GLASS_COLOUR = (150, 200, 225, 110)
DOOR_COLOUR = (140, 104, 72, 255)
GROUND_COLOUR = (176, 186, 168, 255)


@dataclass(slots=True)
class MeshPart:
    """One named chunk of geometry with a colour."""

    name: str
    vertices: np.ndarray            # (n, 3) float
    faces: np.ndarray               # (m, 3) int
    colour: tuple[int, int, int, int]
    category: str = "structure"


@dataclass(slots=True)
class BuildingModel:
    """The assembled 3D model."""

    parts: list[MeshPart] = field(default_factory=list)
    bounds: BoundingBox | None = None
    height: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def vertex_count(self) -> int:
        return sum(len(p.vertices) for p in self.parts)

    @property
    def triangle_count(self) -> int:
        return sum(len(p.faces) for p in self.parts)


def _box(
    centre: tuple[float, float, float], size: tuple[float, float, float], rotation_y: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """Axis-aligned box, optionally spun about the vertical axis."""
    hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
    corners = np.array(
        [
            [-hx, -hy, -hz], [hx, -hy, -hz], [hx, hy, -hz], [-hx, hy, -hz],
            [-hx, -hy, hz], [hx, -hy, hz], [hx, hy, hz], [-hx, hy, hz],
        ],
        dtype=np.float64,
    )
    if abs(rotation_y) > 1e-9:
        c, s = math.cos(rotation_y), math.sin(rotation_y)
        matrix = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
        corners = corners @ matrix.T
    corners += np.array(centre)

    faces = np.array(
        [
            [0, 2, 1], [0, 3, 2],      # -Z
            [4, 5, 6], [4, 6, 7],      # +Z
            [0, 1, 5], [0, 5, 4],      # -Y
            [3, 7, 6], [3, 6, 2],      # +Y
            [0, 4, 7], [0, 7, 3],      # -X
            [1, 2, 6], [1, 6, 5],      # +X
        ],
        dtype=np.int64,
    )
    return corners, faces


def _prism(polygon: list[Vec2], base_y: float, thickness: float) -> tuple[np.ndarray, np.ndarray]:
    """Extrude a horizontal polygon vertically (a slab or floor plate)."""
    n = len(polygon)
    if n < 3:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)

    lower = [(p.x, base_y, -p.y) for p in polygon]
    upper = [(p.x, base_y + thickness, -p.y) for p in polygon]
    vertices = np.array(lower + upper, dtype=np.float64)

    faces: list[list[int]] = []
    # Fan triangulation is valid here because generated rooms are convex
    # rectangles; imported non-convex outlines fall back to their bounding box
    # in `_room_floor`, so this stays correct in both paths.
    for i in range(1, n - 1):
        faces.append([0, i + 1, i])              # bottom, wound downward
        faces.append([n, n + i, n + i + 1])      # top
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    return vertices, np.array(faces, dtype=np.int64)


def build_model(
    plan: FloorPlan,
    *,
    include_glazing: bool = True,
    include_ground: bool = True,
    include_furniture: bool = False,
) -> BuildingModel:
    """Assemble the full 3D model from a plan."""
    model = BuildingModel()
    base_y = 0.0

    if include_ground and plan.site.boundary:
        vertices, faces = _prism(plan.site.boundary, -0.35, 0.35)
        model.parts.append(MeshPart("ground", vertices, faces, GROUND_COLOUR, "site"))

    for level in plan.levels:
        _add_level(model, plan, level, base_y, include_glazing, include_furniture)
        base_y += level.floor_to_floor

    # Roof slab and parapet.
    if plan.levels:
        env = plan.envelope()
        vertices, faces = _prism(env.to_polygon(), base_y, 0.15)
        model.parts.append(MeshPart("roof_slab", vertices, faces, SLAB_COLOUR, "structure"))
        _add_parapet(model, env, base_y + 0.15, 0.9)

    model.bounds = plan.envelope()
    model.height = base_y + 1.05
    model.metadata = {
        "plan_id": plan.id,
        "plan_name": plan.name,
        "levels": len(plan.levels),
        "built_area_m2": plan.total_built_area,
    }
    log_event(
        logger, "model3d.built",
        plan=plan.id, parts=len(model.parts),
        vertices=model.vertex_count, triangles=model.triangle_count,
    )
    return model


def _add_level(
    model: BuildingModel,
    plan: FloorPlan,
    level: Level,
    base_y: float,
    include_glazing: bool,
    include_furniture: bool,
) -> None:
    # Floor slab under the whole level.
    env = level.envelope()
    if env.area > 0:
        vertices, faces = _prism(env.to_polygon(), base_y - 0.15, 0.15)
        model.parts.append(
            MeshPart(f"slab_L{level.index}", vertices, faces, SLAB_COLOUR, "structure")
        )

    for room in level.rooms:
        _room_floor(model, room, base_y)
        if include_furniture:
            _room_furniture(model, room, base_y)

    for wall in level.walls:
        _add_wall(model, wall, base_y, level.floor_to_floor, include_glazing)

    for stair in level.staircases:
        _add_stair(model, stair, base_y)


def _room_floor(model: BuildingModel, room: Room, base_y: float) -> None:
    if room.type is RoomType.SHAFT:
        return
    polygon = room.polygon
    if len(polygon) > 4:
        # Non-convex imported outline: use its bounding box so the fan
        # triangulation in `_prism` stays valid rather than producing folds.
        polygon = room.bbox.to_polygon()
    vertices, faces = _prism(polygon, base_y, 0.02)
    colour = ROOM_COLOURS.get(room.type, (210, 205, 198, 255))
    model.parts.append(
        MeshPart(f"floor_{room.id}", vertices, faces, colour, "finish")
    )


def _add_wall(
    model: BuildingModel,
    wall: Wall,
    base_y: float,
    floor_to_floor: float,
    include_glazing: bool,
) -> None:
    """Build a wall as the set of solid pieces left around its openings."""
    direction = wall.end - wall.start
    length = direction.length
    if length < 1e-6:
        return

    height = min(wall.height, floor_to_floor - 0.15)
    unit = direction.normalised()
    angle = math.atan2(-unit.y, unit.x)          # plan Y maps to model -Z
    midpoint = (wall.start + wall.end) * 0.5
    thickness = wall.thickness
    colour = WALL_COLOUR

    openings = sorted(wall.openings, key=lambda o: o.position)
    if not openings:
        _emit_wall_piece(model, wall, midpoint, 0.0, length, 0.0, height, thickness, angle, base_y, colour)
        return

    def piece(u0: float, u1: float, y0: float, y1: float) -> None:
        if u1 - u0 < 0.01 or y1 - y0 < 0.01:
            return
        offset = (u0 + u1) / 2 - length / 2
        centre = midpoint + unit * offset
        _emit_wall_piece(
            model, wall, centre, 0.0, u1 - u0, y0, y1, thickness, angle, base_y, colour
        )

    cursor = 0.0
    for opening in openings:
        centre_u = opening.position * length
        left = max(0.0, centre_u - opening.width / 2)
        right = min(length, centre_u + opening.width / 2)
        if right <= left:
            continue

        # Full-height wall before the opening.
        piece(cursor, left, 0.0, height)
        # Below the sill and above the head.
        piece(left, right, 0.0, min(opening.sill_height, height))
        piece(left, right, min(opening.head_height, height), height)

        if include_glazing:
            _add_opening_panel(model, wall, opening, unit, midpoint, length, angle, base_y, height)
        cursor = right

    piece(cursor, length, 0.0, height)


def _emit_wall_piece(
    model: BuildingModel,
    wall: Wall,
    centre: Vec2,
    _unused: float,
    piece_length: float,
    y0: float,
    y1: float,
    thickness: float,
    angle: float,
    base_y: float,
    colour: tuple[int, int, int, int],
) -> None:
    height = y1 - y0
    vertices, faces = _box(
        (centre.x, base_y + y0 + height / 2, -centre.y),
        (piece_length, height, thickness),
        rotation_y=angle,
    )
    model.parts.append(MeshPart(f"wall_{wall.id}_{len(model.parts)}", vertices, faces, colour, "structure"))


def _add_opening_panel(
    model: BuildingModel,
    wall: Wall,
    opening: Opening,
    unit: Vec2,
    midpoint: Vec2,
    length: float,
    angle: float,
    base_y: float,
    wall_height: float,
) -> None:
    """A thin panel filling the aperture: glass for windows, a leaf for doors."""
    centre_u = opening.position * length
    centre = midpoint + unit * (centre_u - length / 2)
    top = min(opening.head_height, wall_height)
    panel_height = max(0.05, top - opening.sill_height)
    if panel_height <= 0.05:
        return

    is_glass = opening.kind.is_glazed
    colour = GLASS_COLOUR if is_glass else DOOR_COLOUR
    vertices, faces = _box(
        (centre.x, base_y + opening.sill_height + panel_height / 2, -centre.y),
        (opening.width, panel_height, 0.04),
        rotation_y=angle,
    )
    model.parts.append(
        MeshPart(
            f"{'glazing' if is_glass else 'door'}_{opening.id}",
            vertices, faces, colour, "glazing" if is_glass else "joinery",
        )
    )


def _add_parapet(model: BuildingModel, env: BoundingBox, base_y: float, height: float) -> None:
    thickness = 0.115
    edges = [
        ((env.min_x, env.min_y), (env.max_x, env.min_y)),
        ((env.max_x, env.min_y), (env.max_x, env.max_y)),
        ((env.max_x, env.max_y), (env.min_x, env.max_y)),
        ((env.min_x, env.max_y), (env.min_x, env.min_y)),
    ]
    for index, ((x0, y0), (x1, y1)) in enumerate(edges):
        start, end = Vec2(x0, y0), Vec2(x1, y1)
        direction = end - start
        length = direction.length
        if length < 1e-6:
            continue
        unit = direction.normalised()
        angle = math.atan2(-unit.y, unit.x)
        centre = (start + end) * 0.5
        vertices, faces = _box(
            (centre.x, base_y + height / 2, -centre.y),
            (length, height, thickness),
            rotation_y=angle,
        )
        model.parts.append(
            MeshPart(f"parapet_{index}", vertices, faces, WALL_COLOUR, "structure")
        )


def _add_stair(model: BuildingModel, stair, base_y: float) -> None:
    """Individual treads, so the stair reads as a stair in the walkthrough."""
    from aip.domain.geometry import bounding_box

    box = bounding_box(stair.polygon)
    if box.width < 0.4 or box.height < 0.4:
        return
    horizontal = box.width >= box.height
    steps = max(1, min(stair.step_count, 24))
    run = (box.width if horizontal else box.height) / steps
    width = stair.width if stair.width > 0 else (box.height if horizontal else box.width)

    for i in range(steps):
        y = base_y + (i + 1) * stair.riser
        if horizontal:
            cx = box.min_x + run * (i + 0.5)
            cz = box.centre.y
            size = (run, 0.06, width)
        else:
            cx = box.centre.x
            cz = box.min_y + run * (i + 0.5)
            size = (width, 0.06, run)
        vertices, faces = _box((cx, y, -cz), size)
        model.parts.append(
            MeshPart(f"tread_{stair.id}_{i}", vertices, faces, SLAB_COLOUR, "structure")
        )


def _room_furniture(model: BuildingModel, room: Room, base_y: float) -> None:
    """Blocky indicative furniture, so an empty walkthrough reads as a home."""
    box = room.bbox
    if box.width < 1.6 or box.height < 1.6:
        return
    centre = room.centre
    colour = (150, 130, 110, 255)

    def block(cx: float, cy: float, w: float, d: float, h: float) -> None:
        vertices, faces = _box((cx, base_y + h / 2, -cy), (w, h, d))
        model.parts.append(
            MeshPart(f"furn_{room.id}_{len(model.parts)}", vertices, faces, colour, "furniture")
        )

    if room.type in {RoomType.MASTER_BEDROOM, RoomType.BEDROOM,
                     RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM}:
        block(centre.x, centre.y, min(1.8, box.width - 0.8), min(2.0, box.height - 0.8), 0.5)
    elif room.type in {RoomType.LIVING, RoomType.DRAWING, RoomType.FAMILY}:
        block(centre.x, centre.y - box.height * 0.18, min(2.2, box.width - 1.0), 0.85, 0.42)
        block(centre.x, centre.y + box.height * 0.1, min(1.1, box.width - 1.4), 0.55, 0.4)
    elif room.type is RoomType.DINING:
        block(centre.x, centre.y, min(1.5, box.width - 0.9), min(0.95, box.height - 0.9), 0.75)
    elif room.type is RoomType.KITCHEN:
        if box.width >= box.height:
            block(centre.x, box.min_y + 0.35, box.width - 0.4, 0.6, 0.9)
        else:
            block(box.min_x + 0.35, centre.y, 0.6, box.height - 0.4, 0.9)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_glb(plan: FloorPlan, **options: Any) -> bytes:
    """Export the plan as binary glTF.

    GLB is the right target: a single self-contained binary that browsers,
    `<model-viewer>`, Android Scene Viewer and every WebXR runtime load natively,
    with no conversion service and no licence.
    """
    model = build_model(plan, **options)
    try:
        import trimesh

        scene = trimesh.Scene()
        for part in model.parts:
            if len(part.faces) == 0:
                continue
            mesh = trimesh.Trimesh(
                vertices=part.vertices, faces=part.faces, process=False
            )
            mesh.visual = trimesh.visual.ColorVisuals(
                mesh=mesh, face_colors=np.tile(np.array(part.colour, dtype=np.uint8), (len(part.faces), 1))
            )
            scene.add_geometry(mesh, node_name=part.name, geom_name=part.name)

        buffer = io.BytesIO()
        scene.export(buffer, file_type="glb")
        data = buffer.getvalue()
        log_event(logger, "model3d.exported", format="glb", bytes=len(data), parts=len(model.parts))
        return data
    except ImportError as exc:  # pragma: no cover - trimesh is a hard dependency
        raise RuntimeError("trimesh is required for GLB export") from exc


def export_obj(plan: FloorPlan, **options: Any) -> str:
    """Export as Wavefront OBJ.

    Kept because OBJ is the universal import format for the CAD and rendering
    tools architects already own, and it needs no library at all to write.
    """
    model = build_model(plan, **options)
    lines: list[str] = [
        f"# Architect Intelligence Platform - {plan.name}",
        f"# {model.vertex_count} vertices, {model.triangle_count} triangles",
        "",
    ]
    offset = 1
    for part in model.parts:
        if len(part.faces) == 0:
            continue
        lines.append(f"o {part.name}")
        for vertex in part.vertices:
            lines.append(f"v {vertex[0]:.4f} {vertex[1]:.4f} {vertex[2]:.4f}")
        for face in part.faces:
            lines.append(f"f {face[0] + offset} {face[1] + offset} {face[2] + offset}")
        offset += len(part.vertices)
        lines.append("")
    return "\n".join(lines)


def model_statistics(plan: FloorPlan) -> dict[str, Any]:
    """Model size and composition, surfaced in the API."""
    model = build_model(plan)
    by_category: dict[str, int] = {}
    for part in model.parts:
        by_category[part.category] = by_category.get(part.category, 0) + len(part.faces)
    return {
        "parts": len(model.parts),
        "vertices": model.vertex_count,
        "triangles": model.triangle_count,
        "triangles_by_category": by_category,
        "height_m": round(model.height, 3),
        "bounds": {
            "width_m": round(model.bounds.width, 3) if model.bounds else 0.0,
            "depth_m": round(model.bounds.height, 3) if model.bounds else 0.0,
        },
    }


def camera_waypoints(plan: FloorPlan) -> list[dict[str, Any]]:
    """Suggested walkthrough stops, one per significant room.

    Ordered as a visitor would actually experience the house - entrance first,
    then social spaces, then private ones - because a walkthrough that jumps
    between rooms at random teaches a client nothing about how the home works.
    """
    order = [
        RoomType.FOYER, RoomType.LOBBY, RoomType.LIVING, RoomType.DRAWING,
        RoomType.DINING, RoomType.KITCHEN, RoomType.FAMILY, RoomType.STUDY,
        RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.CHILDREN_BEDROOM,
        RoomType.GUEST_BEDROOM, RoomType.PUJA, RoomType.BALCONY, RoomType.TERRACE,
    ]
    rank = {room_type: index for index, room_type in enumerate(order)}

    waypoints: list[dict[str, Any]] = []
    for level in plan.levels:
        base = level.elevation
        rooms = sorted(
            (r for r in level.rooms if r.area >= 4.0 and r.type is not RoomType.SHAFT),
            key=lambda r: rank.get(r.type, 99),
        )
        for room in rooms:
            centre = room.centre
            waypoints.append(
                {
                    "room_id": room.id,
                    "label": f"{room.display_name()} ({level.display_name()})",
                    "position": [round(centre.x, 3), round(base + 1.6, 3), round(-centre.y, 3)],
                    "target": [round(centre.x, 3), round(base + 1.4, 3), round(-centre.y - 2.0, 3)],
                    "area_m2": room.area,
                    "type": room.type.value,
                }
            )
    return waypoints
