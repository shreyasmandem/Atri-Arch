"""Rooms from wall linework.

A CAD or SVG file from the real world rarely has a closed outline per room.
It has walls: two parallel faces per wall (or one thick stroke), broken where a
door sits, with the room names floating as text. The rooms are not drawn; they
are the *holes* the walls leave between them. This module finds those holes.

The same routine serves DXF, SVG and - once OpenCV has turned pixels into
segments - raster plans, so all three fail and succeed the same way.

The method, and why each step is there:

* Union the segments and buffer by a small snap tolerance, so two faces that
  were drawn a hair apart, or a wall that stops 2 mm short of the next, become
  one connected mass.
* Bridge the door gaps by extending each free wall end along its own direction
  to the next line, up to a door's width. A morphological closing is the
  textbook tool and does not work: a corridor is only a little wider than the
  door that opens onto it, so a closing that spans the door fills the corridor.
* Close the slit between a wall's two faces, which is thinner than any room.
* Each hole in the resulting mass is a room. It is grown back out to the wall
  centreline so neighbours share an edge, as they do in a plan the platform
  draws itself, then simplified and rectified onto the axes.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Sequence

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, unary_union

from aip.core.words import plural
from aip.domain.geometry import Vec2
from aip.domain.plan import RoomType
from aip.engines.architecture.importer import _LABELS, ParsedRoom, _clean_label, classify

#: How a labelled and an unlabelled face are trusted. An unlabelled face is a
#: guess from size and shape, and says so in its confidence.
LABELLED_CONFIDENCE = 0.8
GUESSED_CONFIDENCE = 0.4

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_MTEXT_STACK = re.compile(r"\\S([^;^/#]*)[/^#]([^;]*);")


def strip_cad_formatting(text: str) -> str:
    """Plain words from DXF TEXT/MTEXT content.

    MTEXT carries inline codes: ``\\fArial|b1;`` fonts, ``\\H2.5;`` heights,
    ``\\P`` paragraph breaks, ``{}`` groups, ``\\U+00B2`` and ``%%c`` symbols.
    None of it is part of the room's name.
    """
    out = text.replace("\\P", " ")           # \P is a paragraph break; \pxqc; is paragraph formatting
    out = re.sub(r"\\~", " ", out)
    out = _MTEXT_STACK.sub(r"\1/\2", out)
    out = re.sub(r"\\[fFHhWwQqTtCcAaSsp][^;]*;", "", out)
    out = re.sub(r"\\[LlOoKk]", "", out)
    out = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), out)
    out = out.replace("%%c", "dia ").replace("%%d", "deg").replace("%%p", "+-")
    out = out.replace("{", "").replace("}", "").replace("\\\\", "\\")
    return re.sub(r"\s+", " ", out).strip()


#: Words OCR runs together on a tight label.
_RUN_TOGETHER = re.compile(r"(?i)\b(master|guest|kids?|children|dining|living|family|servant)(?=[a-z]{3})")


def _label_words(text: str) -> str:
    """A label as words: formatting gone, measurements gone, run-together words split."""
    text = strip_cad_formatting(text)
    if not re.search(r"[A-Za-z]{2,}", text):
        return ""            # a number, a dimension, a size string: not a name
    text = _RUN_TOGETHER.sub(lambda m: m.group(1) + " ", text)
    return _clean_label(text)


_KEYWORDS = sorted({k.strip(" .") for keys, _ in _LABELS for k in keys if len(k.strip(" .")) >= 5})


def _fuzzy_type(label: str) -> RoomType | None:
    """A room type for a label OCR clipped or misread ("ORRIDO" for CORRIDOR).

    Only tried when the exact keyword match found nothing, and only against
    keywords long enough that a near-match means something.
    """
    for word in re.findall(r"[a-z]{4,}", label.lower()):
        close = difflib.get_close_matches(word, _KEYWORDS, n=1, cutoff=0.8)
        if close:
            return classify(close[0])
    return None


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _pair_thickness(segments: Sequence[tuple[Vec2, Vec2]], extent: float) -> float | None:
    """Wall thickness from the spacing of parallel faces, or None.

    A wall drawn as two lines shows up as many near-parallel pairs a few
    percent of the plan apart that overlap along their length. The modal
    spacing is the wall; the median of that bin keeps one odd pair from
    moving it.
    """
    arr = np.array([[a.x, a.y, b.x, b.y] for a, b in segments], dtype=float)
    length = np.hypot(arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1])
    keep = length >= 0.03 * extent
    arr, length = arr[keep], length[keep]
    if len(arr) < 4:
        return None
    if len(arr) > 1500:                      # the longest are the walls
        order = np.argsort(-length)[:1500]
        arr, length = arr[order], length[order]
    p0, p1 = arr[:, :2], arr[:, 2:]
    u = (p1 - p0) / length[:, None]
    n = len(arr)

    cross_uu = np.abs(u[:, None, 0] * u[None, :, 1] - u[:, None, 1] * u[None, :, 0])
    parallel = cross_uu < math.sin(math.radians(3.0))
    mid = (p0 + p1) / 2
    dm = mid[None, :, :] - mid[:, None, :]
    perp = np.abs(dm[..., 0] * u[:, None, 1] - dm[..., 1] * u[:, None, 0])
    # Overlap of j's span on i's axis.
    a_j = np.einsum("ijk,ik->ij", p0[None, :, :] - p0[:, None, :], u)
    b_j = np.einsum("ijk,ik->ij", p1[None, :, :] - p0[:, None, :], u)
    lo = np.maximum(0.0, np.minimum(a_j, b_j))
    hi = np.minimum(length[:, None], np.maximum(a_j, b_j))
    overlap = hi - lo
    shorter = np.minimum(length[:, None], length[None, :])
    ok = parallel & (overlap >= 0.3 * shorter) & (perp >= 0.0015 * extent) & (perp <= 0.05 * extent)
    ok &= ~np.eye(n, dtype=bool)
    spacing = perp[ok]
    if len(spacing) < 4:
        return None
    width = 0.0005 * extent
    bins = np.round(spacing / width).astype(int)
    values, counts = np.unique(bins, return_counts=True)
    best = values[int(np.argmax(counts))]
    near = spacing[np.abs(bins - best) <= 1]
    # A single lonely pair is a coincidence; a wall system repeats.
    if len(near) < 4:
        return None
    return float(np.median(near))


def _axis_group(parent: dict[tuple[int, int], tuple[int, int]], k: tuple[int, int]) -> tuple[int, int]:
    while parent[k] != k:
        parent[k] = parent[parent[k]]
        k = parent[k]
    return k


def rectify_polygons(
    polygons: Sequence[Sequence[Vec2]], tol: float, max_degrees: float = 6.0
) -> list[list[Vec2]]:
    """Snap near-axis-aligned edges exactly onto the axes, across all polygons.

    Edges within `max_degrees` of horizontal or vertical are made exactly so,
    and edges of different rooms that lie within `tol` of one another are made
    to share one coordinate, so neighbours meet along a single line instead of
    overlapping by a sliver or leaving one.
    """
    polys = [list(p) for p in polygons]
    result = [[[p.x, p.y] for p in poly] for poly in polys]
    limit = math.tan(math.radians(max_degrees))

    for axis in (0, 1):                      # 0: x of vertical edges; 1: y of horizontal edges
        parent: dict[tuple[int, int], tuple[int, int]] = {}
        for pi, poly in enumerate(polys):
            for vi in range(len(poly)):
                parent[(pi, vi)] = (pi, vi)
        for pi, poly in enumerate(polys):
            m = len(poly)
            for vi in range(m):
                a, b = poly[vi], poly[(vi + 1) % m]
                dx, dy = abs(b.x - a.x), abs(b.y - a.y)
                along, across = (dy, dx) if axis == 0 else (dx, dy)
                if along > 0 and across <= limit * along:
                    ra = _axis_group(parent, (pi, vi))
                    rb = _axis_group(parent, (pi, (vi + 1) % m))
                    parent[ra] = rb
        groups: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for key in parent:
            groups.setdefault(_axis_group(parent, key), []).append(key)
        snapped = []
        for members in groups.values():
            if len(members) < 2:
                continue
            value = float(np.mean([result[pi][vi][axis] for pi, vi in members]))
            snapped.append((value, members))
        snapped.sort(key=lambda g: g[0])
        # Single-linkage with a span cap, so a staircase of nearly equal
        # coordinates cannot chain into one.
        clusters: list[list[tuple[float, list[tuple[int, int]]]]] = []
        for item in snapped:
            if clusters and item[0] - clusters[-1][-1][0] <= tol and item[0] - clusters[-1][0][0] <= 2 * tol:
                clusters[-1].append(item)
            else:
                clusters.append([item])
        for cluster in clusters:
            value = float(np.mean([v for v, _ in cluster]))
            for _, members in cluster:
                for pi, vi in members:
                    result[pi][vi][axis] = value

    cleaned: list[list[Vec2]] = []
    for poly in result:
        pts: list[list[float]] = []
        for p in poly:                       # consecutive duplicates
            if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-9:
                pts.append(p)
        if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 1e-9:
            pts.pop()
        changed = True
        while changed and len(pts) > 3:      # vertices that no longer bend
            changed = False
            for i in range(len(pts)):
                a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
                cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
                scale = math.hypot(b[0] - a[0], b[1] - a[1]) * math.hypot(c[0] - b[0], c[1] - b[1])
                if scale == 0 or abs(cross) <= 1e-9 * max(scale, 1.0):
                    pts.pop(i)
                    changed = True
                    break
        cleaned.append([Vec2(p[0], p[1]) for p in pts])
    return cleaned


def guess_type(area: float, aspect: float, total_area: float) -> RoomType:
    """What an unlabelled room most likely is, from its size and shape.

    Long and thin is circulation; small is a wet room; anything else is more
    often a bedroom than not. It is a guess and is reported as one.
    """
    if aspect > 3.0:
        return RoomType.CORRIDOR
    if total_area > 0 and area < 0.06 * total_area:
        return RoomType.BATHROOM
    return RoomType.BEDROOM


def _aspect(poly: Polygon) -> float:
    rect = poly.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    s1 = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
    s2 = math.hypot(xs[2] - xs[1], ys[2] - ys[1])
    return max(s1, s2) / max(min(s1, s2), 1e-9)


def _min_side(poly: Polygon) -> float:
    rect = poly.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    return min(math.hypot(xs[1] - xs[0], ys[1] - ys[0]), math.hypot(xs[2] - xs[1], ys[2] - ys[1]))


def label_rooms(
    polygons: Sequence[Sequence[Vec2]],
    labels: Sequence[tuple[str, Vec2]],
    scores: Sequence[float] | None = None,
    *,
    geometry_confidence: float = LABELLED_CONFIDENCE,
) -> tuple[list[ParsedRoom], list[str]]:
    """Rooms from outlines and the text lying inside them.

    A text belongs to the smallest outline containing its anchor. Several texts
    in one room (a name and a size) are read top to bottom; numbers and size
    strings are not names and are dropped. An outline with no readable name gets
    a guessed type at low confidence, and one warning says how many.
    """
    shapes = [Polygon([(p.x, p.y) for p in poly]) for poly in polygons]
    held: list[list[tuple[float, float, str, float]]] = [[] for _ in shapes]
    for idx, (text, at) in enumerate(labels):
        words = _label_words(text)
        if not words:
            continue
        pt = Point(at.x, at.y)
        holders = [i for i, shape in enumerate(shapes) if shape.covers(pt)]
        if not holders:
            continue
        i = min(holders, key=lambda k: shapes[k].area)
        held[i].append((-at.y, at.x, words, scores[idx] if scores is not None else 1.0))

    total = sum(s.area for s in shapes)
    rooms: list[ParsedRoom] = []
    guessed = 0
    for poly, shape, found in zip(polygons, shapes, held, strict=True):
        found.sort()
        label = " ".join(w for _, _, w, _ in found).strip()
        if label:
            mean_score = sum(sc for *_, sc in found) / len(found)
            kind = None if classify(label) else _fuzzy_type(label)
            rooms.append(ParsedRoom(label=label, polygon=list(poly), type=kind,
                                    confidence=round(geometry_confidence * min(1.0, 0.5 + mean_score / 2)
                                                     if scores is not None else geometry_confidence, 3)))
        else:
            guessed += 1
            rooms.append(ParsedRoom(label="", polygon=list(poly),
                                    type=guess_type(shape.area, _aspect(shape), total),
                                    confidence=GUESSED_CONFIDENCE))
    warnings: list[str] = []
    if guessed:
        warnings.append(
            f"{plural(guessed, 'room')} had no readable name; their type was guessed from size and shape "
            f"(confidence {GUESSED_CONFIDENCE}). Check them, or put a text label inside each room."
        )
    return rooms, warnings


# ---------------------------------------------------------------------------
# Linework to rooms
# ---------------------------------------------------------------------------

_MITRE = {"join_style": "mitre", "mitre_limit": 2.0}


def bridge_door_gaps(
    segments: Sequence[tuple[Vec2, Vec2]], gap: float, snap: float
) -> list[LineString]:
    """Segments that close the doors: a free wall end extended to whatever it points at.

    A door is a place where a wall stops and, up to a door's width further
    along, starts again or meets another wall. So: find each wall end that
    touches nothing, look along its own direction for the nearest line within
    `gap`, and draw the missing piece.

    A morphological closing is the textbook tool and fails here. A corridor is
    barely wider than the door that opens onto it, so a closing wide enough to
    span the door fills the corridor as well, and the thin strip a door adds is
    attached to the thick fill, so no filter can tell the two apart afterwards.
    Following the wall's own direction cannot make that mistake.
    """
    lines = [LineString([(a.x, a.y), (b.x, b.y)]) for a, b in segments]
    keep = [i for i, ln in enumerate(lines) if ln.length > 1e-12]
    tree = STRtree(lines)
    sin_parallel = math.sin(math.radians(10.0))
    bridges: list[LineString] = []

    for i in keep:
        a, b = segments[i]
        length = lines[i].length
        for p, q in ((a, b), (b, a)):
            d = Vec2((p.x - q.x) / length, (p.y - q.y) / length)
            pt = Point(p.x, p.y)

            def joins(j: int, p=p, d=d, pt=pt, i=i) -> bool:
                """Does line j hold this end on to something, rather than just overlap the wall?"""
                if j == i or lines[j].distance(pt) > 1.5 * snap:
                    return False
                (ja, jb) = segments[j]
                dj = Vec2(jb.x - ja.x, jb.y - ja.y)
                lj = math.hypot(dj.x, dj.y) or 1.0
                if abs(d.x * dj.y - d.y * dj.x) / lj > sin_parallel:
                    return True                      # meets it at an angle: a corner or a T
                # Parallel: a continuation if it runs on past this end, a duplicate otherwise.
                reach = max((e.x - p.x) * d.x + (e.y - p.y) * d.y for e in (ja, jb))
                return reach > 2 * snap

            if any(joins(int(j)) for j in tree.query(pt.buffer(1.5 * snap))):
                continue
            tube = LineString([(p.x, p.y), (p.x + d.x * gap, p.y + d.y * gap)]).buffer(snap, cap_style="flat")
            nearest = None
            for j in tree.query(tube):
                j = int(j)
                if j == i:
                    continue
                hit = tube.intersection(lines[j])
                if hit.is_empty:
                    continue
                at = nearest_points(pt, hit)[1]
                t = (at.x - p.x) * d.x + (at.y - p.y) * d.y
                if t >= 2 * snap and (nearest is None or t < nearest):
                    nearest = t
            if nearest is not None:
                bridges.append(LineString([(p.x, p.y), (p.x + d.x * nearest, p.y + d.y * nearest)]))
    return bridges


def _faces(mass) -> list[Polygon]:
    polys = list(mass.geoms) if isinstance(mass, MultiPolygon) else [mass]
    return [Polygon(ring) for p in polys if isinstance(p, Polygon) for ring in p.interiors]


def rooms_from_linework(
    segments: Sequence[tuple[Vec2, Vec2]],
    labels: Sequence[tuple[str, Vec2]],
    *,
    door_gap: float | None = None,
    wall_thickness: float | None = None,
) -> tuple[list[ParsedRoom], list[str]]:
    """Rooms as the spaces enclosed by wall linework, in the segments' own units.

    `door_gap` is the widest opening to bridge, in those units (callers who know
    the units pass about one metre; otherwise it is a fraction of the plan).
    `wall_thickness` is a stroke width when the walls are drawn as thick strokes
    rather than as two faces; otherwise thickness is read from the spacing of
    parallel faces.
    """
    lines = [LineString([(a.x, a.y), (b.x, b.y)]) for a, b in segments if a.distance_to(b) > 1e-12]
    if not lines:
        return [], ["No wall linework was found."]
    mass = unary_union(lines)
    minx, miny, maxx, maxy = mass.bounds
    extent = max(maxx - minx, maxy - miny)
    if extent <= 0:
        return [], ["The wall linework has no extent."]

    snap = 0.004 * extent
    # About 9% of the plan: a door runs to roughly 1.05 m on a 12-15 m plan.
    # Bridging follows the wall's own direction, so a generous gap is safe.
    gap = door_gap or 0.09 * extent
    if wall_thickness is not None and wall_thickness <= 2 * snap:
        wall_thickness = None            # a hairline: the walls are faces, not strokes

    pair = None if wall_thickness else _pair_thickness([(a, b) for a, b in segments], extent)
    stroke = (wall_thickness or 0.0) / 2
    radius = max(snap, stroke)
    # Square or flat caps, never round, so wall ends meet cleanly at corners.
    cap = "flat" if stroke > snap else "square"
    bridges = bridge_door_gaps(segments, gap, snap)
    walls = unary_union([*lines, *bridges]).buffer(radius, cap_style=cap)
    footprint = (pair + 2 * radius) if pair else max(2 * radius, wall_thickness or 0.0)
    # Fill the slit between a wall's two faces; nothing wider than a wall's
    # own thickness is touched, so no room can close up.
    core = 0.75 * footprint
    bridged = walls.buffer(core, **_MITRE).buffer(-core, **_MITRE)

    # From the hole's edge back out to the wall centreline: the buffer, plus
    # half the wall when it was drawn as two faces.
    grow = radius + (pair / 2 if pair else 0.0)

    faces = []
    for face in _faces(bridged):
        shape = face.buffer(grow, **_MITRE).simplify(snap, preserve_topology=True)
        if isinstance(shape, Polygon) and not shape.is_empty and shape.is_valid:
            faces.append(shape)
    # An outline that encloses other rooms is the plot or the sheet frame.
    faces = [f for f in faces if sum(1 for o in faces if o is not f and f.contains(o.representative_point())) < 2]
    if not faces:
        return [], ["The wall linework does not enclose any room. Doors or openings wider than "
                    "the gap tolerance leave rooms open to the outside."]
    total = sum(f.area for f in faces)
    faces = [f for f in faces if f.area >= 0.015 * total and _min_side(f) >= 0.04 * extent]
    if not faces:
        return [], ["Every enclosed space was too small to be a room."]

    polys = rectify_polygons([[Vec2(x, y) for x, y in f.exterior.coords[:-1]] for f in faces],
                             tol=max(1.5 * snap, 0.5 * (pair or 0.0)))
    polys = [p for p in polys if len(p) >= 3]
    rooms, warnings = label_rooms(polys, list(labels))
    warnings.insert(0, f"Rooms were recovered from wall linework ({len(rooms)} enclosed spaces); "
                       f"{plural(len(bridges), 'door opening')} of up to {gap:.4g} units {'was' if len(bridges) == 1 else 'were'} treated as closed.")
    return rooms, warnings
