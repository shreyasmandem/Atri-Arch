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


#: Where the pool goes, as the client can choose it. "rear" is the default:
#: behind the house, centred on it and parallel to its back wall, a terrace
#: away from the door - the way a garden pool is usually laid out.
POOL_PLACES: dict[str, str] = {
    "rear": "Behind the house, centred",
    "side": "Beside the house",
    "northeast": "In the north-east (Vastu)",
    "corner": "In the far corner",
}


def pool_rect(plan: FloorPlan):
    """Where the pool goes: (shapely box, kind actually used), or None when
    none was asked for or none fits. See `pool_placement`."""
    placed = pool_placement(plan)
    return None if placed is None else placed[:2]


def pool_placement(plan: FloorPlan):
    """Where the pool goes and how it got there: (shapely box, kind used,
    place used), or None. It goes where the site's `pool_place` asks, lined
    up with the house; if that will not take the pool asked for, the next
    place that will, before a smaller pool."""
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

    # The house's frame: its centre, the way to its back garden, and across it.
    hc = foot.centroid if foot is not None else plot.centroid
    back = Vec2(-road.x, -road.y) if road is not None else Vec2(0.0, -1.0)
    across = Vec2(-back.y, back.x)
    pts = list(foot.exterior.coords) if foot is not None and hasattr(foot, "exterior") else \
        [c for g in getattr(foot, "geoms", []) for c in g.exterior.coords] or [(hc.x, hc.y)]
    rear = max((x - hc.x) * back.x + (y - hc.y) * back.y for x, y in pts)
    half = max(abs((x - hc.x) * across.x + (y - hc.y) * across.y) for x, y in pts)
    theta = math.radians(45.0 - plan.site.north_angle)
    ne = Vec2(math.sin(theta), math.cos(theta))

    def score(place: str, cand, wide: bool) -> float | None:
        c = cand.centroid
        vx, vy = c.x - hc.x, c.y - hc.y
        along, side = vx * back.x + vy * back.y, vx * across.x + vy * across.y
        long_axis = Vec2(1.0, 0.0) if wide else Vec2(0.0, 1.0)
        short = min(cand.bounds[2] - cand.bounds[0], cand.bounds[3] - cand.bounds[1])
        if place == "rear":
            if along < rear * 0.5:
                return None
            # Centred on the house, its long side parallel to the back wall, a terrace's depth out.
            parallel = abs(long_axis.x * across.x + long_axis.y * across.y)
            return -abs(side) - 0.6 * abs(along - (rear + 1.2 + 2.0 + short / 2)) + 2.5 * parallel
        if place == "side":
            # Beside the house means level with it, in a side yard, not behind it.
            if abs(side) < half * 0.7 or abs(along) > rear * 0.75:
                return None
            # Alongside the house, running with it, level with its middle.
            parallel = abs(long_axis.x * back.x + long_axis.y * back.y)
            return -0.8 * abs(along) - 0.3 * abs(abs(side) - half - 1.2 - short / 2) + 2.5 * parallel
        if place == "northeast":
            d = math.hypot(vx, vy) or 1.0
            return 10.0 * (vx * ne.x + vy * ne.y) / d + 0.05 * d
        # The far corner: as far from the road as it goes.
        return c.distance(gate) if gate is not None else math.hypot(vx, vy)

    asked = plan.site.pool_place if plan.site.pool_place in POOL_PLACES else "rear"
    places = [asked] + [p for p in POOL_PLACES if p != asked]
    order = list(POOLS)
    for k in order[order.index(kind):]:
        w, l = POOLS[k]
        cands = []
        for (a, b) in ((w, l), (l, w)):
            steps_x, steps_y = int((x1 - x0 - a) / 0.25) + 1, int((y1 - y0 - b) / 0.25) + 1
            for i in range(max(0, steps_x)):
                for j in range(max(0, steps_y)):
                    cand = box(x0 + i * 0.25, y0 + j * 0.25, x0 + i * 0.25 + a, y0 + j * 0.25 + b)
                    if fit.contains(cand):
                        cands.append((cand, a >= b))
        for place in places:
            scored = [(sc, cand) for cand, wide in cands if (sc := score(place, cand, wide)) is not None]
            if scored:
                return max(scored, key=lambda t: t[0])[1], k, place
    return None


#: Garden features: where each traditionally sits (compass bearing from the
#: plot's centre) and how much clear ground it needs (radius, metres).
#: Tulsi and water to the north-east, the swing to the north-west, the heavy
#: rock garden and the gazebo to the south-west, the sit-out to the north.
YARD_FEATURES: dict[str, tuple[float, float]] = {
    "tulsi": (45.0, 0.9), "waterwall": (45.0, 1.4), "koipond": (20.0, 1.8), "jhoola": (315.0, 1.6),
    "gazebo": (225.0, 2.0), "rockgarden": (240.0, 1.6), "sitout": (0.0, 1.5),
}
YARD_NAMES = {"tulsi": "tulsi platform", "waterwall": "water wall", "koipond": "koi pond", "jhoola": "jhoola swing",
              "gazebo": "gazebo", "rockgarden": "rock garden", "sitout": "garden sit-out"}


def yard_spot(plan: FloorPlan, kind: str):
    """Where the garden feature goes: (centre Vec2, radius) in the open garden,
    as near its traditional quarter as the plot allows, clear of the house,
    the drive, the gate and the pool; None when nothing fits."""
    from shapely.geometry import LineString, Point, Polygon
    from shapely.prepared import prep

    if kind not in YARD_FEATURES or not plan.site.boundary:
        return None
    bearing, radius = YARD_FEATURES[kind]
    plot = Polygon([(p.x, p.y) for p in plan.site.boundary]).buffer(0)
    free = plot.buffer(-0.5)
    foot = _footprint(plan)
    if foot is not None:
        free = free.difference(foot.buffer(0.8))
    road = road_vector(plan)
    if road is not None:
        minx, miny, maxx, maxy = plot.bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        gate = Point(cx + road.x * (maxx - minx) / 2, cy + road.y * (maxy - miny) / 2)
        free = free.difference(gate.buffer(2.6))
        if foot is not None:
            free = free.difference(LineString([(gate.x, gate.y), (foot.centroid.x, foot.centroid.y)]).buffer(1.8))
    pool = pool_rect(plan)
    if pool is not None:
        free = free.difference(pool[0].buffer(1.3))
    if free.is_empty:
        return None
    centre = plot.centroid
    theta = math.radians(bearing - plan.site.north_angle)
    want = Vec2(math.sin(theta), math.cos(theta))
    x0, y0, x1, y1 = free.bounds
    for r in (radius, radius * 0.75):
        fit = prep(free)
        best, best_score = None, -1e9
        steps_x, steps_y = int((x1 - x0) / 0.3) + 1, int((y1 - y0) / 0.3) + 1
        for i in range(steps_x):
            for j in range(steps_y):
                p = Point(x0 + i * 0.3, y0 + j * 0.3)
                if not fit.contains(p.buffer(r, 8)):
                    continue
                dx, dy = p.x - centre.x, p.y - centre.y
                d = math.hypot(dx, dy) or 1.0
                score = (dx * want.x + dy * want.y) / d + 0.02 * d       # towards its quarter, then outwards
                if score > best_score:
                    best, best_score = Vec2(p.x, p.y), score
        if best is not None:
            return best, r
    return None
