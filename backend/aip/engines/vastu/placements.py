"""Vastu placements in three dimensions: the zones, and where each room sits.

The report says "the kitchen is in the north-east, which is prohibited". This
turns that into geometry the 3D viewer can draw over the model: the nine-cell
directional grid laid on each floor, every assessed room with its verdict,
and for a room in the wrong quarter, the point in the right one it belongs.
"""

from __future__ import annotations

import math
from typing import Any

from aip.domain.geometry import Direction
from aip.domain.plan import FloorPlan
from aip.engines.vastu.engine import analyse_vastu
from aip.engines.vastu.knowledge import RULES_BY_ID

#: The eight quarters and the centre: guardian, element and the classical tint.
ZONES: dict[str, dict[str, str]] = {
    "N": {"name": "Uttara", "deity": "Kubera", "element": "Water", "colour": "#5b8fb0"},
    "NE": {"name": "Ishanya", "deity": "Ishana", "element": "Water", "colour": "#7fb3c9"},
    "E": {"name": "Purva", "deity": "Indra", "element": "Air", "colour": "#8fb27a"},
    "SE": {"name": "Agneya", "deity": "Agni", "element": "Fire", "colour": "#d9824a"},
    "S": {"name": "Dakshina", "deity": "Yama", "element": "Earth", "colour": "#b85f45"},
    "SW": {"name": "Nairutya", "deity": "Nirriti", "element": "Earth", "colour": "#a07a52"},
    "W": {"name": "Paschima", "deity": "Varuna", "element": "Space", "colour": "#8a8fb8"},
    "NW": {"name": "Vayavya", "deity": "Vayu", "element": "Air", "colour": "#b9b6a8"},
    "CENTRE": {"name": "Brahmasthan", "deity": "Brahma", "element": "Space", "colour": "#e8dcc6"},
}

#: Grid cell (column, row from the north) of each quarter.
_CELL = {"NW": (0, 0), "N": (1, 0), "NE": (2, 0), "W": (0, 1), "CENTRE": (1, 1), "E": (2, 1),
         "SW": (0, 2), "S": (1, 2), "SE": (2, 2)}

PLINTH = 0.45


def _cell_point(direction: str, centre: tuple[float, float], w: float, h: float, north: float) -> tuple[float, float]:
    """The middle of a quarter's cell, in plan coordinates."""
    col, row = _CELL.get(direction, (1, 1))
    dx, dy = (col - 1) * w / 3, (1 - row) * h / 3
    a = math.radians(-north)
    return (round(centre[0] + dx * math.cos(a) - dy * math.sin(a), 3),
            round(centre[1] + dx * math.sin(a) + dy * math.cos(a), 3))


def placements(plan: FloorPlan, tradition_weight: float = 0.5) -> dict[str, Any]:
    report = analyse_vastu(plan, tradition_weight)
    env = plan.envelope()
    centre = (plan.centre.x, plan.centre.y)
    north = float(plan.site.north_angle or 0.0)
    by_id = {r.id: (lv, r) for lv in plan.levels for r in lv.rooms}

    bases, y = {}, PLINTH
    for lv in plan.levels:
        bases[lv.index] = round(y, 3)
        y += lv.floor_to_floor

    rooms: dict[str, dict[str, Any]] = {}
    for v in report.verdicts:
        if not v.assessable or v.subject_id not in by_id:
            continue
        lv, room = by_id[v.subject_id]
        rule = RULES_BY_ID.get(v.rule_id)
        if rule is None or rule.subject is None:
            continue
        prev = rooms.get(room.id)
        # One pin per room: its weightiest placement rule.
        if prev and prev["weight"] >= v.effective_weight:
            continue
        ideal = [d.value for d in sorted(rule.ideal, key=lambda d: d.bearing)]
        # The quarter to point at: an ideal that is one of the eight, else the
        # eight-point quarter most of the ideals collapse to.
        eights = [d.cardinal.value for d in rule.ideal]
        target = next((d for d in ideal if d in _CELL), max(set(eights), key=eights.count) if eights else None)
        rooms[room.id] = {
            "id": room.id, "name": room.display_name(), "level": lv.index,
            "centre": [round(room.centre.x, 3), round(room.centre.y, 3)],
            "polygon": [[round(p.x, 3), round(p.y, 3)] for p in room.polygon],
            "area": round(room.area, 1),
            "direction": v.observed_direction,
            "zone": Direction(v.observed_direction).cardinal.value if v.observed_direction in Direction.__members__ else None, "verdict": v.verdict, "compliance": round(v.compliance, 2),
            "ideal": ideal, "acceptable": [d.value for d in rule.acceptable],
            "prohibited": [d.value for d in rule.prohibited],
            "rule": v.title, "why": v.traditional_rationale or v.modern_rationale,
            "remedy": rule.remedy, "weight": v.effective_weight,
            "ideal_zone": target,
            "ideal_point": _cell_point(target, centre, env.width, env.height, north) if target and v.verdict != "ideal" else None,
        }
    return {
        "score": report.score, "grade": report.grade, "summary": report.summary,
        "centre": [round(centre[0], 3), round(centre[1], 3)], "north_angle": north,
        "envelope": [round(env.min_x, 3), round(env.min_y, 3), round(env.max_x, 3), round(env.max_y, 3)],
        "zones": [{"dir": d, **z, "point": _cell_point(d, centre, env.width, env.height, north)} for d, z in ZONES.items()],
        "levels": [{"index": i, "base": b} for i, b in bases.items()],
        "rooms": sorted(rooms.values(), key=lambda r: (r["level"], -r["weight"])),
        "directions": [d.value for d in Direction if d.value != "CENTRE"],
    }
