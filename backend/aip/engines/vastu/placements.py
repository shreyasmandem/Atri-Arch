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


def _cells(env, north: float) -> dict[str, "Polygon"]:
    """The nine grid cells as polygons in plan coordinates (rotated with north)."""
    from shapely.affinity import rotate
    from shapely.geometry import box

    w, h = env.width, env.height
    out = {}
    for d, (col, row) in _CELL.items():
        x0 = env.min_x + col * w / 3
        y1 = env.max_y - row * h / 3
        out[d] = rotate(box(x0, y1 - h / 3, x0 + w / 3, y1), -north, origin=(env.min_x + w / 2, env.min_y + h / 2))
    return out


#: Rooms whose placement Vastu actually cares about, in order of weight.
_KEY = ("kitchen", "master_bedroom", "puja", "staircase", "bathroom", "toilet", "living", "dining",
        "bedroom", "guest_bedroom", "children_bedroom", "study", "utility", "foyer")


def placements(plan: FloorPlan, tradition_weight: float = 0.5) -> dict[str, Any]:
    """Every key room judged against the same grid the viewer draws.

    The zone a room is in is read from the drawn grid (where most of its floor
    falls), not from a compass bearing the client cannot see, so the label and
    the picture always agree. A misplaced room is offered a move only when the
    move makes sense: to its ideal cell, as a swap with whatever stands there.
    """
    from shapely.geometry import Polygon

    report = analyse_vastu(plan, tradition_weight)
    env = plan.envelope()
    north = float(plan.site.north_angle or 0.0)
    cells = _cells(env, north)
    bases, y = {}, PLINTH
    for lv in plan.levels:
        bases[lv.index] = round(y, 3)
        y += lv.floor_to_floor

    best_rule: dict[str, Any] = {}
    for v in report.verdicts:
        rule = RULES_BY_ID.get(v.rule_id)
        if not v.assessable or rule is None or rule.subject is None or not rule.ideal:
            continue
        if v.subject_id and (v.subject_id not in best_rule or best_rule[v.subject_id][0] < v.effective_weight):
            best_rule[v.subject_id] = (v.effective_weight, rule, v)

    rooms: list[dict[str, Any]] = []
    occupant: dict[tuple[int, str], dict[str, Any]] = {}
    for lv in plan.levels:
        for room in lv.rooms:
            if room.type.value not in _KEY or room.id not in best_rule or len(room.polygon) < 3:
                continue
            _, rule, v = best_rule[room.id]
            poly = Polygon([(p.x, p.y) for p in room.polygon]).buffer(0)
            share = {d: poly.intersection(c).area / max(poly.area, 1e-6) for d, c in cells.items()}
            zone = max(share, key=share.get)
            ideal = {d.cardinal.value for d in rule.ideal}
            bad = {d.cardinal.value for d in rule.prohibited}
            in_ideal = sum(share[d] for d in ideal if d in share)
            verdict = "ideal" if in_ideal >= 0.35 else "avoid" if zone in bad else "fair"
            target = None
            if verdict != "ideal":
                target = min((d for d in ideal if d in cells), key=lambda d: cells[d].centroid.distance(poly.centroid), default=None)
            r = {
                "id": room.id, "name": room.display_name(), "type": room.type.value, "level": lv.index,
                "polygon": [[round(p.x, 3), round(p.y, 3)] for p in room.polygon],
                "centre": [round(room.centre.x, 3), round(room.centre.y, 3)],
                "zone": zone, "verdict": verdict, "ideal": sorted(ideal), "avoid": sorted(bad),
                "rule": v.title, "why": v.traditional_rationale or v.modern_rationale, "remedy": rule.remedy,
                "target": target, "swap": None,
            }
            rooms.append(r)
            occupant.setdefault((lv.index, zone), r)
    for r in rooms:
        t = r["target"]
        if not t:
            continue
        other = occupant.get((r["level"], t))
        if other and other is not r:
            # A swap is only worth suggesting if it does not ruin the other room.
            fits = r["zone"] in other["ideal"] or other["verdict"] != "ideal"
            r["swap"] = other["name"] if fits else None
            if not fits:
                r["target"] = None
        c = cells[t].centroid if r["target"] else None
        r["target_point"] = [round(c.x, 3), round(c.y, 3)] if c is not None else None

    return {
        "score": report.score, "grade": report.grade, "summary": report.summary, "north_angle": north,
        "envelope": [round(env.min_x, 3), round(env.min_y, 3), round(env.max_x, 3), round(env.max_y, 3)],
        "zones": [{"dir": d, **z, "polygon": [[round(x, 3), round(y, 3)] for x, y in list(cells[d].exterior.coords)[:-1]],
                   "point": [round(cells[d].centroid.x, 3), round(cells[d].centroid.y, 3)]} for d, z in ZONES.items()],
        "levels": [{"index": i, "base": b} for i, b in bases.items()],
        "rooms": rooms,
    }
