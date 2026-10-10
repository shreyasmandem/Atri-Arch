"""Bring an existing floor plan into the platform.

Everything downstream - the thirteen critics, the Vastu graph, the cost
takeoff, the airflow solve, the drawings and the CAD export - takes a
`FloorPlan`. So a plan an architect already has, drawn in AutoCAD or exported
from another tool or scanned from paper, only needs to become that one object
and it gets every analysis the generator's own schemes get.

Four sources, in order of how much they can be trusted:

* **JSON** - the platform's own schema. Lossless.
* **DXF** - rooms as closed polylines, names as TEXT inside them, which is what
  the platform itself writes. A draughtsperson's file has no such polylines:
  it has walls as LINEs with gaps at the doors. Those are read by finding the
  spaces the walls enclose (`recover.rooms_from_linework`), with the drawing's
  own `$INSUNITS` giving the scale. Read directly - the R12 subset the platform
  writes plus LWPOLYLINE and MTEXT, which cover what AutoCAD and its clones
  actually emit for a plan.
* **SVG** - rectangles, polygons and simple paths with text labels, or walls as
  stroked lines, with transforms applied down the tree. What plan tools and
  drawing apps export.
* **Image** - a scan or a photograph. Read on this machine with OpenCV and OCR
  (`raster`), and only if that finds nothing is a remote vision model asked,
  with a time limit. It is the least certain path and it says so in the
  result: every room carries a confidence, and the whole import carries a note
  on what was assumed and how the scale was read.

None of the parsers invent doors and windows the source did not draw. Where
they are absent the generator's own placer adds them under the same rules the
generated schemes obey - which is not a shortcut but a feature, since a plan
uploaded as room outlines comes back with code-compliant glazing and a legal
door tree - and the result records that it did so.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

from aip.domain.brief import ClientBrief, RoomRequirement, VastuStance
from aip.domain.geometry import (
    Direction,
    Vec2,
    bounding_box,
    centroid,
    point_in_polygon,
    polygon_area,
)
from aip.domain.plan import FloorPlan, Level, Room, RoomType, Site, StructuralSystem

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ParsedRoom:
    """A room as read from the source, before it becomes a domain object."""

    label: str
    polygon: list[Vec2]
    type: RoomType | None = None
    confidence: float = 1.0

    @property
    def area(self) -> float:
        return polygon_area(self.polygon)


@dataclass(slots=True)
class ImportResult:
    plan: FloorPlan
    source: str
    rooms_read: int
    rooms_kept: int
    unrecognised: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scale_note: str = ""
    openings_added: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "rooms_read": self.rooms_read,
            "rooms_kept": self.rooms_kept,
            "unrecognised": self.unrecognised,
            "warnings": self.warnings,
            "scale_note": self.scale_note,
            "openings_added": self.openings_added,
        }


class ImportError_(ValueError):
    """The file could not be read as a floor plan."""


# ---------------------------------------------------------------------------
# Label -> room type
# ---------------------------------------------------------------------------

#: Ordered: earlier entries win, so "master bed" is checked before "bed" and
#: "dining" before "din" would otherwise catch nothing.
_LABELS: tuple[tuple[tuple[str, ...], RoomType], ...] = (
    (("master bed", "master", "mbr", "m.bed", "m bed"), RoomType.MASTER_BEDROOM),
    (("children", "kids", "child"), RoomType.CHILDREN_BEDROOM),
    (("guest",), RoomType.GUEST_BEDROOM),
    (("bed", "br ", "bedroom"), RoomType.BEDROOM),
    (("living", "hall", "drawing", "lounge", "sitting"), RoomType.LIVING),
    (("family", "lvng"), RoomType.FAMILY),
    (("dining", "dine", "din."), RoomType.DINING),
    (("kitchen", "kit.", "kit ", "cook"), RoomType.KITCHEN),
    (("pantry",), RoomType.PANTRY),
    (("utility", "util", "wash", "laundry"), RoomType.UTILITY),
    (("store", "storage"), RoomType.STORE),
    (("puja", "pooja", "prayer", "mandir", "shrine"), RoomType.PUJA),
    (("powder",), RoomType.POWDER),
    (("toilet", "wc", "w.c", "lav"), RoomType.TOILET),
    (("bath", "attached", "att.", "ens", "shower"), RoomType.BATHROOM),
    (("study", "office", "work"), RoomType.STUDY),
    (("library",), RoomType.LIBRARY),
    (("foyer", "entry", "entrance", "porch", "vestibule"), RoomType.FOYER),
    (("lobby",), RoomType.LOBBY),
    (("verandah", "veranda", "sit-out", "sitout"), RoomType.VERANDAH),
    (("passage", "corridor", "hallway", "lobby"), RoomType.CORRIDOR),
    (("stair",), RoomType.STAIRCASE),
    (("balcony", "balc"), RoomType.BALCONY),
    (("terrace", "deck"), RoomType.TERRACE),
    (("courtyard", "court"), RoomType.COURTYARD),
    (("garage", "car", "parking", "park"), RoomType.GARAGE),
    (("servant", "maid", "staff"), RoomType.SERVANT),
    (("gym",), RoomType.GYM),
    (("theatre", "theater", "media"), RoomType.HOME_THEATRE),
    (("shaft", "duct"), RoomType.SHAFT),
)


#: What a drawing writes beside a room name: areas, dimensions, units,
#: numbering. Stripped so a room is named "Living", not "LIVING 19.43 SQ.M".
_UNIT_WORDS = {"sq", "sqm", "sq.m", "sq.m.", "m2", "m²", "sqft", "sq.ft", "sq.ft.", "sft",
               "ft", "ft2", "m", "mm", "x", "×", "by"}
_MEASURE = re.compile(r"^[\d.'\"x×X]+$")


def _clean_label(label: str) -> str:
    """The words of a label, without its measurements."""
    words = []
    for w in re.split(r"[\s()\[\]:,;/]+", label):
        if not w or _MEASURE.match(w) or w.lower().strip(".") in _UNIT_WORDS:
            continue
        words.append(w)
    return " ".join(words).strip()


def _room_name(r: ParsedRoom, ordinal: int) -> str:
    """A clean display name from a drawn label, numbered when repeated."""
    text = _clean_label(r.label)
    kind = r.type or RoomType.OTHER
    if kind is RoomType.OTHER:
        base = text or kind.label
    elif text and classify(text) is kind:
        base = text.title() if text.isupper() or text.islower() else text
    else:
        base = kind.label
    if ordinal > 1 and not re.search(r"\d", base):
        base = f"{base} {ordinal}"
    return base


def classify(label: str) -> RoomType | None:
    """Map a drawn label to a room type, or None when it is not a room."""
    text = label.strip().lower()
    if not text:
        return None
    # Strip areas and dimensions that share the label: "BEDROOM 12.5 m2".
    text = re.sub(r"[\d.]+\s*(m2|m²|sq\.?\s*m|sqft|sq\.?\s*ft|ft|m)\b", " ", text)
    text = re.sub(r"\d+['\"x×]\s*\d*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for keys, kind in _LABELS:
        for key in (keys if isinstance(keys, tuple) else (keys,)):
            if key in text:
                return kind
    return None


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------


def _dxf_pairs(text: str) -> list[tuple[int, str]]:
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    pairs: list[tuple[int, str]] = []
    for i in range(0, len(lines) - 1, 2):
        code = lines[i].strip()
        if not code.lstrip("-").isdigit():
            continue
        pairs.append((int(code), lines[i + 1].strip()))
    return pairs


#: $INSUNITS codes a plan can plausibly use, as (metres per unit, name).
_DXF_UNITS: dict[int, tuple[float, str]] = {
    1: (0.0254, "inches"), 2: (0.3048, "feet"), 4: (0.001, "millimetres"),
    5: (0.01, "centimetres"), 6: (1.0, "metres"),
}

#: Layers that carry the walls, and layers that never do.
_WALL_LAYER = re.compile(r"wall|mur|wand|a-wall", re.I)
_NOT_WALL_LAYER = re.compile(r"dim|anno|text|furn|door|hatch|grid|axis|title", re.I)


def dxf_units(text: str) -> tuple[float, str] | None:
    """The drawing's own statement of its units ($INSUNITS), when it makes one."""
    pairs = _dxf_pairs(text)
    for i, (code, value) in enumerate(pairs[:-1]):
        if code == 9 and value == "$INSUNITS":
            try:
                return _DXF_UNITS.get(int(pairs[i + 1][1]))
            except ValueError:
                return None
    return None


def parse_dxf(text: str) -> tuple[list[ParsedRoom], list[str]]:
    """Rooms from closed polylines, or else from wall linework, labelled by the text inside them.

    A file the platform wrote has one closed polyline per room. A file from a
    draughtsperson has walls as lines and the rooms are what they enclose; that
    is read by `rooms_from_linework` when the closed-outline path finds fewer
    than two rooms.
    """
    pairs = _dxf_pairs(text)
    polylines: list[tuple[str, list[Vec2], bool]] = []   # (layer, points, closed)
    texts: list[tuple[str, Vec2]] = []
    lines_by_layer: dict[str, list[tuple[Vec2, Vec2]]] = {}

    section = ""
    i = 0
    n = len(pairs)
    while i < n:
        code, value = pairs[i]
        if code != 0:
            i += 1
            continue
        entity = value
        i += 1
        attrs: dict[int, list[str]] = {}
        vertices: list[Vec2] = []
        # Collect this entity's attributes up to the next entity marker.
        while i < n and pairs[i][0] != 0:
            c, v = pairs[i]
            attrs.setdefault(c, []).append(v)
            i += 1

        if entity == "SECTION":
            section = (attrs.get(2) or [""])[0]
            continue
        if entity == "ENDSEC":
            section = ""
            continue
        # Block definitions hold furniture and symbols drawn once and inserted
        # many times; their geometry is not part of the plan.
        skip = section in ("BLOCKS", "CLASSES", "OBJECTS", "TABLES", "HEADER")

        if entity == "POLYLINE":
            layer = attrs.get(8, ["0"])[0]
            closed = bool(int(attrs.get(70, ["0"])[0]) & 1)
            # Vertices follow as their own entities until SEQEND.
            while i < n and pairs[i] == (0, "VERTEX"):
                i += 1
                vx = vy = None
                while i < n and pairs[i][0] != 0:
                    c, v = pairs[i]
                    if c == 10:
                        vx = float(v)
                    elif c == 20:
                        vy = float(v)
                    i += 1
                if vx is not None and vy is not None:
                    vertices.append(Vec2(vx, vy))
            if i < n and pairs[i] == (0, "SEQEND"):
                i += 1
                while i < n and pairs[i][0] != 0:
                    i += 1
            if not skip:
                polylines.append((layer, vertices, closed))

        elif skip:
            continue

        elif entity == "LWPOLYLINE":
            layer = attrs.get(8, ["0"])[0]
            closed = bool(int(attrs.get(70, ["0"])[0]) & 1)
            xs = [float(v) for v in attrs.get(10, [])]
            ys = [float(v) for v in attrs.get(20, [])]
            vertices = [Vec2(x, y) for x, y in zip(xs, ys, strict=False)]
            polylines.append((layer, vertices, closed))

        elif entity in ("TEXT", "MTEXT"):
            # MTEXT splits long content into group-3 chunks before the final group 1.
            content = _strip_mtext(" ".join(attrs.get(3, []) + attrs.get(1, [])))
            try:
                # A TEXT with an alignment is placed by its second point.
                aligned = entity == "TEXT" and 11 in attrs and (
                    int(attrs.get(72, ["0"])[0]) or int(attrs.get(73, ["0"])[0]))
                x = float(attrs.get(11 if aligned else 10, ["0"])[0])
                y = float(attrs.get(21 if aligned else 20, ["0"])[0])
            except ValueError:
                continue
            if content:
                texts.append((content, Vec2(x, y)))

        elif entity == "LINE":
            layer = attrs.get(8, ["0"])[0]
            try:
                a = Vec2(float(attrs[10][0]), float(attrs[20][0]))
                b = Vec2(float(attrs[11][0]), float(attrs[21][0]))
                lines_by_layer.setdefault(layer, []).append((a, b))
            except (KeyError, ValueError):
                pass

    warnings: list[str] = []
    closed_shapes = [
        (layer, pts) for layer, pts, closed in polylines
        if len(pts) >= 3 and (closed or pts[0].distance_to(pts[-1]) < 1e-6)
    ]

    # Layer names carry the drawing's own intent. A polyline on a wall,
    # column, grid, dimension or annotation layer is never a room, whatever
    # its shape; one on an area, room or space layer always is. When the
    # file uses room layers, trust them exclusively; when it does not, fall
    # back to shape, and let the size filter after scaling drop the columns.
    def kind_of(layer: str) -> str:
        name = layer.upper()
        if any(k in name for k in ("AREA", "ROOM", "SPACE", "FLOR-IDEN", "ZONE")):
            return "room"
        if any(k in name for k in ("WALL", "COLS", "COL", "GRID", "DIM", "ANNO", "TEXT",
                                   "DOOR", "GLAZ", "WIND", "FURN", "TITLE", "HATCH")):
            return "not-room"
        return "unknown"

    on_room_layers = [(layer, pts) for layer, pts in closed_shapes if kind_of(layer) == "room"]
    if on_room_layers:
        candidates = on_room_layers
    else:
        candidates = [(layer, pts) for layer, pts in closed_shapes if kind_of(layer) != "not-room"]
        if candidates:
            warnings.append(
                "No room or area layer was found; rooms were taken from closed outlines "
                "on other layers. Put room boundaries on an A-AREA layer for a reliable read."
            )

    rooms: list[ParsedRoom] = []
    for layer, pts in candidates:
        if pts[0].distance_to(pts[-1]) < 1e-6:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        box = bounding_box(pts)
        # A closed outline much longer than it is wide is a wall poché.
        if kind_of(layer) != "room" and min(box.width, box.height) < max(box.width, box.height) * 0.06:
            continue
        rooms.append(ParsedRoom(label="", polygon=list(pts)))

    if len(rooms) < 2:
        recovered = _dxf_from_linework(polylines, lines_by_layer, texts, dxf_units(text))
        if recovered is not None:
            return recovered
        if not rooms:
            raise ImportError_(
                "No closed room outlines found, and the walls do not enclose any room. "
                "Export rooms as closed polylines (one per room) with the room name as "
                "text inside each, or close the door gaps in the wall layer and try again."
            )

    # Attach each text to the smallest room that contains it: dimension
    # strings sit outside rooms and are ignored; a title block is not a room.
    for content, at in texts:
        holders = [r for r in rooms if point_in_polygon(at, r.polygon)]
        if not holders:
            continue
        holder = min(holders, key=lambda r: r.area)
        holder.label = (holder.label + " " + content).strip() if holder.label else content

    return rooms, warnings


def _strip_mtext(content: str) -> str:
    from aip.engines.architecture.recover import strip_cad_formatting

    return strip_cad_formatting(content)


def _dxf_from_linework(
    polylines: list[tuple[str, list[Vec2], bool]],
    lines_by_layer: dict[str, list[tuple[Vec2, Vec2]]],
    texts: list[tuple[str, Vec2]],
    units: tuple[float, str] | None,
) -> tuple[list[ParsedRoom], list[str]] | None:
    """Rooms from the wall layers' lines, or None when they enclose fewer than two."""
    from aip.engines.architecture.recover import rooms_from_linework

    by_layer: dict[str, list[tuple[Vec2, Vec2]]] = {k: list(v) for k, v in lines_by_layer.items()}
    for layer, pts, closed in polylines:
        edges = list(zip(pts, pts[1:], strict=False))
        if closed and len(pts) > 2:
            edges.append((pts[-1], pts[0]))
        by_layer.setdefault(layer, []).extend(edges)

    wall_layers = [k for k in by_layer if _WALL_LAYER.search(k)]
    layers = wall_layers or [k for k in by_layer if not _NOT_WALL_LAYER.search(k)]
    segments = [seg for k in layers for seg in by_layer[k]]
    if len(segments) < 4:
        return None

    # About a metre in the drawing's own units, when it says what they are.
    door_gap = 1.2 / units[0] if units else None
    rooms, warnings = rooms_from_linework(segments, texts, door_gap=door_gap)
    if len(rooms) < 2:
        return None
    where = ", ".join(sorted(layers)) if wall_layers else "all layers except annotation and furniture"
    warnings.insert(0, f"No closed room outlines were drawn, so rooms were read from wall linework on {where}.")
    return rooms, warnings


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------


def _svg_path_points(d: str) -> list[Vec2] | None:
    """Absolute M/L/H/V/Z paths only - what plan exporters write for rooms."""
    tokens = re.findall(r"[MLHVZmlhvz]|-?\d*\.?\d+(?:e-?\d+)?", d)
    points: list[Vec2] = []
    cmd = ""
    x = y = 0.0
    k = 0
    while k < len(tokens):
        t = tokens[k]
        if t.isalpha():
            cmd = t
            k += 1
            if cmd in "Zz":
                break
            continue
        try:
            if cmd in "ML":
                x, y = float(t), float(tokens[k + 1])
                k += 2
            elif cmd in "ml":
                x, y = x + float(t), y + float(tokens[k + 1])
                k += 2
            elif cmd == "H":
                x = float(t)
                k += 1
            elif cmd == "h":
                x += float(t)
                k += 1
            elif cmd == "V":
                y = float(t)
                k += 1
            elif cmd == "v":
                y += float(t)
                k += 1
            else:
                return None   # curves: not a room outline we can trust
        except (IndexError, ValueError):
            return None
        points.append(Vec2(x, y))
    return points if len(points) >= 3 else None


_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

#: (a, b, c, d, e, f): x' = a*x + c*y + e, y' = b*x + d*y + f, as in SVG.
Matrix = tuple[float, float, float, float, float, float]
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mat_mul(m: Matrix, n: Matrix) -> Matrix:
    """The transform that applies `n` first and then `m`."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def _parse_transform(text: str | None) -> Matrix:
    """A `transform` attribute - matrix, translate, scale, rotate, skew, any number of them."""
    m = _IDENTITY
    for name, args in re.findall(r"([A-Za-z]+)\s*\(([^)]*)\)", text or ""):
        v = [float(x) for x in re.findall(_NUM, args)]
        name = name.lower()
        if name == "matrix" and len(v) == 6:
            t: Matrix = (v[0], v[1], v[2], v[3], v[4], v[5])
        elif name == "translate" and v:
            t = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            t = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0], 0.0, 0.0)
        elif name == "rotate" and v:
            c, s = math.cos(math.radians(v[0])), math.sin(math.radians(v[0]))
            t = (c, s, -s, c, 0.0, 0.0)
            if len(v) >= 3:                    # about (cx, cy)
                t = _mat_mul(_mat_mul((1.0, 0.0, 0.0, 1.0, v[1], v[2]), t),
                             (1.0, 0.0, 0.0, 1.0, -v[1], -v[2]))
        elif name == "skewx" and v:
            t = (1.0, 0.0, math.tan(math.radians(v[0])), 1.0, 0.0, 0.0)
        elif name == "skewy" and v:
            t = (1.0, math.tan(math.radians(v[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = _mat_mul(m, t)
    return m


def _apply(m: Matrix, p: Vec2) -> Vec2:
    return Vec2(m[0] * p.x + m[2] * p.y + m[4], m[1] * p.x + m[3] * p.y + m[5])


def _svg_path_edges(d: str) -> list[tuple[list[Vec2], bool]]:
    """Sub-paths of a path as (points, closed). M/L/H/V/Z in both cases; a
    curve (C, S, Q, T, A) is approximated by its end point, which is all a
    wall drawn with a door-swing arc needs."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUM, d)
    out: list[tuple[list[Vec2], bool]] = []
    pts: list[Vec2] = []
    x = y = sx = sy = 0.0
    cmd = ""
    k = 0
    arity = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7}

    def flush(closed: bool) -> None:
        nonlocal pts
        if len(pts) >= 2:
            out.append((pts, closed))
        pts = []

    while k < len(tokens):
        t = tokens[k]
        if t.isalpha():
            cmd = t
            k += 1
            if cmd in "Zz":
                flush(True)
                x, y = sx, sy
                pts = [Vec2(sx, sy)]           # a command after Z continues from the start
            continue
        low = cmd.lower()
        if low not in arity or k + arity[low] > len(tokens):
            break
        try:
            v = [float(tokens[k + j]) for j in range(arity[low])]
        except ValueError:
            break
        k += arity[low]
        rel = cmd.islower()
        if low == "h":
            x = x + v[0] if rel else v[0]
        elif low == "v":
            y = y + v[0] if rel else v[0]
        else:
            ex, ey = v[-2], v[-1]
            x, y = (x + ex, y + ey) if rel else (ex, ey)
        if low == "m":
            flush(False)
            sx, sy = x, y
            cmd = "l" if rel else "L"          # further pairs after M are implicit L
        if not pts or (x, y) != (pts[-1].x, pts[-1].y):
            pts.append(Vec2(x, y))
    flush(False)
    return out


def _style_of(node: ElementTree.Element, inherited: dict[str, str]) -> dict[str, str]:
    """Presentation properties this importer cares about, inherited down the tree."""
    props = dict(inherited)
    for key in ("stroke", "stroke-width", "display", "visibility"):
        if node.get(key) is not None:
            props[key] = node.get(key, "").strip()
    for decl in (node.get("style") or "").split(";"):
        if ":" in decl:
            key, _, value = decl.partition(":")
            if key.strip() in ("stroke", "stroke-width", "display", "visibility"):
                props[key.strip()] = value.strip()
    return props


def _float(value: str | None, default: float = 0.0) -> float:
    """A length attribute; a percentage (the page-sized background rect) is not a length here."""
    text = (value or "").strip()
    if text.endswith("%"):
        return default
    match = re.match(_NUM, text)
    return float(match.group(0)) if match else default


_SVG_SKIP = {"defs", "clippath", "mask", "symbol", "pattern", "marker", "style", "title", "desc",
             "metadata", "lineargradient", "radialgradient", "filter"}


def parse_svg(text: str) -> tuple[list[ParsedRoom], list[str]]:
    """Rooms from an SVG: closed shapes when there are some, else enclosed by wall lines.

    Transforms are composed down the element tree, so a plan inside a
    translated, scaled or rotated group lands where it is drawn. Closed
    rect/polygon/path outlines are tried first; a file whose walls are strokes
    (`<line>`s with a stroke width) is read by `rooms_from_linework`.
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ImportError_(f"Not well-formed SVG: {exc}") from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    shapes: list[list[Vec2]] = []
    texts: list[tuple[str, Vec2]] = []
    # Linework as (a, b, stroke width in user space).
    strokes: list[tuple[Vec2, Vec2, float]] = []
    warnings: list[str] = []

    def walk(node: ElementTree.Element, m: Matrix, inherited: dict[str, str]) -> None:
        tag = local(node.tag)
        if tag in _SVG_SKIP:
            return
        m = _mat_mul(m, _parse_transform(node.get("transform")))
        props = _style_of(node, inherited)
        if props.get("display") == "none" or props.get("visibility") in ("hidden", "collapse"):
            return
        # How much a transform stretches a stroke: the square root of its area scale.
        stretch = math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0
        visible = props.get("stroke", "") != "none"
        width = _float(props.get("stroke-width"), 1.0) * stretch

        def edges(pts: list[Vec2], closed: bool) -> None:
            if not visible:
                return
            pairs = list(zip(pts, pts[1:], strict=False)) + ([(pts[-1], pts[0])] if closed and len(pts) > 2 else [])
            strokes.extend((a, b, width) for a, b in pairs)

        try:
            if tag == "rect":
                x, y = _float(node.get("x")), _float(node.get("y"))
                w, h = _float(node.get("width")), _float(node.get("height"))
                if w > 0 and h > 0:
                    pts = [_apply(m, p) for p in (Vec2(x, y), Vec2(x + w, y), Vec2(x + w, y + h), Vec2(x, y + h))]
                    shapes.append(pts)
                    edges(pts, True)
            elif tag in ("polygon", "polyline"):
                nums = [float(v) for v in re.findall(_NUM, node.get("points", ""))]
                pts = [_apply(m, Vec2(nums[i], nums[i + 1])) for i in range(0, len(nums) - 1, 2)]
                if tag == "polygon" and len(pts) >= 3:
                    shapes.append(pts)
                edges(pts, tag == "polygon")
            elif tag == "line":
                a = _apply(m, Vec2(_float(node.get("x1")), _float(node.get("y1"))))
                b = _apply(m, Vec2(_float(node.get("x2")), _float(node.get("y2"))))
                edges([a, b], False)
            elif tag == "path":
                d = node.get("d", "")
                pts = _svg_path_points(d)
                if pts:
                    shapes.append([_apply(m, p) for p in pts])
                for sub, closed in _svg_path_edges(d):
                    edges([_apply(m, p) for p in sub], closed)
            elif tag == "text":
                content = "".join(node.itertext()).strip()
                if content:
                    first = node if node.get("x") is not None else next(
                        (c for c in node.iter() if c.get("x") is not None), node)
                    at = _apply(m, Vec2(_float((first.get("x") or "0").replace(",", " ").split()[0]),
                                        _float((first.get("y") or "0").replace(",", " ").split()[0])))
                    texts.append((content, at))
        except (ValueError, IndexError):
            pass
        for child in node:
            walk(child, m, props)

    walk(root, _IDENTITY, {})

    # SVG's y axis points down; the platform's points up. Flip once here.
    everything = [p for s in shapes for p in s] + [p for a, b, _ in strokes for p in (a, b)]
    top = max((p.y for p in everything), default=0.0)

    def flip(pts: list[Vec2]) -> list[Vec2]:
        return [Vec2(p.x, top - p.y) for p in pts]

    texts = [(t, Vec2(at.x, top - at.y)) for t, at in texts]
    shapes = [flip(s) for s in shapes]

    rooms: list[ParsedRoom] = []
    for pts in shapes:
        box = bounding_box(pts)
        if min(box.width, box.height) < max(box.width, box.height) * 0.06:
            continue
        rooms.append(ParsedRoom(label="", polygon=pts))

    # The outermost shape that contains every other is the plot or the
    # building outline, not a room.
    if len(rooms) > 1:
        biggest = max(rooms, key=lambda r: r.area)
        if all(point_in_polygon(centroid(r.polygon), biggest.polygon) for r in rooms if r is not biggest):
            rooms.remove(biggest)

    if len(rooms) < 2:
        recovered = _svg_from_strokes(strokes, texts, top)
        if recovered is not None:
            return recovered
        if not rooms:
            raise ImportError_(
                "No room shapes found in the SVG: no closed rect, polygon or path outlines, "
                "and no wall lines that enclose rooms. Export the plan with one closed shape "
                "per room, or draw the walls as continuous lines with the door gaps no wider "
                "than a door."
            )

    for content, at in texts:
        holders = [r for r in rooms if point_in_polygon(at, r.polygon)]
        if holders:
            holder = min(holders, key=lambda r: r.area)
            holder.label = (holder.label + " " + content).strip() if holder.label else content

    return rooms, warnings


def _svg_from_strokes(
    strokes: list[tuple[Vec2, Vec2, float]], texts: list[tuple[str, Vec2]], top: float
) -> tuple[list[ParsedRoom], list[str]] | None:
    """Rooms enclosed by an SVG's stroked wall lines, or None when they enclose fewer than two."""
    from aip.engines.architecture.recover import rooms_from_linework

    if len(strokes) < 4:
        return None
    widths = sorted(w for _, _, w in strokes)
    median = widths[len(widths) // 2]
    # Where the widths split into a thick and a thin population, the thin
    # lines are dimension leaders and hatching, not walls.
    kept = [(a, b, w) for a, b, w in strokes if w >= 0.25 * median]
    segments = [(Vec2(a.x, top - a.y), Vec2(b.x, top - b.y)) for a, b, _ in kept]
    thickness = sorted(w for _, _, w in kept)[len(kept) // 2]
    rooms, warnings = rooms_from_linework(segments, texts, wall_thickness=thickness)
    if len(rooms) < 2:
        return None
    if len(kept) < len(strokes):
        warnings.append(f"Ignored {len(strokes) - len(kept)} thin line(s) as dimension or hatch lines.")
    return rooms, warnings


# ---------------------------------------------------------------------------
# Image, via a vision model
# ---------------------------------------------------------------------------

_IMAGE_PROMPT = """You are reading an architectural floor plan image.

Return ONLY a JSON object, no prose, in this exact shape:
{
  "plot_width_m": <number or null>,
  "plot_depth_m": <number or null>,
  "north": "<N|NE|E|SE|S|SW|W|NW|unknown>",
  "rooms": [
    {"name": "<label as written>", "x": <left, 0-1>, "y": <top, 0-1>, "w": <width, 0-1>, "h": <height, 0-1>, "confidence": <0-1>}
  ]
}

Coordinates are fractions of the drawing's own bounding box (0,0 = top-left,
1,1 = bottom-right). Include every room you can read; use its written label.
Read dimension strings to fill plot_width_m and plot_depth_m if they are
present; otherwise null. Do not include the plot boundary as a room."""


async def parse_image(data: bytes, mime: str) -> tuple[list[ParsedRoom], list[str], dict[str, object]]:
    """Ask a vision model for the rooms, then treat its answer like any parser's."""
    import base64

    from aip.core.llm import get_router, user
    from aip.core.providers import Capability

    uri = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
    router = get_router()
    response = await router.complete(
        [user(_IMAGE_PROMPT, images=[uri])],
        capability=Capability.VISION,
        temperature=0.1,
        max_tokens=2500,
        latency_sensitive=False,
    )
    if response.degraded:
        # The router fell through to its offline stub: every free vision model
        # was rate limited or down. Say that, not "the model answered badly".
        raise ImportError_(
            "No free vision model was reachable just now (the free tiers rate-limit "
            "under load). Try again in a minute, or upload the DXF or SVG of this "
            "plan, which needs no model at all."
        )
    text = response.text.strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ImportError_("The vision model did not return a room list for this image.")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ImportError_(f"The vision model's answer was not valid JSON: {exc}") from exc

    rooms: list[ParsedRoom] = []
    for item in payload.get("rooms", []):
        try:
            x, y, w, h = (float(item[k]) for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        # Fractions, y-down. Flip to y-up here; scaling happens later.
        top = 1.0 - y
        bottom = 1.0 - (y + h)
        rooms.append(ParsedRoom(
            label=str(item.get("name", "")),
            polygon=[Vec2(x, bottom), Vec2(x + w, bottom), Vec2(x + w, top), Vec2(x, top)],
            confidence=max(0.0, min(1.0, float(item.get("confidence", 0.6)))),
        ))
    if not rooms:
        raise ImportError_("The vision model found no rooms in this image.")

    meta = {
        "model": getattr(response, "model", ""),
        "plot_width_m": payload.get("plot_width_m"),
        "plot_depth_m": payload.get("plot_depth_m"),
        "north": payload.get("north", "unknown"),
    }
    warnings = [
        "Rooms were read from an image by a vision model. Positions are approximate; "
        "each room carries the model's own confidence, and the plot size should be "
        "confirmed against the drawing's dimension strings."
    ]
    return rooms, warnings, meta


# ---------------------------------------------------------------------------
# Scaling and assembly
# ---------------------------------------------------------------------------


def _scale_to_plot(
    rooms: list[ParsedRoom],
    plot_width: float | None,
    plot_depth: float | None,
    *,
    unitless: bool,
    setbacks: tuple[float, float, float, float],
    unit_scale: tuple[float, str] | None = None,
) -> tuple[list[ParsedRoom], str]:
    """Bring source units to metres.

    A DXF or plan JSON carries units, even if the header does not say which;
    an SVG or an image carries none. The two are treated differently on
    purpose. A drawing with units is only ever *shrunk* to fit the buildable
    footprint, never inflated to fill it - inflating a 9 m house to a 12 m
    plot is how the first round-trip came back 54% larger than it went out.
    A unitless drawing has nothing to be faithful to, so it is fitted to the
    footprint exactly. A source that states its own scale (a DXF's $INSUNITS,
    # a raster plan whose dimension strings were read) is a drawing with units
    # whatever its format, and is scaled as one.
    """
    # Measure the extent from shapes that are plausibly rooms. Wall slivers,
    # door swings and frame lines survive to this point in a vector export
    # and, being spread across the whole sheet, inflate the extent so the
    # real rooms are fitted small. Anything under 2% of the largest shape is
    # not a room and does not get a say in the scale.
    largest = max((r.area for r in rooms), default=0.0)
    plausible = [r for r in rooms if r.area >= 0.02 * largest] or rooms
    box = bounding_box([p for r in plausible for p in r.polygon])
    extent = max(box.width, box.height)
    if extent <= 0:
        raise ImportError_("The rooms have no extent.")

    front, rear, left, right = setbacks
    buildable_w = (plot_width - left - right) if plot_width else None
    buildable_d = (plot_depth - front - rear) if plot_depth else None

    def fit_scale() -> float:
        sx = buildable_w / box.width if buildable_w and box.width else float("inf")
        sy = buildable_d / box.height if buildable_d and box.height else float("inf")
        return min(sx, sy)

    if unitless and unit_scale is None:
        if buildable_w and buildable_d:
            scale = fit_scale()
            note = (f"Fitted the drawing to the {buildable_w:.1f} x {buildable_d:.1f} m "
                    f"buildable footprint inside the stated plot.")
        else:
            # Nothing to fit to: assume a typical plot so areas are at least plausible.
            scale = 9.0 / extent
            note = "No plot size given for a unitless drawing; scaled so the longer side is 9 m."
    else:
        if unit_scale is not None:
            scale, note = unit_scale[0], f"Units taken from the file: {unit_scale[1]}."
        elif extent > 2000:
            scale, note = 0.001, "Extent exceeds 2000 units; read as millimetres."
        elif extent > 200:
            scale, note = 0.3048 / 12, "Extent in the hundreds; read as inches."
        elif extent > 60:
            scale, note = 0.3048, "Extent in the tens; read as feet."
        else:
            scale, note = 1.0, "Read as metres."
        # A drawing with units already encodes where its walls sit relative
        # to the boundary; imposing default setbacks on top would shrink a
        # correctly drawn house. Shrink only if it would not fit the plot at
        # all, which means the units were misread.
        if plot_width and plot_depth:
            sx = plot_width / box.width / scale if box.width else float("inf")
            sy = plot_depth / box.height / scale if box.height else float("inf")
            shrink = min(sx, sy)
            if shrink < 0.999:
                scale *= shrink
                note += (f" Shrunk by {(1 - shrink) * 100:.0f}% to fit the "
                         f"{plot_width:.1f} x {plot_depth:.1f} m plot.")

    origin = Vec2(box.min_x, box.min_y)
    scaled = [
        ParsedRoom(
            label=r.label,
            polygon=[Vec2((p.x - origin.x) * scale, (p.y - origin.y) * scale) for p in r.polygon],
            type=r.type,
            confidence=r.confidence,
        )
        for r in rooms
    ]
    return scaled, note


def assemble(
    rooms: list[ParsedRoom],
    *,
    source: str,
    plot_width: float | None,
    plot_depth: float | None,
    road: Direction,
    north_angle: float,
    name: str,
    warnings: list[str],
    setbacks: tuple[float, float, float, float] = (3.0, 1.5, 1.2, 1.2),
    add_openings: bool = True,
    unit_scale: tuple[float, str] | None = None,
) -> ImportResult:
    """Turn parsed rooms into a full FloorPlan with walls and openings."""
    from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator

    read = len(rooms)
    unrecognised: list[str] = []
    kept: list[ParsedRoom] = []
    for r in rooms:
        r.type = r.type or classify(r.label)
        if r.type is None:
            if r.label.strip():
                unrecognised.append(r.label.strip())
                r.type = RoomType.OTHER
                kept.append(r)
            else:
                # An unlabelled outline of usable size is still a room; call
                # it so rather than dropping the area it occupies.
                r.type = RoomType.OTHER
                unrecognised.append("(unlabelled)")
                kept.append(r)
        else:
            kept.append(r)
    if not kept:
        raise ImportError_("None of the outlines could be used as rooms.")

    kept, scale_note = _scale_to_plot(
        kept, plot_width, plot_depth, unitless=source in ("svg", "image"), setbacks=setbacks,
        unit_scale=unit_scale,
    )
    # Only now are the units metres, so only now can a column footprint or
    # a stray rectangle be told from a room by size.
    tiny = [r for r in kept if r.area < 1.2]
    if tiny:
        kept = [r for r in kept if r.area >= 1.2]
        unrecognised = [u for u in unrecognised if u != "(unlabelled)"] + (
            ["(unlabelled)"] if any(not r.label.strip() for r in kept if r.type is RoomType.OTHER) else []
        )
        warnings.append(f"Dropped {len(tiny)} outline(s) under 1.2 m2 as columns or fragments.")
    if not kept:
        raise ImportError_("Every outline was too small to be a room after scaling.")
    extent = bounding_box([p for r in kept for p in r.polygon])
    if min(extent.width, extent.height) < 3.0:
        raise ImportError_(
            f"After scaling the plan is only {extent.width:.1f} x {extent.height:.1f} m. "
            f"Supply the plot size so the drawing can be scaled correctly."
        )

    # The site: the stated plot, or the room extent plus setbacks. When the
    # plot is assumed, assume one the house could lawfully stand on: a
    # drawing padded by bare setbacks lands at 60.2% coverage and a
    # disqualifying finding about a plot nobody stated is noise, not review.
    front, rear, left, right = setbacks
    pw = plot_width or (extent.width + left + right)
    pd = plot_depth or (extent.height + front + rear)
    if not (plot_width and plot_depth):
        footprint = sum(r.area for r in kept)
        limit = 0.6 * 0.95  # the statutory 60%, with room to spare for wall thickness
        if footprint > limit * pw * pd:
            grow = (footprint / (limit * pw * pd)) ** 0.5
            pw, pd = round(pw * grow, 2), round(pd * grow, 2)
        warnings.append(
            f"Plot size was not given; a {pw:.1f} x {pd:.1f} m plot was assumed around the "
            f"drawing. Enter the real plot for the setback and coverage checks to mean anything."
        )
    site = Site(
        boundary=[Vec2(0, 0), Vec2(pw, 0), Vec2(pw, pd), Vec2(0, pd)],
        north_angle=north_angle,
        road_directions=[road],
        setback_front=front, setback_rear=rear, setback_left=left, setback_right=right,
    )
    # Place the rooms on the site. A unitless drawing sits inside the
    # setbacks; a drawing with units is centred in the plot so that the
    # margins it was drawn with are the margins it keeps.
    if source in ("svg", "image"):
        inner_w = max(0.1, pw - left - right)
        inner_d = max(0.1, pd - front - rear)
        dx = left + max(0.0, (inner_w - extent.width) / 2) - extent.min_x
        dy = rear + max(0.0, (inner_d - extent.height) / 2) - extent.min_y
    else:
        dx = max(0.0, (pw - extent.width) / 2) - extent.min_x
        dy = max(0.0, (pd - extent.height) / 2) - extent.min_y
        # Record the margins the drawing actually has as the site's setbacks,
        # so compliance judges what was drawn rather than a default.
        left = right = round(max(0.0, (pw - extent.width) / 2), 2)
        rear = round(max(0.0, (pd - extent.height) / 2), 2)
        front = rear
        site.setback_front = site.setback_rear = rear
        site.setback_left = site.setback_right = left

    domain_rooms: list[Room] = []
    seen: dict[RoomType, int] = {}
    for r in kept:
        seen[r.type] = seen.get(r.type, 0) + 1
        domain_rooms.append(Room(
            name=_room_name(r, seen[r.type]),
            type=r.type,
            polygon=[Vec2(p.x + dx, p.y + dy) for p in r.polygon],
            level=0,
            ceiling_height=3.0,
            metadata={"imported": True, "label": r.label, "confidence": r.confidence},
        ))

    # A brief that describes what was uploaded, so the generator's wall and
    # opening logic - and later the critics - have the programme to work with.
    requirements = [
        RoomRequirement(type=r.type, preferred_area=round(max(r.area, 1.0), 2),
                        needs_daylight=r.type.is_habitable,
                        attached_bathroom=(r.type is RoomType.MASTER_BEDROOM))
        for r in kept
    ]
    brief = ClientBrief(
        project_name=name, site=site, levels=1, requirements=requirements,
        vastu=VastuStance.BALANCED,
    )
    generator = LayoutGenerator(brief, GeneratorConfig(population=4, generations=1, seed=1))
    envelope = bounding_box([p for r in domain_rooms for p in r.polygon])
    walls = generator._build_walls(domain_rooms, envelope, 0)

    plan = FloorPlan(
        name=name,
        site=site,
        levels=[Level(index=0, elevation=0.0, floor_to_floor=3.15, rooms=domain_rooms, walls=walls)],
        structural_system=StructuralSystem.RCC_FRAME,
    )
    plan.column_grid = generator._build_column_grid(envelope)
    plan.metadata["imported"] = True
    plan.metadata["import_source"] = source

    openings_added = False
    if add_openings:
        # No door or window survives any of the parsers, so the plan arrives
        # sealed. Cut them under the same rules the generated schemes obey -
        # never re-identifying a room, because the upload is the architect's
        # decision and not a search result to be corrected.
        generator._place_openings(plan, envelope, repair=False)
        openings_added = True
        warnings.append(
            "Doors and windows were placed by the platform under NBC glazing ratios "
            "and the residential circulation rules, since the upload carried none."
        )

    return ImportResult(
        plan=plan, source=source, rooms_read=read, rooms_kept=len(kept),
        unrecognised=sorted(set(unrecognised)), warnings=warnings,
        scale_note=scale_note, openings_added=openings_added,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


#: How long the remote vision model gets before an upload gives up on it. The
#: free tiers rate-limit and queue; an upload should not hang a minute on one.
VISION_TIMEOUT_S = 20.0


def parse_image_local(data: bytes) -> tuple[list[ParsedRoom], list[str], dict[str, object]]:
    """Rooms from an image using OpenCV and OCR on this machine; see `raster`."""
    from aip.engines.architecture.raster import parse_image_local as _parse

    return _parse(data)


async def _read_image(
    data: bytes, mime: str
) -> tuple[list[ParsedRoom], list[str], dict[str, object]]:
    """Local computer vision first, the remote vision model only if that fails.

    The local reader is deterministic and offline; the model is rate-limited
    and slow, so it is a fallback for the plans the local reader cannot make
    sense of (hand sketches without clear walls, photographs at an angle).
    """
    import asyncio

    from aip.engines.architecture.raster import INSTALL_HINT, LocalVisionUnavailable

    local_note = ""
    try:
        rooms, warnings, meta = await asyncio.to_thread(parse_image_local, data)
        if len(rooms) >= 2:
            return rooms, warnings, meta
        local_note = warnings[-1] if warnings else "No rooms were found."
    except LocalVisionUnavailable:
        local_note = INSTALL_HINT

    try:
        return await asyncio.wait_for(parse_image(data, mime), timeout=VISION_TIMEOUT_S)
    except TimeoutError as exc:
        raise ImportError_(
            f"The image could not be read here ({local_note}) and the remote vision model did "
            f"not answer within {VISION_TIMEOUT_S:.0f} s. Try again shortly, or upload the DXF "
            f"or SVG of this plan, which needs no model at all."
        ) from exc
    except ImportError_ as exc:
        raise ImportError_(
            f"The image could not be read here ({local_note}) and {str(exc)[:1].lower()}{str(exc)[1:]}"
        ) from exc


async def import_floorplan(
    data: bytes,
    filename: str,
    *,
    plot_width: float | None = None,
    plot_depth: float | None = None,
    road: Direction = Direction.N,
    north_angle: float = 0.0,
    name: str = "Imported plan",
    mime: str = "",
) -> ImportResult:
    """Read any supported file into a FloorPlan."""
    lower = filename.lower()
    warnings: list[str] = []
    unit_scale: tuple[float, str] | None = None

    if lower.endswith(".json"):
        try:
            payload = json.loads(data.decode("utf-8"))
            plan = FloorPlan.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise ImportError_(f"Not a valid plan JSON: {exc}") from exc
        plan.metadata["imported"] = True
        plan.metadata["import_source"] = "json"
        return ImportResult(plan=plan, source="json", rooms_read=len(plan.all_rooms),
                            rooms_kept=len(plan.all_rooms), scale_note="Native schema; no scaling.")

    if lower.endswith(".dxf"):
        text = data.decode("utf-8", errors="replace")
        rooms, warnings = parse_dxf(text)
        source = "dxf"
        unit_scale = dxf_units(text)
        if unit_scale:
            # A header that says metres over coordinates in the thousands is a
            # stale header, and the extent is the better witness.
            box = bounding_box([p for r in rooms for p in r.polygon])
            if not 3.0 <= max(box.width, box.height) * unit_scale[0] <= 300.0:
                unit_scale = None
    elif lower.endswith(".svg"):
        rooms, warnings = parse_svg(data.decode("utf-8", errors="replace"))
        source = "svg"
    elif lower.endswith((".png", ".jpg", ".jpeg", ".webp")) or mime.startswith("image/"):
        mime = mime or {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(
            lower.rsplit(".", 1)[-1], "image/png")
        rooms, warnings, meta = await _read_image(data, mime)
        source = "image"
        extent_m = meta.get("extent_m")
        if extent_m:
            # The drawing stated its own scale: rooms are fractions of the
            # building's longer side, so the building is exactly that long.
            k = float(extent_m)  # type: ignore[arg-type]
            for r in rooms:
                r.polygon = [Vec2(p.x * k, p.y * k) for p in r.polygon]
            unit_scale = (1.0, "scale read from the drawing's own dimension strings")
        else:
            # Trust the drawing's own dimension strings when the caller gave none.
            plot_width = plot_width or (float(meta["plot_width_m"]) if meta.get("plot_width_m") else None)  # type: ignore[arg-type]
            plot_depth = plot_depth or (float(meta["plot_depth_m"]) if meta.get("plot_depth_m") else None)  # type: ignore[arg-type]
            if not (plot_width and plot_depth):
                warnings.append(
                    "No plot size was given and none could be read from the image, so the "
                    "scale is a guess. Give the plot size for a correct area and cost."
                )
    else:
        raise ImportError_(
            "Unsupported file. Upload a DXF, SVG, PNG/JPG image, or the platform's own plan JSON."
        )

    return assemble(
        rooms, source=source, plot_width=plot_width, plot_depth=plot_depth,
        road=road, north_angle=north_angle, name=name, warnings=warnings,
        unit_scale=unit_scale,
    )
