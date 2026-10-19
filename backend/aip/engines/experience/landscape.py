"""The plot around the house: how much is lawn, and where the pool goes.

A client can ask for a share of the plot to stay green and for a pool. The
lawn share holds the house's footprint down when the plan is generated (see
`SimpleBriefRequest.to_brief`); this module then finds the pool a place: the
largest open stretch of the plot clear of the house and the drive, as far
from the road as it will go, so it sits in the private back garden. The 3D
model and the site plan both ask it, so they always agree.
"""

from __future__ import annotations

import math

from aip.domain.geometry import Vec2
from aip.domain.plan import FloorPlan

#: Pool kinds: (width, length) in metres. A plot too tight for the one asked
#: for gets the next smaller that fits.
POOLS: dict[str, tuple[float, float]] = {"lap": (2.5, 14.0), "family": (4.0, 8.0), "plunge": (3.0, 6.0)}
POOL_NAMES = {"lap": "lap pool", "family": "family pool", "plunge": "plunge pool"}


def pool_area(kind: str) -> float:
    w, l = POOLS.get(kind, (0.0, 0.0))
    return w * l


def road_vector(plan: FloorPlan) -> Vec2 | None:
    dirs = plan.site.road_directions
    if not dirs:
        return None
    bearing = math.radians((dirs[0].bearing + plan.site.north_angle) % 360)
    return Vec2(math.sin(bearing), math.cos(bearing))


def _footprint(plan: FloorPlan):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    ground = plan.level_at(0) if plan.levels else None
    if ground is None:
        return None
    polys = [Polygon([(p.x, p.y) for p in r.polygon]).buffer(0) for r in ground.rooms if len(r.polygon) >= 3]
    return unary_union(polys) if polys else None


def pool_rect(plan: FloorPlan):
    """Where the pool goes: (shapely box, kind actually used), or None when
    none was asked for or none fits."""
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.prepared import prep

    kind = plan.site.pool
    if kind not in POOLS or not plan.site.boundary:
        return None
    plot = Polygon([(p.x, p.y) for p in plan.site.boundary]).buffer(0)
    # Room for the deck round it (0.9 m) and a step to the boundary wall.
    free = plot.buffer(-1.4)
    foot = _footprint(plan)
    if foot is not None:
        free = free.difference(foot.buffer(1.2))
    # Keep the gate and the drive to the house clear.
    road = road_vector(plan)
    gate = None
    if road is not None:
        minx, miny, maxx, maxy = plot.bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        gate = Point(cx + road.x * (maxx - minx) / 2, cy + road.y * (maxy - miny) / 2)
        free = free.difference(gate.buffer(3.0))
        if foot is not None:
            free = free.difference(LineString([(gate.x, gate.y), (foot.centroid.x, foot.centroid.y)]).buffer(2.0))
    if free.is_empty:
        return None
    fit = prep(free)
    x0, y0, x1, y1 = free.bounds
    order = list(POOLS)
    for k in order[order.index(kind):]:
        w, l = POOLS[k]
        best, best_score = None, -1.0
        for (a, b) in ((w, l), (l, w)):
            steps_x, steps_y = int((x1 - x0 - a) / 0.25) + 1, int((y1 - y0 - b) / 0.25) + 1
            for i in range(max(0, steps_x)):
                for j in range(max(0, steps_y)):
                    cand = box(x0 + i * 0.25, y0 + j * 0.25, x0 + i * 0.25 + a, y0 + j * 0.25 + b)
                    if not fit.contains(cand):
                        continue
                    # As far from the road as it goes: the private garden.
                    score = cand.centroid.distance(gate) if gate is not None else 0.0
                    if score > best_score:
                        best, best_score = cand, score
        if best is not None:
            return best, k
    return None
