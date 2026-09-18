"""Bring an existing floor plan into the platform.

Everything downstream - the thirteen critics, the Vastu graph, the cost
takeoff, the airflow solve, the drawings and the CAD export - takes a
`FloorPlan`. So a plan an architect already has, drawn in AutoCAD or exported
from another tool or scanned from paper, only needs to become that one object
and it gets every analysis the generator's own schemes get.

Four sources, in order of how much they can be trusted:

* **JSON** - the platform's own schema. Lossless.
* **DXF** - rooms as closed polylines, names as TEXT inside them. What every
  CAD package exports. Read directly: the R12 subset the platform itself
  writes plus LWPOLYLINE and MTEXT, which cover what AutoCAD and its clones
  actually emit for a plan.
* **SVG** - rectangles, polygons and simple paths with text labels. What plan
  tools and drawing apps export.
* **Image** - a scan or a photograph. Read by a vision model into the same
  room list the vector parsers produce, then validated the same way. It is
  the least certain path and it says so in the result: every room carries the
  confidence the model gave it, and the whole import carries a note on what
  was assumed.

None of the parsers invent doors and windows the source did not draw. Where
they are absent the generator's own placer adds them under the same rules the
generated schemes obey - which is not a shortcut but a feature, since a plan
uploaded as room outlines comes back with code-compliant glazing and a legal
door tree - and the result records that it did so.
"""

from __future__ import annotations

import json
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


def parse_dxf(text: str) -> tuple[list[ParsedRoom], list[str]]:
    """Rooms from closed polylines, labelled by the text sitting inside them."""
    pairs = _dxf_pairs(text)
    polylines: list[tuple[str, list[Vec2], bool]] = []   # (layer, points, closed)
    texts: list[tuple[str, Vec2]] = []
    lines_by_layer: dict[str, list[tuple[Vec2, Vec2]]] = {}

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
            polylines.append((layer, vertices, closed))

        elif entity == "LWPOLYLINE":
            layer = attrs.get(8, ["0"])[0]
            closed = bool(int(attrs.get(70, ["0"])[0]) & 1)
            xs = [float(v) for v in attrs.get(10, [])]
            ys = [float(v) for v in attrs.get(20, [])]
            vertices = [Vec2(x, y) for x, y in zip(xs, ys, strict=False)]
            polylines.append((layer, vertices, closed))

        elif entity in ("TEXT", "MTEXT"):
            content = " ".join(attrs.get(1, []) + attrs.get(3, []))
            content = re.sub(r"\\[A-Za-z][^;]*;", "", content)   # MTEXT formatting codes
            content = content.replace("\\P", " ").strip("{}")
            x = float(attrs.get(10, ["0"])[0])
            y = float(attrs.get(20, ["0"])[0])
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

    if not rooms:
        raise ImportError_(
            "No closed room outlines found. Export rooms as closed polylines "
            "(one per room) with the room name as text inside each."
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


def parse_svg(text: str) -> tuple[list[ParsedRoom], list[str]]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ImportError_(f"Not well-formed SVG: {exc}") from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    shapes: list[list[Vec2]] = []
    texts: list[tuple[str, Vec2]] = []
    warnings: list[str] = []

    for node in root.iter():
        tag = local(node.tag)
        try:
            if tag == "rect":
                x, y = float(node.get("x", 0)), float(node.get("y", 0))
                w, h = float(node.get("width", 0)), float(node.get("height", 0))
                if w > 0 and h > 0:
                    shapes.append([Vec2(x, y), Vec2(x + w, y), Vec2(x + w, y + h), Vec2(x, y + h)])
            elif tag == "polygon":
                nums = [float(v) for v in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", node.get("points", ""))]
                pts = [Vec2(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
                if len(pts) >= 3:
                    shapes.append(pts)
            elif tag == "path":
                pts = _svg_path_points(node.get("d", ""))
                if pts:
                    shapes.append(pts)
            elif tag == "text":
                content = "".join(node.itertext()).strip()
                if content:
                    texts.append((content, Vec2(float(node.get("x", 0)), float(node.get("y", 0)))))
        except ValueError:
            continue

    if root.get("transform") or any(n.get("transform") for n in root.iter()):
        warnings.append(
            "The SVG uses transform attributes, which this importer does not apply. "
            "If rooms look misplaced, export with transforms flattened."
        )

    # SVG's y axis points down; the platform's points up. Flip once here.
    if shapes:
        top = max(p.y for s in shapes for p in s)
        shapes = [[Vec2(p.x, top - p.y) for p in s] for s in shapes]
        texts = [(t, Vec2(at.x, top - at.y)) for t, at in texts]

    rooms: list[ParsedRoom] = []
    for pts in shapes:
        box = bounding_box(pts)
        if min(box.width, box.height) < max(box.width, box.height) * 0.06:
            continue
        rooms.append(ParsedRoom(label="", polygon=pts))
    if not rooms:
        raise ImportError_("No room shapes found in the SVG (looked for rect, polygon and simple path).")

    # The outermost shape that contains every other is the plot or the
    # building outline, not a room.
    if len(rooms) > 1:
        biggest = max(rooms, key=lambda r: r.area)
        if all(point_in_polygon(centroid(r.polygon), biggest.polygon) for r in rooms if r is not biggest):
            rooms.remove(biggest)

    for content, at in texts:
        holders = [r for r in rooms if point_in_polygon(at, r.polygon)]
        if holders:
            holder = min(holders, key=lambda r: r.area)
            holder.label = (holder.label + " " + content).strip() if holder.label else content

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
) -> tuple[list[ParsedRoom], str]:
    """Bring source units to metres.

    A DXF or plan JSON carries units, even if the header does not say which;
    an SVG or an image carries none. The two are treated differently on
    purpose. A drawing with units is only ever *shrunk* to fit the buildable
    footprint, never inflated to fill it - inflating a 9 m house to a 12 m
    plot is how the first round-trip came back 54% larger than it went out.
    A unitless drawing has nothing to be faithful to, so it is fitted to the
    footprint exactly.
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

    if unitless:
        if buildable_w and buildable_d:
            scale = fit_scale()
            note = (f"Fitted the drawing to the {buildable_w:.1f} x {buildable_d:.1f} m "
                    f"buildable footprint inside the stated plot.")
        else:
            # Nothing to fit to: assume a typical plot so areas are at least plausible.
            scale = 9.0 / extent
            note = "No plot size given for a unitless drawing; scaled so the longer side is 9 m."
    else:
        if extent > 2000:
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
        kept, plot_width, plot_depth, unitless=source in ("svg", "image"), setbacks=setbacks
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
        rooms, warnings = parse_dxf(data.decode("utf-8", errors="replace"))
        source = "dxf"
    elif lower.endswith(".svg"):
        rooms, warnings = parse_svg(data.decode("utf-8", errors="replace"))
        source = "svg"
    elif lower.endswith((".png", ".jpg", ".jpeg", ".webp")) or mime.startswith("image/"):
        mime = mime or {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}[lower.rsplit(".", 1)[-1]]
        rooms, warnings, meta = await parse_image(data, mime)
        source = "image"
        # Trust the drawing's own dimension strings when the caller gave none.
        plot_width = plot_width or (float(meta["plot_width_m"]) if meta.get("plot_width_m") else None)
        plot_depth = plot_depth or (float(meta["plot_depth_m"]) if meta.get("plot_depth_m") else None)
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
    )
