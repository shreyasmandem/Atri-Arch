"""Facade design languages: the same plan, dressed as genuinely different houses.

A house is more than its plan's walls extruded. What makes two houses on the
same street look nothing alike is the facade's language: timber fins or a
deep projecting frame around the upper floor, a jaali screen shading the
west, a planted wall, a mono-pitch roof with a clerestory, a stone base and a
plaster top, a vernacular hip roof on timber posts. Each language here is a
set of elements laid over the plan's own envelope, driven by where the road
and the hard sun are, so the result is specific to the house rather than a
skin pasted on.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from aip.domain.geometry import Vec2
from aip.domain.plan import FloorPlan

DESIGNS: dict[str, dict[str, Any]] = {
    "fins": {"name": "Timber Fins", "story": "Vertical timber fins screen the street face of the upper floor; a dark band caps it.",
             "styles": {"tropical_modern", "contemporary", "biophilic", "japandi", "modern_minimal"}},
    "frame": {"name": "Deep Frame", "story": "A bold projecting frame wraps the upper floor's street face, shading its glass.",
              "styles": {"contemporary", "modern_minimal", "industrial", "mid_century_modern"}},
    "jaali": {"name": "Jaali Screen", "story": "Lattice screens filter the hard west and south sun, as a haveli would.",
              "styles": {"traditional_indian", "rajasthani_haveli", "indo_saracenic", "chettinad", "contemporary"}},
    "pitch": {"name": "Mono-pitch", "story": "A single sloping roof rises to a clerestory band that lets light deep inside.",
              "styles": {"scandinavian", "contemporary", "modern_minimal", "japandi"}},
    "twotone": {"name": "Stone Base", "story": "A stone-clad ground floor, a light plaster top and a deep cornice at each floor.",
                "styles": {"contemporary", "indo_saracenic", "mid_century_modern", "industrial", "chettinad"}},
    "vernacular": {"name": "Vernacular", "story": "A tiled hip roof on wide eaves and timber posts along a front verandah.",
                   "styles": {"kerala_vernacular", "traditional_indian", "chettinad"}},
}


def ranked_designs(plan: FloorPlan) -> list[str]:
    """Designs in the order to offer them: style matches first, then the rest,
    each group shuffled by the plan so two plans rarely open on the same one."""
    style = plan.style or "contemporary"
    seed = int(hashlib.sha1(plan.id.encode()).hexdigest()[:8], 16)
    keys = list(DESIGNS)
    match = [k for k in keys if style in DESIGNS[k]["styles"]]
    rest = [k for k in keys if k not in match]
    rot = lambda xs: xs[seed % len(xs):] + xs[:seed % len(xs)] if xs else xs  # noqa: E731
    return rot(match) + rot(rest)


def choose(plan: FloorPlan, design_id: str | None) -> str:
    return design_id if design_id in DESIGNS else ranked_designs(plan)[0]


@dataclass(slots=True)
class Edge:
    a: Vec2
    c: Vec2
    out: Vec2

    @property
    def length(self) -> float:
        return (self.c - self.a).length

    @property
    def dir(self) -> Vec2:
        return (self.c - self.a).normalised()

    def at(self, t: float, off: float = 0.0) -> Vec2:
        return self.a + (self.c - self.a) * t + self.out * off


def edges(footprint) -> list[Edge]:
    """The footprint's outline as edges with outward normals."""
    from shapely.geometry.polygon import orient

    if footprint is None or footprint.is_empty:
        return []
    if footprint.geom_type == "MultiPolygon":
        footprint = max(footprint.geoms, key=lambda g: g.area)
    ring = list(orient(footprint.simplify(0.05), 1.0).exterior.coords)
    out = []
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        d = Vec2(x1 - x0, y1 - y0)
        if d.length < 0.6:
            continue
        u = d.normalised()
        out.append(Edge(Vec2(x0, y0), Vec2(x1, y1), Vec2(u.y, -u.x)))
    return out


def _box(b, node, mat, p: Vec2, y: float, size, yaw: float) -> None:
    b.box(node, mat, (p.x, y, -p.y), size, yaw)


def _yaw(e: Edge) -> float:
    return math.atan2(e.dir.y, e.dir.x)


#: Unit vector toward the afternoon sun (west) and the hard south, in plan coordinates.
def _hot(e: Edge, north: float) -> bool:
    a = math.radians(-north)
    west = Vec2(-math.cos(a), -math.sin(a))
    south = Vec2(math.sin(a), -math.cos(a))
    return e.out.dot(west) > 0.6 or e.out.dot(south) > 0.6


def apply(b, plan: FloorPlan, design: str, levels: list[tuple[Any, float, Any]], road: Vec2 | None,
          roof_y: float) -> dict[str, Any]:
    """Lay the design's elements over the house. `levels` is (level, base y, footprint).

    Returns overrides for the builder: whether the roof should be hip or a
    mono-pitch, so the roof the design needs replaces the default.
    """
    from aip.engines.experience.exteriors import _free, clear, door_spans

    north = float(plan.site.north_angle or 0.0)
    street = lambda e: road is not None and e.out.dot(road) > 0.6  # noqa: E731
    n = len(levels)
    over: dict[str, Any] = {}
    for li, (level, base, fp) in enumerate(levels):
        h = level.floor_to_floor
        es = edges(fp)
        upper = li >= 1 or n == 1
        node = f"level_{level.index}/facade"
        for e in es:
            L, yaw = e.length, _yaw(e)
            spans = door_spans(level, e)          # nothing stands in a doorway
            if design == "fins" and upper and street(e):
                k = max(3, int(L / 0.5))
                for i in range(k):
                    if _free((i + 0.5) / k, 0.05 / L, spans):
                        _box(b, node, "timber", e.at((i + 0.5) / k, 0.2), base + h / 2, (0.06, h - 0.1, 0.36), yaw)
                _box(b, node, "frame", e.at(0.5, 0.18), base + h - 0.12, (L + 0.3, 0.24, 0.42), yaw)
            elif design == "frame" and upper and street(e):
                d = 0.75
                for y in ((base + h - 0.1,) if li == 0 else (base + 0.05, base + h - 0.1)):
                    _box(b, node, "clad", e.at(0.5, d / 2), y, (L + 0.5, 0.22, d), yaw)
                for t in (0.0, 1.0):
                    _box(b, node, "clad", e.at(t, d / 2) + e.dir * (0.25 if t == 0 else -0.25) * -1, base + h / 2, (0.22, h, d), yaw)
            elif design == "jaali" and li >= 0 and _hot(e, north) and L > 2.0:
                rows = int((h - 0.6) / 0.22)
                for t0, t1 in clear(0.225, 0.775, spans):
                    w = (t1 - t0) * L
                    if w < 0.8:
                        continue
                    s0 = e.at((t0 + t1) / 2, 0.32)
                    cols = max(2, int(w / 0.22))
                    for i in range(cols + 1):
                        p = s0 + e.dir * (-w / 2 + i * w / cols)
                        _box(b, node, "joinery", p, base + 0.3 + (h - 0.6) / 2, (0.04, h - 0.6, 0.05), yaw)
                    for j in range(rows + 1):
                        _box(b, node, "joinery", s0, base + 0.3 + j * (h - 0.6) / rows, (w, 0.04, 0.05), yaw)
                    _box(b, node, "frame", s0, base + h - 0.25, (w + 0.2, 0.08, 0.4), yaw)
            elif False and design == "garden" and li == min(1, n - 1) and not street(e) and L == max(x.length for x in es if not street(x)):
                w = L * 0.6
                p = e.at(0.5, 0.1)
                _box(b, node, "leaf", p, base + h * 0.5, (w, h * 0.85, 0.1), yaw)
                for i in range(int(w / 0.35)):
                    for j in range(int(h * 0.85 / 0.35)):
                        if (i * 7 + j * 3) % 4 == 0:
                            q = p + e.dir * (-w / 2 + 0.2 + i * 0.35) + e.out * 0.08
                            b.blob(node, "leaf2", (q.x, base + h * 0.075 + 0.2 + j * 0.35, -q.y), 0.17)
            elif design == "twotone":
                if li == 0:
                    # Stone cladding between the openings, never over a door or window.
                    for t0, t1 in clear(0.0, 1.0, door_spans(level, e, 0.05, windows=True)):
                        _box(b, node, "clad", e.at((t0 + t1) / 2, 0.03), base + h / 2 - 0.05, ((t1 - t0) * L + 0.03, h - 0.1, 0.06), yaw)
                _box(b, node, "slab", e.at(0.5, 0.12), base + h - 0.05, (L + 0.24, 0.26, 0.26), yaw)
            elif design == "vernacular" and li == 0 and street(e) and L > 3.0:
                k = max(2, int(L / 2.4))
                for i in range(k + 1):
                    t = i / k
                    if not _free(t, 0.15 / L, spans):
                        # A post that would stand in front of a door steps aside.
                        t = min((a for a, _b in spans if a > 0), key=lambda a: abs(a - t), default=t)
                    p = e.at(t, 1.6)
                    b.cylinder(node, "timber", (p.x, base, -p.y), 0.1, h - 0.15, 12)
                    _box(b, node, "sill", p, base - 0.02, (0.4, 0.06, 0.4), yaw)
                _box(b, node, "timber", e.at(0.5, 1.6), base + h - 0.2, (L + 0.2, 0.2, 0.18), yaw)
                pts = [e.at(0, 0), e.at(1, 0), e.at(1, 1.9), e.at(0, 1.9)]
                b.slab(node, "roof_tile", pts, base + h - 0.12, base + h - 0.02)
            if False:
                # Planters on the parapet line.
                for i in range(max(1, int(L / 1.6))):
                    p = e.at((i + 0.5) / max(1, int(L / 1.6)), -0.35)
                    _box(b, "roof", "clad", p, roof_y + 0.2, (1.1, 0.4, 0.4), yaw)
                    b.blob("roof", "leaf", (p.x, roof_y + 0.55, -p.y), 0.32)
    if design == "vernacular":
        over["roof"] = "hip"
    elif design == "pitch":
        over["roof"] = "pitch"
    elif design in {"fins", "frame", "twotone", "jaali"}:
        over["roof"] = "flat"
    return over


def pitch_roof(b, footprint, y: float, road: Vec2 | None) -> None:
    """A mono-pitch roof: low at the street, high at the back, over a glazed clerestory."""
    from shapely.geometry import Polygon  # noqa: F401 - footprint is shapely

    if footprint is None or footprint.is_empty:
        return
    x0, y0, x1, y1 = footprint.bounds
    eave = 0.6
    x0, y0, x1, y1 = x0 - eave, y0 - eave, x1 + eave, y1 + eave
    along_y = road is None or abs(road.y) >= abs(road.x)
    low_at_min = road is not None and (road.y < 0 if along_y else road.x < 0)
    span = (y1 - y0) if along_y else (x1 - x0)
    rise = max(0.9, span * 0.16)
    lo, hi = y + 0.15, y + 0.15 + rise
    def h(px, py):
        t = ((py - y0) / span) if along_y else ((px - x0) / span)
        t = t if low_at_min else 1 - t
        return lo + (hi - lo) * t
    P = lambda px, py, dy=0.0: (px, h(px, py) + dy, -py)  # noqa: E731
    A, B, C, D = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
    for dy, mat in ((0.0, "roof_tile"), (-0.18, "slab")):
        b.quad_strip("roof", mat, P(*A, dy), P(*B, dy), P(*C, dy), P(*D, dy))
    # Fascia all round, and the clerestory: glass between the slab and the high edge.
    for (pa, pb) in ((A, B), (B, C), (C, D), (D, A)):
        b.quad_strip("roof", "timber", P(*pa), P(*pb), P(*pb, -0.18), P(*pa, -0.18))
    fx0, fy0, fx1, fy1 = footprint.bounds
    for (pa, pb) in (((fx0, fy0), (fx1, fy0)), ((fx1, fy0), (fx1, fy1)), ((fx1, fy1), (fx0, fy1)), ((fx0, fy1), (fx0, fy0))):
        ya, yb = h(*pa) - 0.18, h(*pb) - 0.18
        if max(ya, yb) - y < 0.25:
            continue
        b.quad_strip("roof", "glass", (pa[0], y, -pa[1]), (pb[0], y, -pb[1]), (pb[0], yb, -pb[1]), (pa[0], ya, -pa[1]))
