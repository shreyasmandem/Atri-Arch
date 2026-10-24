"""Direct edits to a finished plan.

A design is rarely right at the first draw: the client wants the kitchen a
little wider, the study where the bedroom is, a double-height living room. The
edits here change the drawn rooms themselves - not the brief - so everything
that was not touched stays exactly where it was.

Every room is a rectangle, so an edit is one of a few exact moves:

* **resize** - a wall slides. The room grows and the room across the wall
  gives the depth up (or the reverse), or an outside wall steps into the
  setback. Everything that stands on the same line moves with it, so no
  room is ever left with a bent wall; if the line is not clean the edit is
  refused with the reason, rather than guessed at.
* **swap** - two rooms on one floor exchange places.
* **retype / rename** - a room becomes a study, or is called "Gaming Room".
* **ceiling** - a room's ceiling height.

After the rooms change, walls, stairs, the column grid, doors and windows are
rebuilt by the same code that drew the scheme, so the result is a complete plan.
"""

from __future__ import annotations

import uuid
from typing import Any

from aip.domain.geometry import BoundingBox, Vec2, bounding_box, rectangle
from aip.domain.plan import FloorPlan, Room, RoomType

T = RoomType

#: Rooms whose shape is fixed by something else (the stair stacks through floors).
FROZEN = {T.STAIRCASE, T.SHAFT}
#: The narrowest side a room of this kind may be left with.
MIN_SIDE: dict[RoomType, float] = {
    T.BATHROOM: 1.2, T.TOILET: 1.0, T.POWDER: 1.0, T.STORE: 1.1, T.PUJA: 1.1, T.UTILITY: 1.1,
    T.PANTRY: 1.1, T.LAUNDRY: 1.1, T.WARDROBE: 1.0, T.CORRIDOR: 1.0, T.LOBBY: 1.0, T.FOYER: 1.2,
    T.BALCONY: 1.0, T.TERRACE: 1.5, T.VERANDAH: 1.2, T.GARAGE: 2.4, T.KITCHEN: 1.8,
}
DEFAULT_MIN_SIDE = 2.2
#: Rooms that give up depth most readily, then those that mind it.
DONOR_ORDER: dict[RoomType, float] = {
    T.TERRACE: 0.0, T.BALCONY: 0.0, T.STORE: 0.5, T.CORRIDOR: 1.0, T.LOBBY: 1.0, T.UTILITY: 1.5,
    T.PANTRY: 1.5, T.FOYER: 1.5, T.VERANDAH: 1.0, T.WARDROBE: 1.5, T.LAUNDRY: 1.5,
}
TOL = 0.06
MAX_STEP = 3.0
CEILING_RANGE = (2.4, 4.5)
LINKS = ("suite_of", "enter_from", "common")


class EditError(ValueError):
    """An edit that cannot be made, with the reason a client can act on."""


def _label(room: Room) -> str:
    return room.display_name()


def _min_side(room: Room) -> float:
    return MIN_SIDE.get(room.type, DEFAULT_MIN_SIDE)


def _rect(room: Room) -> tuple[float, float, float, float]:
    b = room.bbox
    return b.min_x, b.min_y, b.max_x, b.max_y


def _set_rect(room: Room, r: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = r
    room.polygon = rectangle(Vec2(x0, y0), x1 - x0, y1 - y0)
    room.metadata["_c"] = (x0, y0, x1, y1)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 1e-3 and h > 1e-3 else 0.0


def _span(r: tuple[float, float, float, float], axis: str) -> tuple[float, float]:
    """The extent of a rectangle along the line a wall on `axis` runs."""
    return (r[1], r[3]) if axis == "x" else (r[0], r[2])


def _slide(
    level_rooms: list[Room], room: Room, edge: str, delta: float, bounds: BoundingBox,
) -> dict[str, tuple[float, float, float, float]]:
    """Move one wall of `room` outward by `delta` (inward when negative).

    Returns the new rectangle of every room that changes, or raises EditError.
    """
    axis = "x" if edge in ("e", "w") else "y"
    out = 1.0 if edge in ("e", "n") else -1.0
    r0 = _rect(room)
    idx = (2 if edge == "e" else 0) if axis == "x" else (3 if edge == "n" else 1)
    line = r0[idx]
    shift = out * delta
    lo_idx, hi_idx = (2, 0) if axis == "x" else (3, 1)       # the side above a line starts at hi_idx

    low: dict[str, Room] = {}       # rooms ending on the line
    high: dict[str, Room] = {}      # rooms starting on the line
    (low if out > 0 else high)[room.id] = room
    a, b = _span(r0, axis)
    changed = True
    while changed:
        changed = False
        for other in level_rooms:
            if other.id in low or other.id in high:
                continue
            r = _rect(other)
            s0, s1 = _span(r, axis)
            if min(b, s1) - max(a, s0) < TOL:
                continue
            if abs(r[lo_idx] - line) < TOL:
                low[other.id] = other
            elif abs(r[hi_idx] - line) < TOL:
                high[other.id] = other
            else:
                continue
            a, b = min(a, s0), max(b, s1)
            changed = True
        # Rooms on one side may reach past the other side's rooms: pull in
        # the opposite side over the widened stretch until nothing changes.

    members = list(low.values()) + list(high.values())
    for m in members:
        if m.type in FROZEN:
            raise EditError(f"The {_label(m)} is fixed (the stair runs through every floor), so that wall cannot move.")

    # A clean line: what ends on it spans exactly what starts on it. If only one
    # side has rooms, it is an outside wall and only this room steps out.
    def extent(rooms: dict[str, Room]) -> tuple[float, float]:
        spans = [_span(_rect(m), axis) for m in rooms.values()]
        return min(s[0] for s in spans), max(s[1] for s in spans)

    new: dict[str, tuple[float, float, float, float]] = {}
    exterior = not (low and high)
    if exterior:
        if delta < 0:
            raise EditError(
                f"The {_label(room)} cannot shrink from its outside wall without leaving a gap; "
                f"it can give the depth to a room it shares a wall with.")
        movers = [room]
    else:
        lo_e, hi_e = extent(low), extent(high)
        if abs(lo_e[0] - hi_e[0]) > TOL or abs(lo_e[1] - hi_e[1]) > TOL:
            raise EditError(
                f"That wall of the {_label(room)} is shared by rooms that do not line up, "
                f"so it cannot slide cleanly. Try another side, or swap rooms instead.")
        movers = members
    for m in movers:
        r = list(_rect(m))
        if axis == "x":
            if m.id in low or (exterior and m is room and edge == "e"):
                r[2] += shift
            else:
                r[0] += shift
        else:
            if m.id in low or (exterior and m is room and edge == "n"):
                r[3] += shift
            else:
                r[1] += shift
        new[m.id] = (r[0], r[1], r[2], r[3])

    # Whatever moved must still be a room, inside the buildable land, and clear of the rest.
    for m in movers:
        x0, y0, x1, y1 = new[m.id]
        if min(x1 - x0, y1 - y0) < _min_side(m) - 1e-6:
            raise EditError(
                f"The {_label(m)} would be only {min(x1 - x0, y1 - y0):.1f} m across; "
                f"a {m.type.label.lower()} needs at least {_min_side(m):.1f} m.")
        if x0 < bounds.min_x - 1e-6 or y0 < bounds.min_y - 1e-6 or x1 > bounds.max_x + 1e-6 or y1 > bounds.max_y + 1e-6:
            raise EditError("That would take the room past the setback line the plot allows.")
    for m in movers:
        for other in level_rooms:
            if other.id not in new and other.id != m.id and _overlap(new[m.id], _rect(other)) > 0.02:
                raise EditError(f"That would run the {_label(m)} into the {_label(other)}.")
    return new


def _donor_cost(changes: dict[str, Any], room: Room, rooms: dict[str, Room]) -> float:
    """How much a slide takes from rooms that mind: low is a gentle edit."""
    cost = 0.0
    for rid, new in changes.items():
        if rid == room.id:
            continue
        other = rooms[rid]
        x0, y0, x1, y1 = _rect(other)
        shrink = (x1 - x0) * (y1 - y0) - (new[2] - new[0]) * (new[3] - new[1])
        cost += (DONOR_ORDER.get(other.type, 3.0) + 0.1) * max(0.0, shrink) + 0.01 * len(changes)
    return cost


def _resize(plan: FloorPlan, room: Room, op: dict[str, Any], bounds: BoundingBox) -> tuple[str, int]:
    level = next(lv for lv in plan.levels if room in lv.rooms)
    by_id = {r.id: r for r in level.rooms}
    done: list[str] = []
    for key, edges, unit in (("width", ("e", "w"), "wider"), ("depth", ("n", "s"), "deeper")):
        try:
            d = float(op.get(key) or 0.0)
        except (TypeError, ValueError) as exc:
            raise EditError(f"{key} must be a number of metres") from exc
        if abs(d) < 1e-6:
            continue
        d = max(-MAX_STEP, min(MAX_STEP, d))
        best: tuple[float, dict[str, Any]] | None = None
        errors: list[str] = []
        for edge in edges:
            try:
                changes = _slide(level.rooms, room, edge, d, bounds)
            except EditError as exc:
                errors.append(str(exc))
                continue
            cost = _donor_cost(changes, room, by_id)
            if best is None or cost < best[0]:
                best = (cost, changes)
        if best is None:
            raise EditError(errors[0] if errors else "That edit does not fit.")
        for rid, r in best[1].items():
            _set_rect(by_id[rid], r)
        took = sorted({_label(by_id[rid]) for rid in best[1] if rid != room.id})
        verb = unit if d > 0 else unit.replace("wider", "narrower").replace("deeper", "shallower")
        done.append(f"{abs(d):.1f} m {verb}" + (f" (with the {', '.join(took)})" if took else " (into the setback)"))
    if not done:
        raise EditError("Nothing to change: give a width or depth change in metres.")
    return f"{_label(room)}: " + ", ".join(done), level.index


def _swap(plan: FloorPlan, a: Room, b: Room) -> tuple[str, int]:
    la = next(lv for lv in plan.levels if a in lv.rooms)
    lb = next(lv for lv in plan.levels if b in lv.rooms)
    if la is not lb:
        raise EditError("Rooms can be swapped when they are on the same floor.")
    for r in (a, b):
        if r.type in FROZEN:
            raise EditError(f"The {_label(r)} cannot move: the stair stacks through every floor.")
    ra, rb = _rect(a), _rect(b)
    _set_rect(a, rb)
    _set_rect(b, ra)
    ids = {a.id, b.id}
    for r in la.rooms:
        for k in LINKS:
            if k in r.metadata and (r in (a, b) or r.metadata.get(k) in ids):
                r.metadata.pop(k, None)
    return f"{_label(a)} and {_label(b)} exchanged places", la.index


def _find(rooms: dict[str, Room], key: Any, what: str = "room") -> Room:
    r = rooms.get(str(key))
    if r is None:
        raise EditError(f"There is no {what} with that id in this plan.")
    return r


def apply_edits(plan: FloorPlan, ops: list[dict[str, Any]]) -> tuple[FloorPlan, list[str], list[str]]:
    """Apply `ops` to a copy of `plan`. Returns (plan, what was done, what was refused)."""
    from aip.domain.brief import ClientBrief, RoomRequirement, VastuStance
    from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator

    new = plan.model_copy(deep=True)
    new.id = f"plan_{uuid.uuid4().hex[:10]}"
    rooms = {r.id: r for lv in new.levels for r in lv.rooms}

    reqs = [RoomRequirement(type=r.type, preferred_area=round(max(r.area, 1.0), 2),
                            needs_daylight=r.type.is_habitable) for r in rooms.values()]
    brief = ClientBrief(project_name=new.name, site=new.site, levels=len(new.levels), requirements=reqs,
                        vastu=VastuStance.BALANCED)
    gen = LayoutGenerator(brief, GeneratorConfig(population=4, generations=1, seed=1, check_feasibility=False))
    house = bounding_box([p for r in rooms.values() for p in r.polygon])
    land = gen._site_box() or new.site.bbox
    # Rooms may step out to the buildable line, never past it, and never back
    # into what an earlier floor already stands on being wider than that.
    bounds = BoundingBox(min(land.min_x, house.min_x), min(land.min_y, house.min_y),
                         max(land.max_x, house.max_x), max(land.max_y, house.max_y))

    applied: list[str] = []
    refused: list[str] = []
    geometry_changed = False
    for op in (ops or [])[:16]:
        try:
            kind = str(op.get("op", "")).lower()
            if kind == "resize":
                msg, _ = _resize(new, _find(rooms, op.get("room")), op, bounds)
                geometry_changed = True
            elif kind == "swap":
                msg, _ = _swap(new, _find(rooms, op.get("a")), _find(rooms, op.get("b")))
                geometry_changed = True
            elif kind == "rename":
                room = _find(rooms, op.get("room"))
                name = " ".join(str(op.get("name", "")).split())[:40]
                if not name:
                    raise EditError("Give the room a name.")
                old = _label(room)
                room.name = name
                msg = f"{old} renamed {name}"
            elif kind == "retype":
                room = _find(rooms, op.get("room"))
                try:
                    kind_to = RoomType(str(op.get("type", "")).lower())
                except ValueError as exc:
                    raise EditError("That kind of room is not known.") from exc
                if room.type in FROZEN or kind_to in FROZEN:
                    raise EditError("The staircase cannot be changed into, or out of, another room.")
                old = _label(room)
                room.type = kind_to
                room.name = " ".join(str(op.get("name") or kind_to.label).split())[:40]
                msg = f"{old} is now a {room.name}"
                geometry_changed = True          # doors and windows follow what a room is
            elif kind == "ceiling":
                h = float(op.get("height"))
                if not CEILING_RANGE[0] <= h <= CEILING_RANGE[1]:
                    raise EditError(f"Ceiling heights run from {CEILING_RANGE[0]} to {CEILING_RANGE[1]} m.")
                if op.get("room"):
                    targets = [_find(rooms, op.get("room"))]
                else:
                    li = int(op.get("level", 0))
                    lvl = next((lv for lv in new.levels if lv.index == li), None)
                    if lvl is None:
                        raise EditError("That floor does not exist.")
                    targets = [r for r in lvl.rooms if not r.type.is_outdoor]
                for r in targets:
                    lvl_of = next(lv for lv in new.levels if r in lv.rooms)
                    room_cap = _ceiling_cap(new, lvl_of)
                    if h > room_cap + 1e-6:
                        raise EditError(
                            f"The {_label(r)} has another floor over it, so its ceiling can be at most "
                            f"{room_cap:.2f} m (the floor-to-floor less the slab).")
                for r in targets:
                    r.ceiling_height = round(h, 2)
                msg = (f"{_label(targets[0])}" if len(targets) == 1 else f"{len(targets)} rooms") + f" ceiling {h:.2f} m"
            elif kind == "pool":
                # The garden pool: where it goes, what kind, or none at all.
                from aip.engines.experience.landscape import POOL_NAMES, POOL_PLACES, POOLS, pool_placement

                want_kind = str(op.get("kind", new.site.pool) or "").lower()
                want_place = str(op.get("place", new.site.pool_place or "rear") or "rear").lower()
                if want_kind not in ("", "none") and want_kind not in POOLS:
                    raise EditError("That kind of pool is not known.")
                if want_place not in POOL_PLACES:
                    raise EditError("That is not a place a pool can go.")
                new.site.pool = "" if want_kind in ("", "none") else want_kind
                new.site.pool_place = "" if want_place == "rear" else want_place
                if not new.site.pool:
                    msg = "Pool removed"
                else:
                    placed = pool_placement(new)
                    if placed is None:
                        raise EditError(
                            f"A {POOL_NAMES[new.site.pool]} does not fit: the house leaves too little open ground "
                            "round it. A smaller pool may fit, or ask for more lawn in the brief.")
                    _rect, got_kind, got_place = placed
                    if got_kind != new.site.pool:
                        # A smaller pool than the one picked is a different choice: offer it, do not make it.
                        raise EditError(
                            f"A {POOL_NAMES[new.site.pool]} does not fit round this house; "
                            f"a {POOL_NAMES[got_kind]} would.")
                    if "place" in op and got_place != want_place:
                        # Say so rather than quietly putting it somewhere else.
                        raise EditError(
                            f"There is no room {POOL_PLACES[want_place][0].lower()}{POOL_PLACES[want_place][1:].split(',')[0]} "
                            f"for a {POOL_NAMES[got_kind]}; the open ground there is too narrow.")
                    # Where it went is where the plan says it is, so the controls show the truth.
                    new.site.pool_place = "" if got_place == "rear" else got_place
                    msg = f"{POOL_NAMES[got_kind].capitalize()} {POOL_PLACES[got_place][0].lower()}{POOL_PLACES[got_place][1:]}"
            else:
                raise EditError(f"Unknown edit {kind!r}.")
            applied.append(msg)
        except EditError as exc:
            refused.append(str(exc))
        except (TypeError, ValueError, KeyError) as exc:
            refused.append(f"That edit could not be read ({exc}).")

    if not applied:
        return plan, [], refused

    if geometry_changed:
        env = bounding_box([p for r in rooms.values() for p in r.polygon])
        # A room stepped into the setback leaves the house no longer a rectangle: a wall
        # with a room on one side only is an outside wall (with its windows), as when
        # the scheme was drawn, not a partition because it falls short of the bounding box.
        gen._open_outline = True
        for lv in new.levels:
            lv.walls = gen._build_walls(lv.rooms, env, lv.index)
            lv.staircases = gen._build_stairs(lv.rooms, lv.index)
        new.column_grid = gen._build_column_grid(env)
        gen._place_openings(new, env, repair=False)
    new.metadata = {**new.metadata, "edited_from": plan.id, "edits": applied}
    new.name = plan.name if plan.name.endswith("(edited)") else f"{plan.name} (edited)"
    return new, applied, refused


def _ceiling_cap(plan: FloorPlan, level) -> float:
    """How high a ceiling on this floor can go: the top floor is open to the
    roof; any other has a floor over it, so the floor-to-floor less the slab."""
    top = max(lv.index for lv in plan.levels)
    return CEILING_RANGE[1] if level.index == top else level.floor_to_floor - 0.15


def describe_rooms(plan: FloorPlan) -> list[dict[str, Any]]:
    """What the editor lets a client pick from, floor by floor."""
    out = []
    for lv in plan.levels:
        cap = round(_ceiling_cap(plan, lv), 2)
        for r in lv.rooms:
            b = r.bbox
            out.append({
                "id": r.id, "name": r.display_name(), "type": r.type.value, "level": lv.index,
                "width": round(b.width, 2), "depth": round(b.height, 2), "area": round(r.area, 1),
                "ceiling": round(r.ceiling_height, 2), "ceiling_max": cap, "fixed": r.type in FROZEN,
            })
    return out


__all__ = ["apply_edits", "describe_rooms", "EditError"]
