"""Computational geometry for building layouts.

Deliberately dependency-light: the core predicates are implemented directly so
the platform can run anywhere, with Shapely used only for the heavier boolean
operations. All units are metres and all angles are degrees clockwise from true
north unless stated otherwise, which matches how architects and Vastu texts both
describe orientation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Sequence

EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Vec2:
    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, k: float) -> Vec2:
        return Vec2(self.x * k, self.y * k)

    __rmul__ = __mul__

    def __truediv__(self, k: float) -> Vec2:
        return Vec2(self.x / k, self.y / k)

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec2) -> float:
        return self.x * other.y - self.y * other.x

    @property
    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def normalised(self) -> Vec2:
        n = self.length
        return Vec2(0.0, 0.0) if n < EPS else Vec2(self.x / n, self.y / n)

    def perpendicular(self) -> Vec2:
        """90 degrees counter-clockwise."""
        return Vec2(-self.y, self.x)

    def distance_to(self, other: Vec2) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def rotated(self, degrees: float, about: Vec2 | None = None) -> Vec2:
        origin = about or Vec2(0.0, 0.0)
        rad = math.radians(degrees)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = self.x - origin.x, self.y - origin.y
        return Vec2(origin.x + dx * cos_a - dy * sin_a, origin.y + dx * sin_a + dy * cos_a)

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    def rounded(self, places: int = 4) -> Vec2:
        return Vec2(round(self.x, places), round(self.y, places))


Polygon = list[Vec2]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def centre(self) -> Vec2:
        return Vec2((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)

    @property
    def aspect_ratio(self) -> float:
        short, long = sorted((self.width, self.height))
        return long / short if short > EPS else float("inf")

    def contains(self, p: Vec2) -> bool:
        return self.min_x - EPS <= p.x <= self.max_x + EPS and self.min_y - EPS <= p.y <= self.max_y + EPS

    def intersects(self, other: BoundingBox) -> bool:
        return not (
            self.max_x < other.min_x
            or other.max_x < self.min_x
            or self.max_y < other.min_y
            or other.max_y < self.min_y
        )

    def to_polygon(self) -> Polygon:
        return [
            Vec2(self.min_x, self.min_y),
            Vec2(self.max_x, self.min_y),
            Vec2(self.max_x, self.max_y),
            Vec2(self.min_x, self.max_y),
        ]


class Direction(str, Enum):
    """16-fold compass division.

    Vastu Shastra reasons in 16 zones (`shodasha padas`), not 8, and several of
    the most-cited rules - Ishanya for the prayer room, Agneya for the kitchen -
    are only expressible at that resolution. Modern building analysis needs the
    same resolution for solar exposure, so one enum serves both.
    """

    N = "N"
    NNE = "NNE"
    NE = "NE"
    ENE = "ENE"
    E = "E"
    ESE = "ESE"
    SE = "SE"
    SSE = "SSE"
    S = "S"
    SSW = "SSW"
    SW = "SW"
    WSW = "WSW"
    W = "W"
    WNW = "WNW"
    NW = "NW"
    NNW = "NNW"
    CENTRE = "CENTRE"

    @property
    def sanskrit(self) -> str:
        return _SANSKRIT.get(self, "")

    @property
    def bearing(self) -> float:
        """Centre bearing in degrees clockwise from north."""
        return _BEARINGS.get(self, 0.0)

    @property
    def cardinal(self) -> "Direction":
        """Collapse to the nearest of the 8 principal directions."""
        return _TO_EIGHT.get(self, self)


_ORDER: tuple[Direction, ...] = (
    Direction.N, Direction.NNE, Direction.NE, Direction.ENE,
    Direction.E, Direction.ESE, Direction.SE, Direction.SSE,
    Direction.S, Direction.SSW, Direction.SW, Direction.WSW,
    Direction.W, Direction.WNW, Direction.NW, Direction.NNW,
)

_BEARINGS: dict[Direction, float] = {d: i * 22.5 for i, d in enumerate(_ORDER)}
_BEARINGS[Direction.CENTRE] = 0.0

_SANSKRIT: dict[Direction, str] = {
    Direction.N: "Uttara (Kubera)",
    Direction.NNE: "Uttara-Ishanya",
    Direction.NE: "Ishanya (Ishana)",
    Direction.ENE: "Purva-Ishanya",
    Direction.E: "Purva (Indra)",
    Direction.ESE: "Purva-Agneya",
    Direction.SE: "Agneya (Agni)",
    Direction.SSE: "Dakshina-Agneya",
    Direction.S: "Dakshina (Yama)",
    Direction.SSW: "Dakshina-Nairutya",
    Direction.SW: "Nairutya (Nirriti)",
    Direction.WSW: "Paschima-Nairutya",
    Direction.W: "Paschima (Varuna)",
    Direction.WNW: "Paschima-Vayavya",
    Direction.NW: "Vayavya (Vayu)",
    Direction.NNW: "Uttara-Vayavya",
    Direction.CENTRE: "Brahmasthan",
}

_TO_EIGHT: dict[Direction, Direction] = {
    Direction.N: Direction.N, Direction.NNE: Direction.NE, Direction.NE: Direction.NE,
    Direction.ENE: Direction.NE, Direction.E: Direction.E, Direction.ESE: Direction.SE,
    Direction.SE: Direction.SE, Direction.SSE: Direction.SE, Direction.S: Direction.S,
    Direction.SSW: Direction.SW, Direction.SW: Direction.SW, Direction.WSW: Direction.SW,
    Direction.W: Direction.W, Direction.WNW: Direction.NW, Direction.NW: Direction.NW,
    Direction.NNW: Direction.N, Direction.CENTRE: Direction.CENTRE,
}


def normalise_bearing(degrees: float) -> float:
    return degrees % 360.0


def bearing_to_direction(degrees: float) -> Direction:
    """Map a bearing (deg clockwise from north) onto one of 16 sectors."""
    bearing = normalise_bearing(degrees)
    index = int((bearing + 11.25) % 360.0 // 22.5)
    return _ORDER[index]


def bearing_between(origin: Vec2, target: Vec2, north_angle: float = 0.0) -> float:
    """Bearing from `origin` to `target`, corrected for plan rotation.

    `north_angle` is the compass bearing of the plan's +Y axis. A plan drawn with
    +Y pointing north has `north_angle == 0`; a plan rotated 30 degrees so that
    +Y points ENE has `north_angle == 30`.
    """
    delta = target - origin
    if delta.length < EPS:
        return 0.0
    # atan2(dx, dy) gives clockwise-from-+Y, which is what a compass measures.
    raw = math.degrees(math.atan2(delta.x, delta.y))
    return normalise_bearing(raw + north_angle)


def direction_of(
    point: Vec2,
    reference: Vec2,
    north_angle: float = 0.0,
    *,
    centre_radius: float = 0.0,
) -> Direction:
    """Which compass sector `point` occupies relative to `reference`."""
    if centre_radius > 0 and point.distance_to(reference) <= centre_radius:
        return Direction.CENTRE
    return bearing_to_direction(bearing_between(reference, point, north_angle))


# ---------------------------------------------------------------------------
# Polygon operations
# ---------------------------------------------------------------------------


def polygon_area(points: Sequence[Vec2]) -> float:
    """Unsigned area via the shoelace formula."""
    return abs(signed_area(points))


def signed_area(points: Sequence[Vec2]) -> float:
    """Positive when the ring is counter-clockwise."""
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        total += a.x * b.y - b.x * a.y
    return total / 2.0


def is_clockwise(points: Sequence[Vec2]) -> bool:
    return signed_area(points) < 0


def ensure_ccw(points: Sequence[Vec2]) -> Polygon:
    pts = list(points)
    return pts[::-1] if is_clockwise(pts) else pts


def perimeter(points: Sequence[Vec2]) -> float:
    n = len(points)
    if n < 2:
        return 0.0
    return sum(points[i].distance_to(points[(i + 1) % n]) for i in range(n))


def centroid(points: Sequence[Vec2]) -> Vec2:
    """Area centroid (not the vertex average, which is wrong for L-shapes)."""
    n = len(points)
    if n == 0:
        return Vec2(0.0, 0.0)
    if n < 3:
        return Vec2(sum(p.x for p in points) / n, sum(p.y for p in points) / n)

    area = signed_area(points)
    if abs(area) < EPS:
        return Vec2(sum(p.x for p in points) / n, sum(p.y for p in points) / n)

    cx = cy = 0.0
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        cross = a.x * b.y - b.x * a.y
        cx += (a.x + b.x) * cross
        cy += (a.y + b.y) * cross
    factor = 1.0 / (6.0 * area)
    return Vec2(cx * factor, cy * factor)


def bounding_box(points: Iterable[Vec2]) -> BoundingBox:
    pts = list(points)
    if not pts:
        return BoundingBox(0.0, 0.0, 0.0, 0.0)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    return BoundingBox(min(xs), min(ys), max(xs), max(ys))


def point_in_polygon(point: Vec2, polygon: Sequence[Vec2]) -> bool:
    """Ray-casting test. Points exactly on an edge count as inside.

    The cheap ray cast runs first and the expensive boundary test only runs when
    it reports "outside", which is the case where the answer could still flip.
    This ordering matters: the layout optimiser calls this function millions of
    times per design session.
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        pi, pj = polygon[i], polygon[j]
        if (pi.y > point.y) != (pj.y > point.y):
            x_cross = (pj.x - pi.x) * (point.y - pi.y) / (pj.y - pi.y + EPS) + pi.x
            if point.x < x_cross:
                inside = not inside
        j = i
    return inside or point_on_boundary(point, polygon)


def point_on_boundary(point: Vec2, polygon: Sequence[Vec2], tol: float = 1e-7) -> bool:
    n = len(polygon)
    for i in range(n):
        if distance_point_to_segment(point, polygon[i], polygon[(i + 1) % n]) <= tol:
            return True
    return False


def distance_point_to_segment(p: Vec2, a: Vec2, b: Vec2) -> float:
    ab = b - a
    length_sq = ab.dot(ab)
    if length_sq < EPS:
        return p.distance_to(a)
    t = max(0.0, min(1.0, (p - a).dot(ab) / length_sq))
    return p.distance_to(a + ab * t)


def closest_point_on_segment(p: Vec2, a: Vec2, b: Vec2) -> Vec2:
    ab = b - a
    length_sq = ab.dot(ab)
    if length_sq < EPS:
        return a
    t = max(0.0, min(1.0, (p - a).dot(ab) / length_sq))
    return a + ab * t


def segments_intersect(a1: Vec2, a2: Vec2, b1: Vec2, b2: Vec2) -> bool:
    d1 = (a2 - a1).cross(b1 - a1)
    d2 = (a2 - a1).cross(b2 - a1)
    d3 = (b2 - b1).cross(a1 - b1)
    d4 = (b2 - b1).cross(a2 - b1)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    for d, p, s1, s2 in ((d1, b1, a1, a2), (d2, b2, a1, a2), (d3, a1, b1, b2), (d4, a2, b1, b2)):
        if abs(d) < EPS and distance_point_to_segment(p, s1, s2) < EPS:
            return True
    return False


def segment_intersection(a1: Vec2, a2: Vec2, b1: Vec2, b2: Vec2) -> Vec2 | None:
    r = a2 - a1
    s = b2 - b1
    denom = r.cross(s)
    if abs(denom) < EPS:
        return None
    t = (b1 - a1).cross(s) / denom
    u = (b1 - a1).cross(r) / denom
    if -EPS <= t <= 1 + EPS and -EPS <= u <= 1 + EPS:
        return a1 + r * t
    return None


def polygons_overlap(a: Sequence[Vec2], b: Sequence[Vec2]) -> bool:
    """True when the interiors intersect (shared edges alone do not count)."""
    if not bounding_box(a).intersects(bounding_box(b)):
        return False
    for poly, other in ((a, b), (b, a)):
        for i in range(len(poly)):
            p1, p2 = poly[i], poly[(i + 1) % len(poly)]
            mid = (p1 + p2) * 0.5
            probe = mid + (p2 - p1).perpendicular().normalised() * 1e-4
            if point_in_polygon(probe, other) and not point_on_boundary(probe, other, 1e-5):
                return True
    return any(point_in_polygon(p, b) and not point_on_boundary(p, b) for p in a) or any(
        point_in_polygon(p, a) and not point_on_boundary(p, a) for p in b
    )


def overlap_area(a: Sequence[Vec2], b: Sequence[Vec2]) -> float:
    """Intersection area, using Shapely when present and sampling otherwise."""
    try:
        from shapely.geometry import Polygon as ShapelyPolygon

        pa = ShapelyPolygon([p.as_tuple() for p in a]).buffer(0)
        pb = ShapelyPolygon([p.as_tuple() for p in b]).buffer(0)
        return float(pa.intersection(pb).area)
    except Exception:
        return _sampled_overlap(a, b)


def _sampled_overlap(a: Sequence[Vec2], b: Sequence[Vec2], samples: int = 60) -> float:
    box_a, box_b = bounding_box(a), bounding_box(b)
    if not box_a.intersects(box_b):
        return 0.0
    lo_x, hi_x = max(box_a.min_x, box_b.min_x), min(box_a.max_x, box_b.max_x)
    lo_y, hi_y = max(box_a.min_y, box_b.min_y), min(box_a.max_y, box_b.max_y)
    if hi_x <= lo_x or hi_y <= lo_y:
        return 0.0
    cell = ((hi_x - lo_x) / samples) * ((hi_y - lo_y) / samples)
    hits = 0
    for i in range(samples):
        px = lo_x + (i + 0.5) * (hi_x - lo_x) / samples
        for j in range(samples):
            py = lo_y + (j + 0.5) * (hi_y - lo_y) / samples
            probe = Vec2(px, py)
            if point_in_polygon(probe, a) and point_in_polygon(probe, b):
                hits += 1
    return hits * cell


def shrink_polygon(points: Sequence[Vec2], distance: float) -> Polygon:
    """Inward offset - used for setbacks and for clear-floor-area checks."""
    if distance <= 0:
        return list(points)
    try:
        from shapely.geometry import Polygon as ShapelyPolygon

        poly = ShapelyPolygon([p.as_tuple() for p in points]).buffer(0)
        shrunk = poly.buffer(-distance, join_style=2)
        if shrunk.is_empty:
            return []
        if shrunk.geom_type == "MultiPolygon":
            shrunk = max(shrunk.geoms, key=lambda g: g.area)
        return [Vec2(x, y) for x, y in list(shrunk.exterior.coords)[:-1]]
    except Exception:
        return _scale_about_centroid(points, distance)


def _scale_about_centroid(points: Sequence[Vec2], distance: float) -> Polygon:
    c = centroid(points)
    out: Polygon = []
    for p in points:
        d = p - c
        n = d.length
        if n < EPS:
            out.append(p)
            continue
        out.append(c + d * max(0.0, (n - distance) / n))
    return out


def convex_hull(points: Sequence[Vec2]) -> Polygon:
    """Andrew's monotone chain."""
    pts = sorted({(p.x, p.y) for p in points})
    if len(pts) < 3:
        return [Vec2(x, y) for x, y in pts]

    def build(seq: list[tuple[float, float]]) -> list[tuple[float, float]]:
        chain: list[tuple[float, float]] = []
        for p in seq:
            while len(chain) >= 2:
                o, a = chain[-2], chain[-1]
                if (a[0] - o[0]) * (p[1] - o[1]) - (a[1] - o[1]) * (p[0] - o[0]) <= 0:
                    chain.pop()
                else:
                    break
            chain.append(p)
        return chain

    lower = build(pts)
    upper = build(pts[::-1])
    return [Vec2(x, y) for x, y in lower[:-1] + upper[:-1]]


def rectangle(origin: Vec2, width: float, height: float) -> Polygon:
    """Axis-aligned rectangle, counter-clockwise from `origin` (lower-left)."""
    return [
        Vec2(origin.x, origin.y),
        Vec2(origin.x + width, origin.y),
        Vec2(origin.x + width, origin.y + height),
        Vec2(origin.x, origin.y + height),
    ]


def rotate_polygon(points: Sequence[Vec2], degrees: float, about: Vec2 | None = None) -> Polygon:
    pivot = about or centroid(points)
    return [p.rotated(degrees, pivot) for p in points]


def translate_polygon(points: Sequence[Vec2], delta: Vec2) -> Polygon:
    return [p + delta for p in points]


def shared_edge(
    a: Sequence[Vec2], b: Sequence[Vec2], tol: float = 0.06
) -> tuple[Vec2, Vec2] | None:
    """Longest collinear overlap between two polygon boundaries.

    This is how the platform decides two rooms are genuinely adjacent - and
    therefore whether a door between them is possible - rather than merely close.
    """
    if is_axis_aligned_rect(a) and is_axis_aligned_rect(b):
        return _rect_shared_edge(bounding_box(a), bounding_box(b), tol)

    best: tuple[float, Vec2, Vec2] | None = None
    for i in range(len(a)):
        a1, a2 = a[i], a[(i + 1) % len(a)]
        dir_a = (a2 - a1).normalised()
        if dir_a.length < EPS:
            continue
        for j in range(len(b)):
            b1, b2 = b[j], b[(j + 1) % len(b)]
            dir_b = (b2 - b1).normalised()
            if abs(dir_a.cross(dir_b)) > 0.06:  # not parallel
                continue
            if distance_point_to_segment(b1, a1, a2) > tol or distance_point_to_segment(b2, a1, a2) > tol:
                continue
            # Project both segments onto a's axis and intersect the intervals.
            t_a1, t_a2 = 0.0, (a2 - a1).length
            t_b1 = (b1 - a1).dot(dir_a)
            t_b2 = (b2 - a1).dot(dir_a)
            lo = max(min(t_a1, t_a2), min(t_b1, t_b2))
            hi = min(max(t_a1, t_a2), max(t_b1, t_b2))
            if hi - lo > tol:
                length = hi - lo
                if best is None or length > best[0]:
                    best = (length, a1 + dir_a * lo, a1 + dir_a * hi)
    if best is None:
        return None
    return best[1], best[2]


def _rect_shared_edge(a: BoundingBox, b: BoundingBox, tol: float) -> tuple[Vec2, Vec2] | None:
    """Constant-time shared-edge test for two axis-aligned rectangles.

    The generator emits rectangular rooms, so this is the path the adjacency
    graph actually takes. Doing it in closed form instead of the general
    edge-pair sweep is what makes a full-population fitness evaluation cheap
    enough to run thousands of times per second.
    """
    # Vertical contact: touching x faces with overlapping y extents.
    for ax, bx in ((a.max_x, b.min_x), (a.min_x, b.max_x)):
        if abs(ax - bx) <= tol:
            lo = max(a.min_y, b.min_y)
            hi = min(a.max_y, b.max_y)
            if hi - lo > tol:
                return Vec2(ax, lo), Vec2(ax, hi)
    # Horizontal contact: touching y faces with overlapping x extents.
    for ay, by in ((a.max_y, b.min_y), (a.min_y, b.max_y)):
        if abs(ay - by) <= tol:
            lo = max(a.min_x, b.min_x)
            hi = min(a.max_x, b.max_x)
            if hi - lo > tol:
                return Vec2(lo, ay), Vec2(hi, ay)
    return None


def aspect_ratio(points: Sequence[Vec2]) -> float:
    return bounding_box(points).aspect_ratio


def compactness(points: Sequence[Vec2]) -> float:
    """Polsby-Popper score in [0, 1]. A circle scores 1, a slot scores near 0.

    Used as a proxy for how buildable and furnishable a generated room is - long
    thin rooms are geometrically valid but practically useless.
    """
    p = perimeter(points)
    if p < EPS:
        return 0.0
    return min(1.0, 4 * math.pi * polygon_area(points) / (p * p))


def is_axis_aligned_rect(points: Sequence[Vec2], tol: float = 1e-6) -> bool:
    """True when the ring is a 4-corner rectangle aligned to the axes."""
    if len(points) != 4:
        return False
    for i in range(4):
        a, b = points[i], points[(i + 1) % 4]
        if abs(a.x - b.x) > tol and abs(a.y - b.y) > tol:
            return False
    box = bounding_box(points)
    return abs(polygon_area(points) - box.area) < max(tol, box.area * 1e-6)


def largest_inscribed_square(points: Sequence[Vec2], resolution: int = 16) -> float:
    """Side of the largest axis-aligned square that fits inside the polygon.

    A practical furnishability metric: it answers "can a bed actually go here",
    which room area alone does not - a 14 m2 room that is 1.6 m wide passes every
    area check and is still unusable.

    Rectangles are answered exactly and in constant time. That fast path is not
    an optimisation detail: the slicing-tree generator produces rectangular
    rooms, so it is the case that dominates the optimiser's inner loop, and the
    grid search below exists only for hand-drawn or imported non-convex plans.
    """
    box = bounding_box(points)
    if box.width < EPS or box.height < EPS:
        return 0.0
    if is_axis_aligned_rect(points):
        return min(box.width, box.height)

    best = 0.0
    step_x = box.width / resolution
    step_y = box.height / resolution
    for i in range(resolution):
        ox = box.min_x + i * step_x
        for j in range(resolution):
            oy = box.min_y + j * step_y
            hi = min(box.width - i * step_x, box.height - j * step_y)
            if hi <= best:
                continue                      # cannot beat the incumbent
            lo = best
            while hi - lo > 0.03:
                mid = (lo + hi) / 2
                corners = (
                    Vec2(ox, oy), Vec2(ox + mid, oy),
                    Vec2(ox + mid, oy + mid), Vec2(ox, oy + mid),
                    Vec2(ox + mid / 2, oy + mid / 2),
                )
                if all(point_in_polygon(c, points) for c in corners):
                    lo = mid
                else:
                    hi = mid
            best = max(best, lo)
    return best
