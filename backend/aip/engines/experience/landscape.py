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


def drive_line(footprint, gate):
    """The drive's centre line: from the gate to the nearest point of the
    house. The 3D model paves it and the garden keeps clear of it."""
    from shapely.geometry import LineString, Point

    g = Point(gate.x, gate.y)
    edge = footprint.exterior if hasattr(footprint, "exterior") else footprint.convex_hull.exterior
    near = edge.interpolate(edge.project(g))
    return LineString([(g.x, g.y), (near.x, near.y)])


#: The drive's half width as paved (see `arch3d._site`).
DRIVE_HALF = 1.6
#: The deck round a pool and the coping inside it.
POOL_DECK = 0.9


def _gate(plan: FloorPlan, plot):
    from shapely.geometry import Point

    road = road_vector(plan)
    if road is None:
        return None
    minx, miny, maxx, maxy = plot.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return Point(cx + road.x * (maxx - minx) / 2, cy + road.y * (maxy - miny) / 2)


class _PoolSite:
    """The open ground a pool can take on this plot, and the house's frame
    (its back, across it, the north-east) for scoring where it sits."""

    def __init__(self, plan: FloorPlan):
        from shapely.geometry import Polygon
        from shapely.prepared import prep

        self.ok = False
        if not plan.site.boundary:
            return
        plot = Polygon([(p.x, p.y) for p in plan.site.boundary]).buffer(0)
        # Room for the deck round it and a step to the boundary wall.
        free = plot.buffer(-(POOL_DECK + 0.5))
        foot = _footprint(plan)
        if foot is not None:
            # A path between the house (its plinth and the steps down from its doors) and the deck.
            free = free.difference(foot.buffer(POOL_DECK + 0.9))
        # Keep the gate and the drive to the house clear, deck and all.
        road = road_vector(plan)
        self.gate = _gate(plan, plot)
        if self.gate is not None:
            free = free.difference(self.gate.buffer(3.0))
            if foot is not None:
                free = free.difference(drive_line(foot, self.gate).buffer(DRIVE_HALF + POOL_DECK + 0.2))
        if free.is_empty:
            return
        self.ok = True
        self.fit = prep(free)
        self.bounds = free.bounds
        self.hc = foot.centroid if foot is not None else plot.centroid
        self.back = Vec2(-road.x, -road.y) if road is not None else Vec2(0.0, -1.0)
        self.across = Vec2(-self.back.y, self.back.x)
        pts = list(foot.exterior.coords) if foot is not None and hasattr(foot, "exterior") else \
            [c for g in getattr(foot, "geoms", []) for c in g.exterior.coords] or [(self.hc.x, self.hc.y)]
        hx, hy = self.hc.x, self.hc.y
        self.rear = max((x - hx) * self.back.x + (y - hy) * self.back.y for x, y in pts)
        self.half = max(abs((x - hx) * self.across.x + (y - hy) * self.across.y) for x, y in pts)
        theta = math.radians(45.0 - plan.site.north_angle)
        self.ne = Vec2(math.sin(theta), math.cos(theta))
        self._cands: dict[str, list] = {}

    def candidates(self, kind: str) -> list:
        """Every pool of this kind that fits, on a 25 cm grid, both ways round."""
        if kind not in self._cands:
            from shapely.geometry import box

            w, l = POOLS[kind]
            x0, y0, x1, y1 = self.bounds
            out = []
            for (a, b) in ((w, l), (l, w)):
                for i in range(max(0, int((x1 - x0 - a) / 0.25) + 1)):
                    for j in range(max(0, int((y1 - y0 - b) / 0.25) + 1)):
                        cand = box(x0 + i * 0.25, y0 + j * 0.25, x0 + i * 0.25 + a, y0 + j * 0.25 + b)
                        if self.fit.contains(cand):
                            out.append((cand, a >= b))
            self._cands[kind] = out
        return self._cands[kind]

    def score(self, place: str, cand, wide: bool) -> float | None:
        c = cand.centroid
        vx, vy = c.x - self.hc.x, c.y - self.hc.y
        back, across = self.back, self.across
        along, side = vx * back.x + vy * back.y, vx * across.x + vy * across.y
        long_axis = Vec2(1.0, 0.0) if wide else Vec2(0.0, 1.0)
        short = min(cand.bounds[2] - cand.bounds[0], cand.bounds[3] - cand.bounds[1])
        if place == "rear":
            if along < self.rear * 0.5:
                return None
            # Centred on the house, its long side parallel to the back wall, a terrace's depth out.
            parallel = abs(long_axis.x * across.x + long_axis.y * across.y)
            return -abs(side) - 0.6 * abs(along - (self.rear + 1.2 + 2.0 + short / 2)) + 2.5 * parallel
        if place == "side":
            # Beside the house means level with it, in a side yard, not behind it.
            if abs(side) < self.half * 0.7 or abs(along) > self.rear * 0.75:
                return None
            parallel = abs(long_axis.x * back.x + long_axis.y * back.y)
            return -0.8 * abs(along) - 0.3 * abs(abs(side) - self.half - 1.2 - short / 2) + 2.5 * parallel
        if place == "northeast":
            d = math.hypot(vx, vy) or 1.0
            return 10.0 * (vx * self.ne.x + vy * self.ne.y) / d + 0.05 * d
        # The far corner: as far from the road as it goes.
        return c.distance(self.gate) if self.gate is not None else math.hypot(vx, vy)

    def best(self, kind: str, place: str):
        scored = [(sc, cand) for cand, wide in self.candidates(kind) if (sc := self.score(place, cand, wide)) is not None]
        return max(scored, key=lambda t: t[0])[1] if scored else None


def pool_placement(plan: FloorPlan):
    """Where the pool goes and how it got there: (shapely box, kind used,
    place used), or None. It goes where the site's `pool_place` asks, lined
    up with the house; if that will not take the pool asked for, the next
    place that will, before a smaller pool."""
    kind = plan.site.pool
    if kind not in POOLS:
        return None
    site = _PoolSite(plan)
    if not site.ok:
        return None
    asked = plan.site.pool_place if plan.site.pool_place in POOL_PLACES else "rear"
    places = [asked] + [p for p in POOL_PLACES if p != asked]
    order = list(POOLS)
    for k in order[order.index(kind):]:
        for place in places:
            got = site.best(k, place)
            if got is not None:
                return got, k, place
    return None


def pool_options(plan: FloorPlan) -> dict[str, list[str]]:
    """For each kind of pool, the places on this plot it fits; an empty list
    when the open ground round the house will not take it anywhere."""
    site = _PoolSite(plan)
    if not site.ok:
        return {k: [] for k in POOLS}
    return {k: [p for p in POOL_PLACES if site.best(k, p) is not None] for k in POOLS}


#: Garden features: where each traditionally sits (compass bearing from the
#: plot's centre) and how much clear ground it needs (radius, metres).
#: Tulsi and water to the north-east, the swing to the north-west, the heavy
#: rock garden and the gazebo to the south-west, the sit-out to the north.
YARD_FEATURES: dict[str, tuple[float, float]] = {
    "tulsi": (45.0, 0.9), "waterwall": (45.0, 1.4), "koipond": (20.0, 1.8), "jhoola": (315.0, 1.6),
    "gazebo": (225.0, 2.0), "rockgarden": (240.0, 1.6), "sitout": (0.0, 1.5),
    # Water to the north-east, fire in Agneya (the south-east), flowers where the morning sun is, a deck to the west.
    "fountain": (30.0, 1.5), "firepit": (135.0, 1.7), "flowerbeds": (90.0, 1.5), "lounge": (270.0, 1.9),
}
YARD_NAMES = {"tulsi": "tulsi platform", "waterwall": "water wall", "koipond": "koi pond", "jhoola": "jhoola swing",
              "gazebo": "gazebo", "rockgarden": "rock garden", "sitout": "garden sit-out",
              "fountain": "fountain", "firepit": "fire pit", "flowerbeds": "flower beds", "lounge": "lounge deck"}


def yard_spot(plan: FloorPlan, kind: str):
    """Where the garden feature goes: (centre Vec2, radius) in the open garden,
    as near its traditional quarter as the plot allows, clear of the house,
    the drive, the gate and the pool; None when nothing fits."""
    from shapely.geometry import Point, Polygon
    from shapely.prepared import prep

    if kind not in YARD_FEATURES or not plan.site.boundary:
        return None
    bearing, radius = YARD_FEATURES[kind]
    plot = Polygon([(p.x, p.y) for p in plan.site.boundary]).buffer(0)
    free = plot.buffer(-0.5)
    foot = _footprint(plan)
    if foot is not None:
        free = free.difference(foot.buffer(0.8))
    gate = _gate(plan, plot)
    if gate is not None:
        free = free.difference(gate.buffer(2.6))
        if foot is not None:
            free = free.difference(drive_line(foot, gate).buffer(DRIVE_HALF + 0.2))
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


#: The widest the paved terrace and walks round the house and drive grow, metres.
APRON_MAX = 4.0


def ground_cover(plan: FloorPlan) -> dict:
    """The plot's ground laid out as the client asked: what is house, drive,
    pool, lawn and paving, with each share of the plot.

    Open ground is the plot less the house (its plinth), the drive and the pool
    with its deck. When the client set a lawn share and there is more open
    ground than that, the lawn is what they asked for, never less: the rest
    becomes a paved terrace and walks round the house and along the drive -
    grown out from them evenly, the way a garden is laid, up to `APRON_MAX`
    wide - and the lawn is what remains towards the boundary. With no lawn
    asked for, the open ground is plain grass.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    empty = Polygon()
    out = {"lawn": empty, "paved": empty, "shares": {}}
    if not plan.site.boundary:
        return out
    plot = Polygon([(p.x, p.y) for p in plan.site.boundary]).buffer(0)
    foot = _footprint(plan)
    house = foot.buffer(0.15, join_style=2) if foot is not None else empty
    gate = _gate(plan, plot)
    drive = (drive_line(foot, gate).buffer(DRIVE_HALF, cap_style=2).intersection(plot).difference(house)
             if foot is not None and gate is not None else empty)
    placed = pool_rect(plan)
    pool = placed[0].buffer(POOL_DECK, join_style=2).intersection(plot) if placed is not None else empty
    open_ = plot.difference(unary_union([house, drive, pool]))
    lawn, paved = open_, empty
    want = float(plan.site.garden_share or 0.0) * plot.area
    if want > 0 and open_.area > want + 1.0:
        # Grow the apron round the house and the drive until the lawn left is what was asked.
        core = unary_union([house, drive])
        lo, hi = 0.0, max(plot.bounds[2] - plot.bounds[0], plot.bounds[3] - plot.bounds[1])
        for _ in range(28):
            mid = (lo + hi) / 2
            if open_.difference(core.buffer(mid, join_style=2)).area > want:
                lo = mid
            else:
                hi = mid
        # The terrace and walks are an apron, never a car park: past a couple
        # of metres from the house the ground a plot cannot build on is grass,
        # so a lawn is never less than asked, and on a big plot it is more.
        lo = min(lo, APRON_MAX)
        lawn = open_.difference(core.buffer(lo, join_style=2))
        paved = open_.difference(lawn)
    a = plot.area or 1.0
    out.update(lawn=lawn, paved=paved, drive=drive, pool=pool, house=house, plot=plot)
    out["shares"] = {"house": house.intersection(plot).area / a, "drive": drive.area / a, "pool": pool.area / a,
                     "lawn": lawn.area / a, "paved": paved.area / a, "asked_lawn": want / a}
    return out


def simple_parts(geom) -> list:
    """A shape as polygons without holes (a paved ring round a house has one),
    for builders and drawings that take only an outline: each hole is cut through."""
    from shapely.geometry import LineString
    from shapely.ops import split

    todo = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "Polygon" and not g.is_empty]
    done = []
    while todo:
        g = todo.pop()
        if g.area < 0.05:
            continue
        if not g.interiors:
            done.append(g)
            continue
        cx = g.interiors[0].centroid.x
        y0, y1 = g.bounds[1] - 1, g.bounds[3] + 1
        parts = split(g, LineString([(cx, y0), (cx, y1)]))
        todo.extend(p for p in parts.geoms if p.geom_type == "Polygon")
    return done
