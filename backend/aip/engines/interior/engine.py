"""Interior layout solver.

Places furniture geometrically, respecting the constraints that decide whether a
room actually works:

* **Door swings** are blocked before anything is placed. A wardrobe that cannot
  open because the bedroom door hits it is the single most common defect in
  auto-generated interiors, and it is entirely avoidable.
* **Clearances** are treated as part of each item's footprint, so a bed is not
  "placed" unless there is room to walk around and make it.
* **Circulation** from the door into the room is preserved as a corridor of
  clear floor, so a layout can never seal off the space it furnishes.
* **Orientation preferences** are applied where they matter: the bed head goes
  against a solid wall rather than a window, the desk faces north light rather
  than into glare, the television sits at viewing distance from the seating, and
  the hob faces east where the client asked for Vastu compliance.

The result is a schedule with real positions, real dimensions and a real cost -
something a joiner can build from, not a picture of a room.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from aip.core.logging import get_logger, log_event
from aip.domain.brief import ClientBrief, DesignStyle
from aip.domain.geometry import BoundingBox, Direction, Vec2
from aip.domain.plan import FloorPlan, OpeningKind, Room, RoomType, Wall, WallKind
from aip.engines.interior.catalog import (
    FurnitureItem,
    Placement,
    StylePalette,
    items_for,
    palette_for,
)

logger = get_logger("aip.interior")

CIRCULATION_WIDTH = 0.75          # m of clear floor kept from every doorway


class PlacedFurniture(BaseModel):
    """One item, positioned."""

    item_id: str
    name: str
    x: float
    y: float
    rotation: float = 0.0          # degrees, counter-clockwise
    width: float
    depth: float
    height: float
    cost: float = 0.0
    against_wall: str = ""
    facing: str = ""
    notes: str = ""

    @property
    def footprint(self) -> BoundingBox:
        # Rotation is always a multiple of 90 degrees, so the extents just swap.
        swapped = abs(math.sin(math.radians(self.rotation))) > 0.5
        w = self.depth if swapped else self.width
        d = self.width if swapped else self.depth
        return BoundingBox(self.x - w / 2, self.y - d / 2, self.x + w / 2, self.y + d / 2)


class RoomInterior(BaseModel):
    """The complete interior specification for one room."""

    room_id: str
    room_name: str
    room_type: str
    area_m2: float
    direction: str = ""

    furniture: list[PlacedFurniture] = Field(default_factory=list)
    unplaced: list[dict[str, Any]] = Field(default_factory=list)

    palette: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, str] = Field(default_factory=dict)
    lighting: dict[str, Any] = Field(default_factory=dict)

    furniture_cost: float = 0.0
    finishes_cost: float = 0.0
    total_cost: float = 0.0

    utilisation: float = 0.0       # fraction of floor covered by furniture
    layout_score: float = 0.0
    notes: list[str] = Field(default_factory=list)
    render_prompt: str = ""


class InteriorScheme(BaseModel):
    """Interior design across a whole plan."""

    plan_id: str
    style: str
    rooms: list[RoomInterior] = Field(default_factory=list)
    palette: dict[str, Any] = Field(default_factory=dict)
    total_furniture_cost: float = 0.0
    total_finishes_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "INR"
    summary: str = ""


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Obstacle:
    """A region of floor that furniture must not occupy."""

    box: BoundingBox
    reason: str


def _overlaps(a: BoundingBox, b: BoundingBox, tolerance: float = 0.02) -> bool:
    return not (
        a.max_x <= b.min_x + tolerance
        or b.max_x <= a.min_x + tolerance
        or a.max_y <= b.min_y + tolerance
        or b.max_y <= a.min_y + tolerance
    )


def _inside(box: BoundingBox, room: BoundingBox, tolerance: float = 0.02) -> bool:
    return (
        box.min_x >= room.min_x - tolerance
        and box.max_x <= room.max_x + tolerance
        and box.min_y >= room.min_y - tolerance
        and box.max_y <= room.max_y + tolerance
    )


def _door_obstacles(plan: FloorPlan, room: Room) -> list[_Obstacle]:
    """Swing arcs and approach corridors for every door serving this room."""
    obstacles: list[_Obstacle] = []
    level = plan.level_at(room.level)
    if level is None:
        return obstacles

    for wall in level.walls:
        if room.id not in wall.rooms:
            continue
        for opening in wall.openings:
            if not opening.kind.is_door:
                continue

            centre = wall.point_at(opening.position)
            along = wall.direction_vector
            half = along * (opening.width / 2)
            hinge = centre - half

            # The leaf sweeps a quarter-disc of radius = door width, on the room
            # side of the wall only. Modelling it as a full square centred on the
            # door - the obvious shortcut - blocks a radius in every direction
            # and makes small rooms like a foyer or a WC entirely unfurnishable.
            inward = along.perpendicular()
            if (room.centre - centre).dot(inward) < 0:
                inward = inward * -1

            radius = opening.width
            corners = [
                hinge,
                hinge + along * radius,
                hinge + inward * radius,
                hinge + along * radius + inward * radius,
            ]
            xs = [p.x for p in corners]
            ys = [p.y for p in corners]
            obstacles.append(
                _Obstacle(
                    BoundingBox(min(xs), min(ys), max(xs), max(ys)),
                    f"door swing ({opening.kind.value})",
                )
            )
    return obstacles


def _window_segments(plan: FloorPlan, room: Room) -> list[tuple[Vec2, Vec2, Direction]]:
    """Window extents on this room's walls, with the direction each faces."""
    from aip.engines.architecture.layout import _wall_direction

    level = plan.level_at(room.level)
    if level is None:
        return []
    out: list[tuple[Vec2, Vec2, Direction]] = []
    for wall in level.walls:
        if room.id not in wall.rooms:
            continue
        facing = _wall_direction(plan, wall)
        for opening in wall.openings:
            if not opening.kind.is_glazed:
                continue
            centre = wall.point_at(opening.position)
            half = wall.direction_vector * (opening.width / 2)
            out.append((centre - half, centre + half, facing))
    return out


def _wall_runs(room: Room) -> list[tuple[str, Vec2, Vec2, Vec2]]:
    """The room's four wall faces as (name, start, end, inward normal)."""
    box = room.bbox
    return [
        ("south", Vec2(box.min_x, box.min_y), Vec2(box.max_x, box.min_y), Vec2(0, 1)),
        ("east", Vec2(box.max_x, box.min_y), Vec2(box.max_x, box.max_y), Vec2(-1, 0)),
        ("north", Vec2(box.max_x, box.max_y), Vec2(box.min_x, box.max_y), Vec2(0, -1)),
        ("west", Vec2(box.min_x, box.max_y), Vec2(box.min_x, box.min_y), Vec2(1, 0)),
    ]


def _clearance_zone(
    body: BoundingBox, normal: Vec2, front: float, side: float
) -> BoundingBox:
    """The usable-space rectangle in front of an item.

    Orientation-aware: the clearance extends along the wall's inward normal, and
    widens sideways perpendicular to it. Computing this as if every wall ran
    along X - which is the obvious mistake - makes items on east and west walls
    appear not to fit in rooms that comfortably accommodate them.
    """
    if abs(normal.y) > 0.5:                     # wall runs along X, front is +/-Y
        min_x, max_x = body.min_x - side, body.max_x + side
        if normal.y > 0:
            min_y, max_y = body.max_y, body.max_y + front
        else:
            min_y, max_y = body.min_y - front, body.min_y
    else:                                        # wall runs along Y, front is +/-X
        min_y, max_y = body.min_y - side, body.max_y + side
        if normal.x > 0:
            min_x, max_x = body.max_x, body.max_x + front
        else:
            min_x, max_x = body.min_x - front, body.min_x
    return BoundingBox(min_x, min_y, max_x, max_y)


def _rotation_for(normal: Vec2) -> float:
    """Rotation that puts an item's back against a wall with this inward normal."""
    if normal.y > 0.5:
        return 0.0        # against the south wall, facing north
    if normal.x < -0.5:
        return 90.0       # against the east wall, facing west
    if normal.y < -0.5:
        return 180.0
    return 270.0


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


def _place_room(
    plan: FloorPlan,
    room: Room,
    brief: ClientBrief,
) -> tuple[list[PlacedFurniture], list[dict[str, Any]], float, list[str]]:
    """Solve the furniture layout for one room."""
    box = room.bbox
    catalogue = items_for(room.type)
    if not catalogue:
        return [], [], 0.0, []

    obstacles = _door_obstacles(plan, room)
    windows = _window_segments(plan, room)
    placed: list[PlacedFurniture] = []
    unplaced: list[dict[str, Any]] = []
    notes: list[str] = []

    def collides(candidate: BoundingBox, clearance: BoundingBox) -> bool:
        """Hard rejection only.

        A position is illegal if the item body leaves the room, overlaps another
        item, or blocks a door. Clearance overlapping another item's *body* is
        deliberately not fatal - a nightstand legitimately sits inside the bed's
        side clearance, and rejecting that produced bedrooms with no bed. Such
        overlaps are penalised during scoring instead.
        """
        if not _inside(candidate, box):
            return True
        for existing in placed:
            if _overlaps(candidate, existing.footprint):
                return True
        for obstacle in obstacles:
            if _overlaps(candidate, obstacle.box):
                return True
        return False

    for item in catalogue:
        result = _try_place(item, room, box, windows, placed, collides, brief)

        if result is None and item.essential:
            # Second pass for essentials only. A designer facing a narrow room
            # pushes the bed into a corner and accepts one tight side rather
            # than leaving the room without a bed. Reproducing that judgement
            # matters: a "no layout possible" verdict on a perfectly ordinary
            # 2.65 m bedroom is wrong and destroys trust in the whole output.
            from dataclasses import replace

            relaxed = replace(
                item,
                side_clearance=item.side_clearance * 0.35,
                front_clearance=max(0.55, item.front_clearance * 0.8),
            )
            result = _try_place(relaxed, room, box, windows, placed, collides, brief)
            if result is not None:
                result.notes = (
                    (result.notes + " ") if result.notes else ""
                ) + "Placed with reduced side clearance; the room is tight for this item."
                notes.append(
                    f"{item.name} fits only with reduced clearance. Consider a "
                    f"smaller size or a wider room."
                )

        if result is None:
            if item.essential:
                unplaced.append(
                    {
                        "item_id": item.id,
                        "name": item.name,
                        "reason": (
                            f"No position leaves even a reduced clearance for this "
                            f"item. The room is {box.width:.2f} x {box.height:.2f} m "
                            f"and the item needs {item.width:.2f} x {item.depth:.2f} m "
                            f"plus {item.front_clearance:.2f} m in front."
                        ),
                        "essential": True,
                    }
                )
            continue
        placed.append(result)

    covered = sum(p.footprint.area for p in placed)
    utilisation = covered / room.area if room.area > 0 else 0.0

    if unplaced:
        notes.append(
            f"{len(unplaced)} essential item(s) could not be placed. The room is "
            f"too small or too awkwardly shaped for its intended function."
        )
    if utilisation > 0.62:
        notes.append(
            f"Furniture covers {utilisation:.0%} of the floor. Above about 60% a "
            f"room feels cramped regardless of its area."
        )
    return placed, unplaced, utilisation, notes


def _try_place(
    item: FurnitureItem,
    room: Room,
    box: BoundingBox,
    windows: list[tuple[Vec2, Vec2, Direction]],
    placed: list[PlacedFurniture],
    collides,
    brief: ClientBrief,
) -> PlacedFurniture | None:
    """Find the best legal position for one item, or None."""
    best: tuple[float, PlacedFurniture] | None = None

    if item.placement is Placement.BESIDE:
        parent = next((p for p in placed if p.item_id == item.parent), None)
        if parent is None:
            return None
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            pf = parent.footprint
            x = parent.x + dx * (pf.width / 2 + item.width / 2 + 0.05)
            y = parent.y + dy * (pf.height / 2 + item.depth / 2 + 0.05)
            candidate = BoundingBox(
                x - item.width / 2, y - item.depth / 2,
                x + item.width / 2, y + item.depth / 2,
            )
            clearance = BoundingBox(
                candidate.min_x, candidate.min_y - item.front_clearance,
                candidate.max_x, candidate.max_y,
            )
            if not collides(candidate, clearance):
                return PlacedFurniture(
                    item_id=item.id, name=item.name, x=round(x, 3), y=round(y, 3),
                    width=item.width, depth=item.depth, height=item.height,
                    cost=item.cost, notes=item.notes,
                )
        return None

    if item.placement is Placement.CENTRE:
        # Search a grid rather than only the exact centroid. A dining table
        # nudged half a metre off centre to clear a door swing is completely
        # normal; refusing to move it means reporting that a 14 m2 dining room
        # cannot hold a dining table, which is plainly wrong.
        for rotation in (0.0, 90.0):
            w = item.depth if rotation == 90 else item.width
            d = item.width if rotation == 90 else item.depth
            # Fine enough to find the gap between two door swings. A coarse
            # grid reports 'no position exists' for rooms that have one a few
            # centimetres away, which is indistinguishable from a real defect.
            steps = 15
            for ix in range(steps):
                for iy in range(steps):
                    cx = box.min_x + box.width * (ix + 0.5) / steps
                    cy = box.min_y + box.height * (iy + 0.5) / steps
                    candidate = BoundingBox(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
                    clearance = BoundingBox(
                        candidate.min_x - item.side_clearance,
                        candidate.min_y - item.front_clearance,
                        candidate.max_x + item.side_clearance,
                        candidate.max_y + item.front_clearance,
                    )
                    if not _inside(clearance, box) or collides(candidate, candidate):
                        continue
                    # Prefer positions near the middle of the room.
                    offset = Vec2(cx, cy).distance_to(box.centre)
                    score = 1.0 - offset / max(box.width, box.height)
                    if best is None or score > best[0]:
                        best = (
                            score,
                            PlacedFurniture(
                                item_id=item.id, name=item.name,
                                x=round(cx, 3), y=round(cy, 3), rotation=rotation,
                                width=item.width, depth=item.depth, height=item.height,
                                cost=item.cost, notes=item.notes,
                            ),
                        )
        return best[1] if best else None

    # AGAINST_WALL, CORNER, COUNTER_RUN and FLOATING all slide along wall faces.
    # Each wall is tried in two orientations: the natural one with the item's
    # back to the wall, and a quarter turn with its long side to the wall. The
    # turned option is worse and is scored down, but in a narrow room it is
    # often the only arrangement that fits - and it is what a designer would do
    # rather than declaring the room unfurnishable.
    for name, start, end, normal in _wall_runs(room):
        length = (end - start).length
        unit = (end - start).normalised()
        along_x = abs(unit.x) > 0.5
        base_rotation = _rotation_for(normal)

        for turned in (False, True):
            face = item.depth if turned else item.width
            depth = item.width if turned else item.depth
            if length < face + 0.1:
                continue
            rotation = (base_rotation + 90) % 360 if turned else base_rotation
            w = face if along_x else depth
            d = depth if along_x else face
            turn_penalty = 0.45 if turned else 0.0

            steps = max(6, int(length / 0.12))
            for step in range(steps + 1):
                centre_along = start + unit * ((step / steps) * length)
                # Offset from the wall by half the extent *along the normal*:
                # `d` for a wall running along X, `w` for one running along Y.
                # Using `d` unconditionally makes items on east and west walls
                # straddle the wall and be rejected as outside the room.
                offset = (d if along_x else w) / 2
                centre = centre_along + normal * offset
                candidate = BoundingBox(
                    centre.x - w / 2, centre.y - d / 2, centre.x + w / 2, centre.y + d / 2
                )
                clearance = _clearance_zone(
                    candidate, normal, item.front_clearance, item.side_clearance
                )
                if not _inside(candidate, box) or not _inside(clearance, box):
                    continue
                if collides(candidate, candidate):
                    continue

                score = _score_position(
                    item, room, candidate, name, normal, windows, placed, box, brief
                ) - turn_penalty
                # Clearance landing on another item's body is workable but worse.
                for existing in placed:
                    if _overlaps(clearance, existing.footprint):
                        score -= 0.3

                if best is None or score > best[0]:
                    best = (
                        score,
                        PlacedFurniture(
                            item_id=item.id, name=item.name,
                            x=round(centre.x, 3), y=round(centre.y, 3), rotation=rotation,
                            width=item.width, depth=item.depth, height=item.height,
                            cost=item.cost, against_wall=name,
                            facing=_facing_label(normal),
                            notes=(item.notes + (" Turned to fit the wall run." if turned else "")).strip(),
                        ),
                    )
    return best[1] if best else None


def _score_position(
    item: FurnitureItem,
    room: Room,
    candidate: BoundingBox,
    wall_name: str,
    normal: Vec2,
    windows: list[tuple[Vec2, Vec2, Direction]],
    placed: list[PlacedFurniture],
    box: BoundingBox,
    brief: ClientBrief,
) -> float:
    """Rank a legal position by how well it serves the item's purpose."""
    score = 1.0
    centre = candidate.centre

    # Prefer a solid wall behind, not a window.
    on_window = any(
        min(a.x, b.x) - 0.3 <= centre.x <= max(a.x, b.x) + 0.3
        and min(a.y, b.y) - 0.3 <= centre.y <= max(a.y, b.y) + 0.3
        for a, b, _ in windows
    )
    if "bed" in item.id or "sofa" in item.id or "wardrobe" in item.id:
        score += 0.0 if not on_window else -0.55

    # Desks want daylight in front, and north light specifically to avoid glare.
    if "desk" in item.id and windows:
        nearest = min(
            windows,
            key=lambda w: centre.distance_to((w[0] + w[1]) * 0.5),
        )
        distance = centre.distance_to((nearest[0] + nearest[1]) * 0.5)
        score += max(0.0, 0.5 - distance * 0.12)
        if nearest[2].cardinal in {Direction.N, Direction.NE}:
            score += 0.35

    # A television needs viewing distance from the seating already placed.
    if "tv" in item.id or "media" in item.id or "screen" in item.id:
        seating = [p for p in placed if "sofa" in p.item_id or "sectional" in p.item_id or "recliner" in p.item_id]
        if seating:
            distance = min(centre.distance_to(Vec2(s.x, s.y)) for s in seating)
            score += 0.9 if 2.2 <= distance <= 4.5 else -0.5
        else:
            # Placed before the seating: favour the wall opposite the longest run.
            score += 0.2

    # Corner items genuinely want a corner.
    if item.placement is Placement.CORNER:
        corner_distance = min(
            centre.distance_to(Vec2(x, y))
            for x in (box.min_x, box.max_x)
            for y in (box.min_y, box.max_y)
        )
        score += max(0.0, 1.0 - corner_distance * 0.6)

    # Kitchen counters want the longest available wall.
    if item.placement is Placement.COUNTER_RUN:
        score += 0.5 if wall_name in {"south", "north"} and box.width >= box.height else 0.0

    # Vastu preferences where the client asked for them, applied as a nudge -
    # never at the cost of a layout that would otherwise fail.
    if brief.vastu.is_constraining:
        weight = brief.tradition_weight
        if "mandir" in item.id and wall_name == "west":
            score += 0.6 * weight        # worshipper then faces east
        if "bed" in item.id and wall_name == "south":
            score += 0.4 * weight        # head to the south
        if "counter" in item.id and wall_name in {"south", "east"}:
            score += 0.4 * weight        # cook faces east

    # Keep the middle of the room clear so it stays usable.
    score += 0.25 * (centre.distance_to(box.centre) / max(box.width, box.height))
    return score


def _facing_label(normal: Vec2) -> str:
    if normal.y > 0.5:
        return "north"
    if normal.y < -0.5:
        return "south"
    if normal.x > 0.5:
        return "east"
    return "west"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def design_room(
    plan: FloorPlan, room: Room, brief: ClientBrief, palette: StylePalette | None = None
) -> RoomInterior:
    """Full interior specification for a single room."""
    palette = palette or palette_for(brief.style.primary)
    placed, unplaced, utilisation, notes = _place_room(plan, room, brief)

    furniture_cost = sum(p.cost for p in placed)
    finishes_cost = _finishes_cost(room)
    lighting = _lighting_for(room, palette, plan)
    direction = plan.direction_of_room(room)

    layout_score = _layout_score(room, placed, unplaced, utilisation)

    interior = RoomInterior(
        room_id=room.id,
        room_name=room.display_name(),
        room_type=room.type.value,
        area_m2=room.area,
        direction=direction.value,
        furniture=placed,
        unplaced=unplaced,
        palette={
            "style": palette.style.value,
            "swatches": palette.swatches(),
            "character": palette.character,
        },
        materials={
            "floor": palette.floor_material,
            "walls": f"{palette.wall} emulsion over putty",
            "accent_wall": palette.wall_accent,
            "ceiling": f"{palette.ceiling}, gypsum false ceiling" if not room.type.is_wet else "moisture-resistant board",
            "joinery": palette.joinery_material,
            "metal": palette.metal,
        },
        lighting=lighting,
        furniture_cost=round(furniture_cost, 2),
        finishes_cost=round(finishes_cost, 2),
        total_cost=round(furniture_cost + finishes_cost, 2),
        utilisation=round(utilisation, 4),
        layout_score=round(layout_score, 4),
        notes=notes,
    )
    interior.render_prompt = build_render_prompt(interior, palette, room, direction)
    return interior


def _finishes_cost(room: Room) -> float:
    """Indicative finishes cost for a room, driven by area and wet/dry use."""
    rate = 4_200.0 if room.type.is_wet else 2_600.0
    if room.type.is_outdoor:
        rate = 1_400.0
    return room.area * rate


def _lighting_for(room: Room, palette: StylePalette, plan: FloorPlan) -> dict[str, Any]:
    """Lighting layout: lux target, fitting count and control strategy."""
    # Lux targets from IS 3646 / general practice.
    lux = {
        RoomType.LIVING: 200, RoomType.DRAWING: 200, RoomType.FAMILY: 200,
        RoomType.DINING: 200, RoomType.KITCHEN: 400, RoomType.STUDY: 500,
        RoomType.HOME_OFFICE: 500, RoomType.MASTER_BEDROOM: 150,
        RoomType.BEDROOM: 150, RoomType.CHILDREN_BEDROOM: 300,
        RoomType.BATHROOM: 200, RoomType.TOILET: 150, RoomType.PUJA: 200,
        RoomType.CORRIDOR: 100, RoomType.FOYER: 150, RoomType.STAIRCASE: 150,
    }.get(room.type, 150)

    # ~900 lumens per typical LED downlight, with a utilisation allowance.
    required_lumens = lux * room.area / 0.6
    downlights = max(1, round(required_lumens / 900))

    layers = ["Ambient: recessed LED downlights on a dimmable circuit"]
    if room.type in {RoomType.LIVING, RoomType.DRAWING, RoomType.FAMILY, RoomType.DINING}:
        layers.append("Accent: cove lighting to the perimeter of the false ceiling")
        layers.append("Task: table and floor lamps on switched sockets")
    if room.type is RoomType.KITCHEN:
        layers.append("Task: LED strip under the wall units, over the counter")
    if room.type in {RoomType.STUDY, RoomType.HOME_OFFICE}:
        layers.append("Task: adjustable desk lamp, at least 500 lux at the work plane")
    if room.type is RoomType.PUJA:
        layers.append("Accent: warm 2700K focused light on the deity niche")
    if room.type.is_wet:
        layers.append("Task: IP44 mirror light, vertically flanking rather than above")

    return {
        "target_lux": lux,
        "colour_temperature_k": palette.lighting_kelvin,
        "downlight_count": downlights,
        "estimated_load_w": round(downlights * 9 + 40, 0),
        "layers": layers,
        "strategy": palette.lighting_strategy,
        "controls": "Two-way switching at entry and bedside" if room.type.is_private else "Scene control at entry",
    }


def _layout_score(
    room: Room, placed: list[PlacedFurniture], unplaced: list[dict[str, Any]], utilisation: float
) -> float:
    if not placed and not unplaced:
        return 0.5
    total = len(placed) + len(unplaced)
    completeness = len(placed) / total if total else 0.0
    # Essential items missing is a severe defect, not a proportional shortfall.
    essential_penalty = 0.35 * len([u for u in unplaced if u.get("essential")])
    # Best utilisation sits around 35-50%: enough furniture to work, enough
    # floor to move.
    if utilisation < 0.18:
        density = utilisation / 0.18 * 0.7
    elif utilisation <= 0.52:
        density = 1.0
    else:
        density = max(0.0, 1.0 - (utilisation - 0.52) * 2.2)
    return max(0.0, min(1.0, 0.55 * completeness + 0.45 * density - essential_penalty))


def build_render_prompt(
    interior: RoomInterior, palette: StylePalette, room: Room, direction: Direction
) -> str:
    """Prompt for the free image backends.

    Built from the *solved* layout rather than from the brief, so the render
    depicts the room that was actually designed - the same furniture, the same
    palette, the same orientation - instead of an unrelated stock interior.
    """
    furniture = ", ".join(p.name.lower() for p in interior.furniture[:6]) or "minimal furnishing"
    materials = ", ".join(palette.materials[:4])
    daylight = {
        Direction.N: "soft even north daylight",
        Direction.NE: "gentle morning light",
        Direction.E: "warm morning sunlight",
        Direction.S: "bright diffused daylight",
        Direction.W: "warm late afternoon light through screening",
    }.get(direction.cardinal, "natural daylight")

    return (
        f"Interior photograph of a {room.display_name().lower()}, "
        f"{room.area:.0f} square metres, {palette.style.value.replace('_', ' ')} style. "
        f"Contains {furniture}. "
        f"Materials: {materials}. "
        f"Walls {palette.wall}, floor in {palette.floor_material.lower()}, "
        f"joinery in {palette.joinery_material.lower()}. "
        f"{daylight} from the {direction.value} side. "
        f"{palette.lighting_kelvin}K artificial lighting, {palette.lighting_strategy.lower()}. "
        f"Architectural photography, wide angle, eye level, realistic proportions, "
        f"no people, no text."
    )


def design_interior(
    plan: FloorPlan,
    brief: ClientBrief | None = None,
    *,
    room_ids: set[str] | None = None,
) -> InteriorScheme:
    """Interior design for a whole plan."""
    brief = brief or ClientBrief()
    palette = palette_for(brief.style.primary)

    rooms = [
        r for r in plan.all_rooms
        if (room_ids is None or r.id in room_ids)
        and r.type not in {RoomType.SHAFT, RoomType.STAIRCASE}
        and not r.type.is_outdoor
    ]

    interiors = [design_room(plan, room, brief, palette) for room in rooms]
    furniture_total = sum(i.furniture_cost for i in interiors)
    finishes_total = sum(i.finishes_cost for i in interiors)

    unplaced_essential = sum(
        len([u for u in i.unplaced if u.get("essential")]) for i in interiors
    )
    mean_score = (
        sum(i.layout_score for i in interiors) / len(interiors) if interiors else 0.0
    )

    scheme = InteriorScheme(
        plan_id=plan.id,
        style=palette.style.value,
        rooms=interiors,
        palette={
            "style": palette.style.value,
            "swatches": palette.swatches(),
            "materials": list(palette.materials),
            "avoid": list(palette.avoid),
            "character": palette.character,
            "lighting_kelvin": palette.lighting_kelvin,
        },
        total_furniture_cost=round(furniture_total, 2),
        total_finishes_cost=round(finishes_total, 2),
        total_cost=round(furniture_total + finishes_total, 2),
        currency=brief.budget.currency or "INR",
    )
    scheme.summary = (
        f"{len(interiors)} rooms furnished in {palette.style.value.replace('_', ' ')} style. "
        f"Furniture {furniture_total:,.0f} plus finishes {finishes_total:,.0f} = "
        f"{scheme.total_cost:,.0f} {scheme.currency}. "
        f"Mean layout quality {mean_score:.2f}."
        + (
            f" {unplaced_essential} essential item(s) could not be placed - "
            f"those rooms need more space or a different arrangement."
            if unplaced_essential
            else " Every essential item was placed with its required clearances."
        )
    )
    log_event(
        logger, "interior.designed",
        plan=plan.id, rooms=len(interiors), cost=scheme.total_cost,
        unplaced_essential=unplaced_essential, mean_score=round(mean_score, 3),
    )
    return scheme
