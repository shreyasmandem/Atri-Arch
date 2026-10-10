"""Targeted plan repair.

The critics do not just complain - each finding names a specific element and a
specific remedy. This module applies those remedies mechanically.

Repair is deliberately conservative. It adjusts openings, door widths and
ceiling heights: changes that fix a defect without redesigning the building. It
never moves walls or reassigns rooms, because that is a different scheme and
would need to go back through the whole committee rather than being slipped in
after the decision. Anything requiring that scale of change is reported to the
architect as a recommendation instead of being silently applied.

The caller re-scores afterwards and discards the result if it did not improve,
so the loop is monotonic by construction.
"""

from __future__ import annotations

from typing import Callable

from aip.agents.base import Finding
from aip.core.logging import get_logger, log_event
from aip.domain.brief import ClientBrief
from aip.domain.geometry import shared_edge
from aip.domain.plan import FloorPlan, Level, Opening, OpeningKind, Room, Wall, WallKind

logger = get_logger("aip.repair")

MIN_HABITABLE_HEIGHT = 2.75
ACCESSIBLE_DOOR_WIDTH = 0.90


def repair_plan(
    plan: FloorPlan, findings: list[Finding], brief: ClientBrief | None = None
) -> tuple[FloorPlan, list[str]]:
    """Apply every repair we know how to make. Returns a new plan and a log."""
    repaired = plan.clone()
    applied: list[str] = []

    handlers: dict[str, Callable[[FloorPlan, Finding], str | None]] = {
        "DAY.NO_GLAZING": _add_window,
        "DAY.UNDER_GLAZED": _enlarge_glazing,
        "DAY.LOW_DF": _enlarge_glazing,
        "DAY.OVERHEAT": _add_shading,
        "VENT.NONE": _add_window,
        "VENT.INSUFFICIENT": _enlarge_glazing,
        "VENT.NO_CROSS": _add_opposing_window,
        "ACC.DOOR_WIDTH": _widen_door,
        "ACC.CORRIDOR_WIDTH": None,          # needs a wall move; reported instead
        "CIRC.UNREACHABLE": _add_door,
        "NBC.3.4.3": _raise_ceiling,
    }

    for finding in findings:
        handler = handlers.get(finding.code)
        if handler is None:
            continue
        try:
            note = handler(repaired, finding)
        except Exception as exc:  # noqa: BLE001 - a failed repair must not abort the rest
            log_event(logger, "repair.failed", level=30, code=finding.code, error=str(exc))
            continue
        if note:
            applied.append(note)

    log_event(logger, "repair.applied", count=len(applied), considered=len(findings))
    return repaired, applied


# ---------------------------------------------------------------------------
# Individual repairs
# ---------------------------------------------------------------------------


def _locate(plan: FloorPlan, finding: Finding) -> tuple[Room | None, Level | None]:
    room = plan.room_by_id(finding.target_id)
    if room is None:
        return None, None
    return room, plan.level_at(room.level)


def _exterior_walls(level: Level, room: Room) -> list[Wall]:
    return [w for w in level.walls if room.id in w.rooms and w.kind is WallKind.EXTERIOR]


def _add_window(plan: FloorPlan, finding: Finding) -> str | None:
    """Give a room its first window."""
    room, level = _locate(plan, finding)
    if room is None or level is None:
        return None
    walls = _exterior_walls(level, room)
    if not walls:
        # Landlocked: the honest answer is that this needs a plan change.
        return None

    wall = max(walls, key=lambda w: w.length)
    required = max(room.area * 0.11, (room.area / 6) / 0.75)
    height = 0.75 if room.type.is_wet else 1.35
    width = min(max(0.6, wall.length - 0.6), max(0.6, required / height))
    wall.openings.append(
        Opening(
            kind=OpeningKind.VENTILATOR if room.type.is_wet else OpeningKind.WINDOW,
            wall_id=wall.id,
            position=0.5,
            width=round(width, 3),
            height=height,
            sill_height=1.8 if room.type.is_wet else 0.9,
        )
    )
    return f"Added a {width:.2f} x {height:.2f} m opening to {room.display_name()}"


def _enlarge_glazing(plan: FloorPlan, finding: Finding) -> str | None:
    """Grow existing windows until the statutory ratio is met."""
    room, level = _locate(plan, finding)
    if room is None or level is None:
        return None
    walls = _exterior_walls(level, room)
    glazed = [o for w in walls for o in w.openings if o.kind.is_glazed]
    if not glazed:
        return _add_window(plan, finding)

    target = max(room.area * 0.11, (room.area / 6) / 0.75)
    current = sum(o.area for o in glazed)
    if current >= target:
        return None

    scale = min(1.9, (target / current) ** 0.5)
    changed = False
    for wall in walls:
        for opening in wall.openings:
            if not opening.kind.is_glazed:
                continue
            max_width = max(0.6, wall.length - 0.6)
            new_width = min(max_width, opening.width * scale)
            new_height = min(2.1, opening.height * scale)
            if new_width > opening.width + 0.01 or new_height > opening.height + 0.01:
                opening.width = round(new_width, 3)
                opening.height = round(new_height, 3)
                # Keep the head below the ceiling.
                opening.sill_height = round(
                    min(opening.sill_height, max(0.0, room.ceiling_height - 0.3 - new_height)), 3
                )
                changed = True
    if not changed:
        return None
    after = sum(o.area for w in walls for o in w.openings if o.kind.is_glazed)
    return (
        f"Enlarged glazing in {room.display_name()} from "
        f"{current:.2f} to {after:.2f} m2"
    )


def _add_opposing_window(plan: FloorPlan, finding: Finding) -> str | None:
    """Create cross ventilation by opening a second, differently-facing wall."""
    from aip.engines.architecture.layout import _wall_direction

    room, level = _locate(plan, finding)
    if room is None or level is None:
        return None
    walls = _exterior_walls(level, room)
    if len(walls) < 2:
        return None

    existing = {
        _wall_direction(plan, w).bearing
        for w in walls
        if any(o.kind.is_glazed for o in w.openings)
    }
    if not existing:
        return _add_window(plan, finding)

    for wall in walls:
        if any(o.kind.is_glazed for o in wall.openings):
            continue
        bearing = _wall_direction(plan, wall).bearing
        if all(abs(((bearing - b) + 180) % 360 - 180) >= 80 for b in existing):
            height = 0.75 if room.type.is_wet else 1.2
            width = min(max(0.6, wall.length - 0.6), 1.2)
            wall.openings.append(
                Opening(
                    kind=OpeningKind.WINDOW,
                    wall_id=wall.id,
                    position=0.5,
                    width=round(width, 3),
                    height=height,
                    sill_height=0.9,
                )
            )
            return (
                f"Added an opposing window to {room.display_name()} to establish "
                f"cross ventilation"
            )
    return None


def _add_shading(plan: FloorPlan, finding: Finding) -> str | None:
    """Record a sun-shade on the room so the daylight metric credits it.

    The shading factor is metadata rather than geometry because a chajja is
    detailed at a later stage; what matters here is that the overheating
    penalty is correctly reduced and the requirement is carried forward.
    """
    room, _level = _locate(plan, finding)
    if room is None:
        return None
    current = float(room.metadata.get("shading_factor", 0.0))
    if current >= 0.7:
        return None
    room.metadata["shading_factor"] = 0.7
    room.metadata["shading_note"] = finding.remedy or "Add external shading to west glazing."
    return f"Specified external shading to {room.display_name()} (70% of glazing protected)"


def _widen_door(plan: FloorPlan, finding: Finding) -> str | None:
    for wall in plan.all_walls:
        for opening in wall.openings:
            if opening.id != finding.target_id:
                continue
            if opening.width >= ACCESSIBLE_DOOR_WIDTH:
                return None
            # Do not exceed the host wall.
            new_width = min(ACCESSIBLE_DOOR_WIDTH, max(0.6, wall.length - 0.3))
            if new_width <= opening.width + 0.01:
                return None
            before = opening.width
            opening.width = round(new_width, 3)
            return f"Widened a door from {before:.2f} to {opening.width:.2f} m"
    return None


def _add_door(plan: FloorPlan, finding: Finding) -> str | None:
    """Connect an unreachable room to the circulation network."""
    room, level = _locate(plan, finding)
    if room is None or level is None:
        return None

    connectivity = plan.connectivity(level.index)
    connected = {rid for rid, links in connectivity.items() if links}
    if not connected:
        connected = {r.id for r in level.rooms if r.id != room.id}

    from aip.engines.architecture.layout import _wall_between

    best: tuple[float, Wall, Room] | None = None
    for other in level.rooms:
        if other.id == room.id or other.id not in connected:
            continue
        edge = shared_edge(room.polygon, other.polygon)
        if edge is None:
            continue
        length = edge[0].distance_to(edge[1])
        if length < 0.9:
            continue
        # Uses the same T-junction-tolerant lookup as the generator, so a repair
        # is never blocked by the wall bookkeeping artefact described there.
        wall = _wall_between(level, room.id, other.id)
        if wall is None:
            continue
        # Prefer connecting through circulation space.
        priority = length * (2.0 if other.type.is_circulation else 1.0)
        if best is None or priority > best[0]:
            best = (priority, wall, other)

    if best is None:
        return None

    _priority, wall, other = best
    wall.openings.append(
        Opening(
            kind=OpeningKind.DOOR,
            wall_id=wall.id,
            position=0.5,
            width=0.9,
            height=2.1,
            sill_height=0.0,
            connects=(room.id, other.id),
        )
    )
    return f"Added a door connecting {room.display_name()} to {other.display_name()}"


def _raise_ceiling(plan: FloorPlan, finding: Finding) -> str | None:
    room, level = _locate(plan, finding)
    if room is None or level is None:
        return None
    if room.ceiling_height >= MIN_HABITABLE_HEIGHT:
        return None
    before = room.ceiling_height
    room.ceiling_height = MIN_HABITABLE_HEIGHT
    # The floor-to-floor must accommodate the new clear height plus structure.
    required = MIN_HABITABLE_HEIGHT + 0.4
    if level.floor_to_floor < required:
        level.floor_to_floor = round(required, 3)
    return (
        f"Raised the ceiling of {room.display_name()} from {before:.2f} to "
        f"{MIN_HABITABLE_HEIGHT:.2f} m"
    )
