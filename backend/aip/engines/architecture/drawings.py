"""Vector drawing generation.

Produces real architectural drawings - plans, elevations, sections, roof and site
plans - as SVG, directly from the model. SVG rather than raster because it is
resolution independent, tiny, styleable by the host page's theme, printable to
scale, and embeddable in any website without a viewer.

Drawing conventions follow standard architectural practice so the output is
legible to a builder, not just to a client: walls poched solid, doors shown with
swing arcs, windows as a break in the wall with sill lines, rooms labelled with
name and area, plus a north point and a graphic scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

from aip.domain.geometry import BoundingBox, Direction, Vec2, bounding_box
from aip.domain.plan import (
    FloorPlan,
    Level,
    Opening,
    OpeningKind,
    Room,
    RoomType,
    Wall,
    WallKind,
)


@dataclass(slots=True)
class DrawingStyle:
    """Pen weights and colours. Defaults read well in light and dark themes."""

    scale: float = 42.0              # pixels per metre
    margin: float = 60.0
    wall_fill: str = "#1f2933"
    wall_stroke: str = "#0b1015"
    room_fill: str = "#f4f1ea"
    room_fill_wet: str = "#e3edf2"
    room_fill_outdoor: str = "#e8f0e4"
    room_fill_circulation: str = "#f0ece2"
    text: str = "#1f2933"
    text_muted: str = "#6b7785"
    accent: str = "#c2603a"
    glass: str = "#4a90b8"
    dimension: str = "#8a94a0"
    grid: str = "#dfe3e8"
    background: str = "#ffffff"
    font: str = "'Inter', 'Segoe UI', system-ui, sans-serif"

    def room_colour(self, room: Room) -> str:
        if room.type.is_outdoor:
            return self.room_fill_outdoor
        if room.type.is_wet:
            return self.room_fill_wet
        if room.type.is_circulation:
            return self.room_fill_circulation
        return self.room_fill


class _Canvas:
    """Minimal SVG writer with a model-to-screen transform."""

    def __init__(self, extent: BoundingBox, style: DrawingStyle, title: str) -> None:
        self.style = style
        self.extent = extent
        self.title = title
        self.width = extent.width * style.scale + 2 * style.margin
        self.height = extent.height * style.scale + 2 * style.margin
        self.parts: list[str] = []

    def px(self, point: Vec2) -> tuple[float, float]:
        """Model metres to SVG pixels, flipping Y so north is up."""
        x = (point.x - self.extent.min_x) * self.style.scale + self.style.margin
        y = (self.extent.max_y - point.y) * self.style.scale + self.style.margin
        return round(x, 2), round(y, 2)

    def m(self, metres: float) -> float:
        return round(metres * self.style.scale, 2)

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def polygon(self, points: list[Vec2], fill: str, stroke: str = "none", width: float = 1.0,
                opacity: float = 1.0, extra: str = "") -> None:
        coords = " ".join(f"{x},{y}" for x, y in (self.px(p) for p in points))
        self.add(
            f'<polygon points="{coords}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{width}" opacity="{opacity}" {extra}/>'
        )

    def line(self, a: Vec2, b: Vec2, stroke: str, width: float = 1.0, dash: str = "",
             cap: str = "butt", opacity: float = 1.0) -> None:
        x1, y1 = self.px(a)
        x2, y2 = self.px(b)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" '
            f'stroke-width="{width}" stroke-linecap="{cap}" opacity="{opacity}"{dash_attr}/>'
        )

    def text(self, point: Vec2, content: str, size: float = 11.0, fill: str | None = None,
             anchor: str = "middle", weight: str = "400", dy: float = 0.0,
             italic: bool = False) -> None:
        x, y = self.px(point)
        style = "font-style:italic;" if italic else ""
        self.add(
            f'<text x="{x}" y="{round(y + dy, 2)}" font-family="{self.style.font}" '
            f'font-size="{size}" fill="{fill or self.style.text}" text-anchor="{anchor}" '
            f'font-weight="{weight}" style="{style}">{escape(content)}</text>'
        )

    def arc(self, centre: Vec2, radius: float, start_deg: float, end_deg: float,
            stroke: str, width: float = 0.8, dash: str = "3 3") -> None:
        cx, cy = self.px(centre)
        r = self.m(radius)
        sx = cx + r * math.cos(math.radians(start_deg))
        sy = cy - r * math.sin(math.radians(start_deg))
        ex = cx + r * math.cos(math.radians(end_deg))
        ey = cy - r * math.sin(math.radians(end_deg))
        sweep = 0 if end_deg > start_deg else 1
        large = 1 if abs(end_deg - start_deg) > 180 else 0
        self.add(
            f'<path d="M {round(sx,2)},{round(sy,2)} A {r},{r} 0 {large} {sweep} '
            f'{round(ex,2)},{round(ey,2)}" fill="none" stroke="{stroke}" '
            f'stroke-width="{width}" stroke-dasharray="{dash}"/>'
        )

    def render(self) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{round(self.width)}" '
            f'height="{round(self.height)}" viewBox="0 0 {round(self.width)} '
            f'{round(self.height)}" role="img" aria-label="{escape(self.title)}">'
            f"<title>{escape(self.title)}</title>"
            f'<rect width="100%" height="100%" fill="{self.style.background}"/>'
            + "".join(self.parts)
            + "</svg>"
        )


# ---------------------------------------------------------------------------
# Floor plan
# ---------------------------------------------------------------------------


def floor_plan_svg(
    plan: FloorPlan,
    level_index: int = 0,
    *,
    style: DrawingStyle | None = None,
    show_dimensions: bool = True,
    show_grid: bool = False,
    show_furniture: bool = True,
    highlight_rooms: set[str] | None = None,
) -> str:
    """Render one level as a measured floor plan."""
    style = style or DrawingStyle()
    level = plan.level_at(level_index)
    if level is None or not level.rooms:
        return _empty_drawing(style, "No plan to draw")

    extent = _padded_extent(plan, level)
    canvas = _Canvas(extent, style, f"{plan.name} - {level.display_name()}")

    if show_grid and plan.column_grid:
        _draw_column_grid(canvas, plan, extent)

    for room in level.rooms:
        highlighted = highlight_rooms is not None and room.id in highlight_rooms
        canvas.polygon(
            room.polygon,
            fill=style.accent if highlighted else canvas.style.room_colour(room),
            opacity=0.28 if highlighted else 1.0,
        )

    for wall in level.walls:
        _draw_wall(canvas, wall, style)

    for wall in level.walls:
        for opening in wall.openings:
            _draw_opening(canvas, wall, opening, style)

    if show_furniture:
        for room in level.rooms:
            _draw_furniture_hint(canvas, room, style)

    for room in level.rooms:
        _label_room(canvas, room, style)

    for stair in level.staircases:
        _draw_stair(canvas, stair, style)

    if show_dimensions:
        _draw_dimensions(canvas, level, style)

    _draw_north_point(canvas, plan, style)
    _draw_scale_bar(canvas, style)
    _draw_title_block(canvas, plan, level, style)
    return canvas.render()


def _padded_extent(plan: FloorPlan, level: Level) -> BoundingBox:
    points = [p for r in level.rooms for p in r.polygon]
    if plan.site.boundary:
        points.extend(plan.site.boundary)
    box = bounding_box(points)
    pad = 1.2
    return BoundingBox(box.min_x - pad, box.min_y - pad, box.max_x + pad, box.max_y + pad)


def _draw_wall(canvas: _Canvas, wall: Wall, style: DrawingStyle) -> None:
    """Poche the wall as a filled rectangle of its true thickness."""
    direction = wall.direction_vector
    if direction.length < 1e-6:
        return
    normal = direction.perpendicular() * (wall.thickness / 2)
    corners = [
        wall.start + normal, wall.end + normal,
        wall.end - normal, wall.start - normal,
    ]
    canvas.polygon(
        corners,
        fill=style.wall_fill,
        stroke=style.wall_stroke,
        width=0.5,
    )


def _draw_opening(canvas: _Canvas, wall: Wall, opening: Opening, style: DrawingStyle) -> None:
    """Break the wall for an opening and add the appropriate symbol."""
    direction = wall.direction_vector
    if direction.length < 1e-6:
        return
    centre = wall.point_at(opening.position)
    half = direction * (opening.width / 2)
    normal = direction.perpendicular() * (wall.thickness / 2 + 0.012)

    start, end = centre - half, centre + half
    # Erase the wall across the opening.
    canvas.polygon(
        [start + normal, end + normal, end - normal, start - normal],
        fill=style.background,
    )

    if opening.kind.is_glazed:
        inner = direction.perpendicular() * (wall.thickness * 0.16)
        canvas.line(start + inner, end + inner, style.glass, 1.5)
        canvas.line(start - inner, end - inner, style.glass, 1.5)
        canvas.line(start, end, style.glass, 0.6, dash="2 2")
    else:
        is_main = opening.kind is OpeningKind.MAIN_DOOR
        colour = style.accent if is_main else style.wall_stroke
        # Leaf plus swing arc, the standard plan symbol.
        leaf_end = start + direction.perpendicular() * opening.width
        canvas.line(start, leaf_end, colour, 1.6 if is_main else 1.2)
        base_angle = math.degrees(math.atan2(direction.y, direction.x))
        canvas.arc(start, opening.width, base_angle, base_angle + 90, colour, 0.9)
        canvas.line(start, start + direction * 0.02, colour, 2.0)


def _label_room(canvas: _Canvas, room: Room, style: DrawingStyle) -> None:
    centre = room.centre
    box = room.bbox
    # Skip the label when the room is too small to hold it legibly.
    if canvas.m(min(box.width, box.height)) < 34:
        return

    name = room.display_name()
    size = 11.5 if canvas.m(min(box.width, box.height)) > 60 else 9.5
    canvas.text(centre, name.upper(), size=size, weight="600", dy=-3)
    canvas.text(
        centre, f"{room.area:.1f} m²", size=size - 1.5,
        fill=style.text_muted, dy=size + 1,
    )


def _draw_furniture_hint(canvas: _Canvas, room: Room, style: DrawingStyle) -> None:
    """Indicative furniture blocks.

    Not a furniture layout - the interior engine does that properly. These are
    the schematic blocks an architect sketches to show a room works, and their
    real job here is to make the drawing legible as a *home* rather than as a
    partition diagram.
    """
    box = room.bbox
    if box.width < 1.6 or box.height < 1.6:
        return
    centre = room.centre
    faint = 0.35

    def block(cx: float, cy: float, w: float, h: float) -> None:
        canvas.polygon(
            [Vec2(cx - w / 2, cy - h / 2), Vec2(cx + w / 2, cy - h / 2),
             Vec2(cx + w / 2, cy + h / 2), Vec2(cx - w / 2, cy + h / 2)],
            fill="none", stroke=style.text_muted, width=0.7, opacity=faint,
        )

    if room.type in {RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
                     RoomType.CHILDREN_BEDROOM}:
        bed_w, bed_h = (1.8, 2.0) if room.type is RoomType.MASTER_BEDROOM else (1.5, 2.0)
        if box.width >= box.height:
            block(box.min_x + bed_w / 2 + 0.4, centre.y, bed_w, bed_h)
        else:
            block(centre.x, box.max_y - bed_h / 2 - 0.4, bed_w, bed_h)
    elif room.type in {RoomType.LIVING, RoomType.DRAWING, RoomType.FAMILY}:
        block(centre.x, centre.y - box.height * 0.2, min(2.4, box.width - 0.8), 0.85)
        block(centre.x, centre.y + box.height * 0.12, min(1.2, box.width - 1.2), 0.6)
    elif room.type is RoomType.DINING:
        size = min(1.6, box.width - 0.8, box.height - 0.8)
        block(centre.x, centre.y, size, size * 0.75)
    elif room.type is RoomType.KITCHEN:
        depth = 0.6
        if box.width >= box.height:
            block(centre.x, box.min_y + depth / 2 + 0.06, box.width - 0.3, depth)
        else:
            block(box.min_x + depth / 2 + 0.06, centre.y, depth, box.height - 0.3)
    elif room.type in {RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER}:
        block(box.min_x + 0.45, box.min_y + 0.4, 0.5, 0.7)


def _draw_stair(canvas: _Canvas, stair, style: DrawingStyle) -> None:
    """Draw treads and the direction-of-travel arrow."""
    box = bounding_box(stair.polygon)
    if box.width < 0.5 or box.height < 0.5:
        return
    horizontal = box.width >= box.height
    steps = min(stair.step_count, 18)
    for i in range(1, steps):
        t = i / steps
        if horizontal:
            x = box.min_x + box.width * t
            canvas.line(Vec2(x, box.min_y + 0.08), Vec2(x, box.max_y - 0.08), style.text_muted, 0.7)
        else:
            y = box.min_y + box.height * t
            canvas.line(Vec2(box.min_x + 0.08, y), Vec2(box.max_x - 0.08, y), style.text_muted, 0.7)

    centre = box.centre
    if horizontal:
        canvas.line(Vec2(box.min_x + 0.3, centre.y), Vec2(box.max_x - 0.3, centre.y), style.accent, 1.2)
        tip = Vec2(box.max_x - 0.3, centre.y)
        canvas.line(tip, tip + Vec2(-0.22, 0.14), style.accent, 1.2)
        canvas.line(tip, tip + Vec2(-0.22, -0.14), style.accent, 1.2)
    else:
        canvas.line(Vec2(centre.x, box.min_y + 0.3), Vec2(centre.x, box.max_y - 0.3), style.accent, 1.2)
        tip = Vec2(centre.x, box.max_y - 0.3)
        canvas.line(tip, tip + Vec2(0.14, -0.22), style.accent, 1.2)
        canvas.line(tip, tip + Vec2(-0.14, -0.22), style.accent, 1.2)
    canvas.text(Vec2(centre.x, box.min_y + 0.25), "UP", size=8, fill=style.accent, weight="600")


def _draw_column_grid(canvas: _Canvas, plan: FloorPlan, extent: BoundingBox) -> None:
    grid = plan.column_grid
    if grid is None:
        return
    style = canvas.style
    xs, ys = [grid.origin.x], [grid.origin.y]
    for dx in grid.x_spacings:
        xs.append(xs[-1] + dx)
    for dy in grid.y_spacings:
        ys.append(ys[-1] + dy)

    for x in xs:
        canvas.line(Vec2(x, extent.min_y), Vec2(x, extent.max_y), style.grid, 0.6, dash="6 4")
    for y in ys:
        canvas.line(Vec2(extent.min_x, y), Vec2(extent.max_x, y), style.grid, 0.6, dash="6 4")

    w, d = grid.column_size
    for x in xs:
        for y in ys:
            canvas.polygon(
                [Vec2(x - w / 2, y - d / 2), Vec2(x + w / 2, y - d / 2),
                 Vec2(x + w / 2, y + d / 2), Vec2(x - w / 2, y + d / 2)],
                fill=style.wall_fill, opacity=0.85,
            )


def _draw_dimensions(canvas: _Canvas, level: Level, style: DrawingStyle) -> None:
    """Overall dimension strings on the south and west edges."""
    box = level.envelope()
    offset = 0.62

    def string(a: Vec2, b: Vec2, label: str, vertical: bool) -> None:
        canvas.line(a, b, style.dimension, 0.8)
        tick = Vec2(0, 0.11) if not vertical else Vec2(0.11, 0)
        canvas.line(a - tick, a + tick, style.dimension, 0.8)
        canvas.line(b - tick, b + tick, style.dimension, 0.8)
        mid = (a + b) * 0.5
        canvas.text(
            mid, label, size=9.5, fill=style.dimension,
            dy=-4 if not vertical else 0,
        )

    string(
        Vec2(box.min_x, box.min_y - offset), Vec2(box.max_x, box.min_y - offset),
        f"{box.width:.2f} m", vertical=False,
    )
    string(
        Vec2(box.min_x - offset, box.min_y), Vec2(box.min_x - offset, box.max_y),
        f"{box.height:.2f} m", vertical=True,
    )


def _draw_north_point(canvas: _Canvas, plan: FloorPlan, style: DrawingStyle) -> None:
    """North arrow, rotated to the site's true north."""
    extent = canvas.extent
    cx = extent.max_x - 0.85
    cy = extent.max_y - 0.85
    centre = Vec2(cx, cy)
    angle = math.radians(-plan.site.north_angle)
    length = 0.62

    tip = Vec2(cx + length * math.sin(angle), cy + length * math.cos(angle))
    tail = Vec2(cx - length * 0.55 * math.sin(angle), cy - length * 0.55 * math.cos(angle))
    left = Vec2(
        cx + 0.2 * math.sin(angle + 2.4), cy + 0.2 * math.cos(angle + 2.4)
    )
    right = Vec2(
        cx + 0.2 * math.sin(angle - 2.4), cy + 0.2 * math.cos(angle - 2.4)
    )
    canvas.line(tail, tip, style.text, 1.4)
    canvas.polygon([tip, left, centre, right], fill=style.text)
    canvas.text(
        Vec2(tip.x, tip.y + 0.28), "N", size=11, weight="700", fill=style.text
    )


def _draw_scale_bar(canvas: _Canvas, style: DrawingStyle) -> None:
    extent = canvas.extent
    x0 = extent.min_x + 0.4
    y0 = extent.min_y + 0.35
    total = 5.0
    segment = 1.0
    for i in range(int(total / segment)):
        a = Vec2(x0 + i * segment, y0)
        b = Vec2(x0 + (i + 1) * segment, y0)
        canvas.polygon(
            [a, b, Vec2(b.x, b.y + 0.1), Vec2(a.x, a.y + 0.1)],
            fill=style.text if i % 2 == 0 else style.background,
            stroke=style.text, width=0.5,
        )
    canvas.text(Vec2(x0, y0 - 0.12), "0", size=8, fill=style.text_muted, anchor="middle")
    canvas.text(
        Vec2(x0 + total, y0 - 0.12), f"{total:.0f} m", size=8,
        fill=style.text_muted, anchor="middle",
    )


def _draw_title_block(canvas: _Canvas, plan: FloorPlan, level: Level, style: DrawingStyle) -> None:
    extent = canvas.extent
    canvas.text(
        Vec2(extent.min_x + 0.4, extent.max_y - 0.35),
        f"{plan.name} - {level.display_name()}",
        size=13, weight="700", anchor="start",
    )
    canvas.text(
        Vec2(extent.min_x + 0.4, extent.max_y - 0.72),
        f"Built-up {level.built_area:.1f} m²   |   Carpet {level.carpet_area:.1f} m²   "
        f"|   {len(level.rooms)} rooms",
        size=9.5, fill=style.text_muted, anchor="start",
    )


def _empty_drawing(style: DrawingStyle, message: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="160">'
        f'<rect width="100%" height="100%" fill="{style.background}"/>'
        f'<text x="210" y="85" text-anchor="middle" font-family="{style.font}" '
        f'font-size="14" fill="{style.text_muted}">{escape(message)}</text></svg>'
    )


# ---------------------------------------------------------------------------
# Elevations
# ---------------------------------------------------------------------------


def elevation_svg(
    plan: FloorPlan, direction: Direction = Direction.N, *, style: DrawingStyle | None = None
) -> str:
    """Orthographic elevation seen from `direction`.

    Projects every level's envelope and the openings on the facing walls onto a
    vertical plane, which is enough to communicate massing, opening rhythm and
    storey heights - the three things an elevation is actually read for.
    """
    style = style or DrawingStyle()
    if not plan.levels:
        return _empty_drawing(style, "No levels to draw")

    env = plan.envelope()
    horizontal = env.width if direction in {Direction.N, Direction.S} else env.height
    total_height = plan.building_height + 0.9        # parapet

    extent = BoundingBox(-1.0, -1.0, horizontal + 1.0, total_height + 1.4)
    canvas = _Canvas(extent, style, f"{plan.name} - {direction.value} elevation")

    # Ground line.
    canvas.line(
        Vec2(-0.8, 0.0), Vec2(horizontal + 0.8, 0.0), style.wall_stroke, 2.4, cap="square"
    )
    for i in range(int(horizontal) + 2):
        canvas.line(Vec2(i - 0.4, 0.0), Vec2(i - 0.65, -0.25), style.text_muted, 0.7)

    # Building mass, storey by storey.
    base = 0.0
    for level in plan.levels:
        top = base + level.floor_to_floor
        canvas.polygon(
            [Vec2(0, base), Vec2(horizontal, base), Vec2(horizontal, top), Vec2(0, top)],
            fill="#eceff2", stroke=style.wall_stroke, width=1.3,
        )
        canvas.line(Vec2(0, top), Vec2(horizontal, top), style.text_muted, 0.8, dash="5 4")
        canvas.text(
            Vec2(horizontal + 0.55, top), f"+{top:.2f}", size=8.5,
            fill=style.text_muted, anchor="start", dy=3,
        )
        _draw_elevation_openings(canvas, plan, level, direction, base, env, style)
        base = top

    # Parapet.
    canvas.polygon(
        [Vec2(0, base), Vec2(horizontal, base), Vec2(horizontal, base + 0.9), Vec2(0, base + 0.9)],
        fill="#dfe3e8", stroke=style.wall_stroke, width=1.3,
    )

    canvas.text(
        Vec2(0, total_height + 0.9), f"{direction.value} ELEVATION",
        size=12.5, weight="700", anchor="start",
    )
    _draw_scale_bar(canvas, style)
    return canvas.render()


def _draw_elevation_openings(
    canvas: _Canvas,
    plan: FloorPlan,
    level: Level,
    direction: Direction,
    base: float,
    env: BoundingBox,
    style: DrawingStyle,
) -> None:
    from aip.engines.architecture.layout import _wall_direction

    for wall in level.walls:
        if wall.kind is not WallKind.EXTERIOR:
            continue
        facing = _wall_direction(plan, wall)
        # Only walls facing roughly toward the viewer appear in this elevation.
        delta = abs(((facing.bearing - direction.bearing) + 180) % 360 - 180)
        if delta > 55:
            continue

        for opening in wall.openings:
            centre = wall.point_at(opening.position)
            if direction in {Direction.N, Direction.S}:
                u = centre.x - env.min_x
                if direction is Direction.S:
                    u = env.width - u
            else:
                u = centre.y - env.min_y
                if direction is Direction.W:
                    u = env.height - u

            x0 = u - opening.width / 2
            x1 = u + opening.width / 2
            y0 = base + opening.sill_height
            y1 = y0 + opening.height

            fill = style.glass if opening.kind.is_glazed else "#8a6a4f"
            canvas.polygon(
                [Vec2(x0, y0), Vec2(x1, y0), Vec2(x1, y1), Vec2(x0, y1)],
                fill=fill, stroke=style.wall_stroke, width=1.0, opacity=0.85,
            )
            if opening.kind.is_glazed:
                mid = (x0 + x1) / 2
                canvas.line(Vec2(mid, y0), Vec2(mid, y1), "#ffffff", 0.9, opacity=0.6)
                canvas.line(Vec2(x0, (y0 + y1) / 2), Vec2(x1, (y0 + y1) / 2), "#ffffff", 0.9, opacity=0.6)
                # Sun-shade over the opening.
                canvas.polygon(
                    [Vec2(x0 - 0.15, y1), Vec2(x1 + 0.15, y1),
                     Vec2(x1 + 0.15, y1 + 0.12), Vec2(x0 - 0.15, y1 + 0.12)],
                    fill="#cfd6dd", stroke=style.wall_stroke, width=0.7,
                )


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


def section_svg(
    plan: FloorPlan,
    *,
    axis: str = "x",
    position: float | None = None,
    style: DrawingStyle | None = None,
) -> str:
    """Vertical section cut through the building.

    `axis="x"` cuts along the X axis (viewer looks north), `axis="y"` along Y.
    Rooms the cut passes through are shown with their true clear heights, which
    is what a section is for: proving the building works in the vertical
    dimension, where plans are silent.
    """
    style = style or DrawingStyle()
    if not plan.levels:
        return _empty_drawing(style, "No levels to draw")

    env = plan.envelope()
    if position is None:
        position = env.centre.y if axis == "x" else env.centre.x
    span = env.width if axis == "x" else env.height
    origin = env.min_x if axis == "x" else env.min_y
    total_height = plan.building_height + 0.9

    extent = BoundingBox(-1.0, -1.4, span + 1.6, total_height + 1.4)
    canvas = _Canvas(extent, style, f"{plan.name} - section")

    # Ground and foundation.
    canvas.polygon(
        [Vec2(-0.8, -1.2), Vec2(span + 0.8, -1.2), Vec2(span + 0.8, 0.0), Vec2(-0.8, 0.0)],
        fill="#e6e0d6", stroke=style.text_muted, width=0.7,
    )
    canvas.line(Vec2(-0.8, 0.0), Vec2(span + 0.8, 0.0), style.wall_stroke, 2.2)

    base = 0.0
    for level in plan.levels:
        cut_rooms = [r for r in level.rooms if _crosses(r, axis, position)]
        slab = 0.15
        canvas.polygon(
            [Vec2(0, base - slab), Vec2(span, base - slab), Vec2(span, base), Vec2(0, base)],
            fill=style.wall_fill,
        )

        for room in cut_rooms:
            box = room.bbox
            lo = (box.min_x if axis == "x" else box.min_y) - origin
            hi = (box.max_x if axis == "x" else box.max_y) - origin
            top = base + room.ceiling_height
            canvas.polygon(
                [Vec2(lo, base), Vec2(hi, base), Vec2(hi, top), Vec2(lo, top)],
                fill=canvas.style.room_colour(room), stroke=style.text_muted, width=0.6,
            )
            if hi - lo > 1.4:
                canvas.text(
                    Vec2((lo + hi) / 2, base + room.ceiling_height / 2),
                    room.display_name().upper(), size=9, weight="600",
                )
                canvas.text(
                    Vec2((lo + hi) / 2, base + room.ceiling_height / 2),
                    f"clear {room.ceiling_height:.2f} m", size=8,
                    fill=style.text_muted, dy=12,
                )
            # Cut walls at the room boundaries.
            for x in (lo, hi):
                canvas.polygon(
                    [Vec2(x - 0.06, base), Vec2(x + 0.06, base),
                     Vec2(x + 0.06, top), Vec2(x - 0.06, top)],
                    fill=style.wall_fill,
                )

        top_of_level = base + level.floor_to_floor
        canvas.text(
            Vec2(span + 0.35, base), f"FFL +{base:.2f}", size=8.5,
            fill=style.text_muted, anchor="start", dy=3,
        )
        base = top_of_level

    # Roof slab and parapet.
    canvas.polygon(
        [Vec2(0, base - 0.15), Vec2(span, base - 0.15), Vec2(span, base), Vec2(0, base)],
        fill=style.wall_fill,
    )
    for x in (0.0, span):
        canvas.polygon(
            [Vec2(x - 0.06, base), Vec2(x + 0.06, base),
             Vec2(x + 0.06, base + 0.9), Vec2(x - 0.06, base + 0.9)],
            fill=style.wall_fill,
        )

    canvas.text(
        Vec2(0, total_height + 0.9),
        f"SECTION {'A-A' if axis == 'x' else 'B-B'}",
        size=12.5, weight="700", anchor="start",
    )
    _draw_scale_bar(canvas, style)
    return canvas.render()


def _crosses(room: Room, axis: str, position: float) -> bool:
    box = room.bbox
    if axis == "x":
        return box.min_y <= position <= box.max_y
    return box.min_x <= position <= box.max_x


# ---------------------------------------------------------------------------
# Roof and site
# ---------------------------------------------------------------------------


def roof_plan_svg(plan: FloorPlan, *, style: DrawingStyle | None = None) -> str:
    """Roof layout with falls, rainwater outlets and terrace zoning."""
    style = style or DrawingStyle()
    if not plan.levels:
        return _empty_drawing(style, "No levels to draw")

    top = plan.levels[-1]
    env = top.envelope()
    extent = BoundingBox(env.min_x - 1.2, env.min_y - 1.2, env.max_x + 1.2, env.max_y + 1.2)
    canvas = _Canvas(extent, style, f"{plan.name} - roof plan")

    canvas.polygon(
        env.to_polygon(), fill="#e9ecef", stroke=style.wall_stroke, width=1.6
    )
    # Parapet band.
    inner = BoundingBox(env.min_x + 0.2, env.min_y + 0.2, env.max_x - 0.2, env.max_y - 0.2)
    canvas.polygon(inner.to_polygon(), fill="#f3f5f7", stroke=style.text_muted, width=0.8)

    # Falls toward the north-east, which is both good drainage practice and the
    # direction the Vastu slope rule prescribes.
    outlet = Vec2(env.max_x - 0.6, env.max_y - 0.6)
    for fx in (0.25, 0.5, 0.75):
        for fy in (0.25, 0.5, 0.75):
            start = Vec2(env.min_x + env.width * fx, env.min_y + env.height * fy)
            direction = (outlet - start).normalised() * 0.55
            end = start + direction
            canvas.line(start, end, style.glass, 0.9)
            canvas.line(end, end - direction * 0.35 + direction.perpendicular() * 0.14, style.glass, 0.9)
            canvas.line(end, end - direction * 0.35 - direction.perpendicular() * 0.14, style.glass, 0.9)

    canvas.polygon(
        [Vec2(outlet.x - 0.22, outlet.y - 0.22), Vec2(outlet.x + 0.22, outlet.y - 0.22),
         Vec2(outlet.x + 0.22, outlet.y + 0.22), Vec2(outlet.x - 0.22, outlet.y + 0.22)],
        fill=style.glass, stroke=style.wall_stroke, width=0.8,
    )
    canvas.text(
        Vec2(outlet.x, outlet.y - 0.42), "RWP", size=8, fill=style.glass, weight="600"
    )

    # Overhead tank in the north-east, per the water rule.
    tank = Vec2(env.max_x - 1.8, env.max_y - 1.4)
    canvas.polygon(
        [Vec2(tank.x - 0.75, tank.y - 0.6), Vec2(tank.x + 0.75, tank.y - 0.6),
         Vec2(tank.x + 0.75, tank.y + 0.6), Vec2(tank.x - 0.75, tank.y + 0.6)],
        fill="#cfd6dd", stroke=style.wall_stroke, width=1.0,
    )
    canvas.text(tank, "OHT", size=9, weight="600")

    canvas.text(
        Vec2(env.min_x, env.max_y + 0.7), "ROOF PLAN",
        size=12.5, weight="700", anchor="start",
    )
    canvas.text(
        Vec2(env.min_x, env.max_y + 0.35),
        f"Falls 1:100 to north-east   |   Area {env.area:.1f} m²",
        size=9, fill=style.text_muted, anchor="start",
    )
    _draw_north_point(canvas, plan, style)
    _draw_scale_bar(canvas, style)
    return canvas.render()


def site_plan_svg(plan: FloorPlan, *, style: DrawingStyle | None = None) -> str:
    """Plot boundary, setbacks, building footprint and approach."""
    style = style or DrawingStyle()
    site = plan.site
    if not site.boundary:
        return _empty_drawing(style, "No site boundary recorded")

    box = site.bbox
    extent = BoundingBox(box.min_x - 2.0, box.min_y - 2.0, box.max_x + 2.0, box.max_y + 2.0)
    canvas = _Canvas(extent, style, f"{plan.name} - site plan")

    canvas.polygon(site.boundary, fill="#eef2ec", stroke=style.wall_stroke, width=2.0)

    from aip.domain.geometry import shrink_polygon

    setback = min(site.setback_front, site.setback_rear, site.setback_left, site.setback_right)
    envelope = shrink_polygon(site.boundary, setback)
    if envelope:
        canvas.polygon(envelope, fill="none", stroke=style.accent, width=1.1, extra='stroke-dasharray="7 5"')

    ground = plan.level_at(0)
    if ground:
        for room in ground.rooms:
            canvas.polygon(
                room.polygon,
                fill=style.wall_fill if not room.type.is_outdoor else "#d7e4d2",
                opacity=0.9 if not room.type.is_outdoor else 0.6,
            )

    # Road on the approach side.
    road = site.road_directions[0] if site.road_directions else Direction.N
    _draw_road(canvas, box, road, style)

    canvas.text(
        Vec2(extent.min_x + 0.4, extent.max_y - 0.4), "SITE PLAN",
        size=12.5, weight="700", anchor="start",
    )
    canvas.text(
        Vec2(extent.min_x + 0.4, extent.max_y - 0.8),
        f"Plot {site.plot_area:.0f} m²   |   Footprint {plan.footprint_area:.0f} m²   "
        f"|   Coverage {plan.footprint_area / site.plot_area:.0%}   |   FAR {plan.achieved_far:.2f}",
        size=9, fill=style.text_muted, anchor="start",
    )
    _draw_north_point(canvas, plan, style)
    _draw_scale_bar(canvas, style)
    return canvas.render()


def _draw_road(canvas: _Canvas, box: BoundingBox, road: Direction, style: DrawingStyle) -> None:
    width = 1.4
    if road.cardinal in {Direction.N, Direction.NE, Direction.NW}:
        strip = [Vec2(box.min_x - 1, box.max_y + 0.2), Vec2(box.max_x + 1, box.max_y + 0.2),
                 Vec2(box.max_x + 1, box.max_y + 0.2 + width), Vec2(box.min_x - 1, box.max_y + 0.2 + width)]
        label = Vec2(box.centre.x, box.max_y + 0.2 + width / 2)
    elif road.cardinal in {Direction.S, Direction.SE, Direction.SW}:
        strip = [Vec2(box.min_x - 1, box.min_y - 0.2 - width), Vec2(box.max_x + 1, box.min_y - 0.2 - width),
                 Vec2(box.max_x + 1, box.min_y - 0.2), Vec2(box.min_x - 1, box.min_y - 0.2)]
        label = Vec2(box.centre.x, box.min_y - 0.2 - width / 2)
    elif road.cardinal is Direction.E:
        strip = [Vec2(box.max_x + 0.2, box.min_y - 1), Vec2(box.max_x + 0.2 + width, box.min_y - 1),
                 Vec2(box.max_x + 0.2 + width, box.max_y + 1), Vec2(box.max_x + 0.2, box.max_y + 1)]
        label = Vec2(box.max_x + 0.2 + width / 2, box.centre.y)
    else:
        strip = [Vec2(box.min_x - 0.2 - width, box.min_y - 1), Vec2(box.min_x - 0.2, box.min_y - 1),
                 Vec2(box.min_x - 0.2, box.max_y + 1), Vec2(box.min_x - 0.2 - width, box.max_y + 1)]
        label = Vec2(box.min_x - 0.2 - width / 2, box.centre.y)

    canvas.polygon(strip, fill="#d8dce0", stroke=style.text_muted, width=0.7)
    canvas.text(label, "ROAD", size=9, fill=style.text_muted, weight="600")


def all_drawings(plan: FloorPlan) -> dict[str, str]:
    """Render the full drawing set for a scheme."""
    drawings: dict[str, str] = {}
    for level in plan.levels:
        drawings[f"plan_level_{level.index}"] = floor_plan_svg(plan, level.index)
    for direction in (Direction.N, Direction.E, Direction.S, Direction.W):
        drawings[f"elevation_{direction.value}"] = elevation_svg(plan, direction)
    drawings["section_aa"] = section_svg(plan, axis="x")
    drawings["section_bb"] = section_svg(plan, axis="y")
    drawings["roof_plan"] = roof_plan_svg(plan)
    if plan.site.boundary:
        drawings["site_plan"] = site_plan_svg(plan)
    return drawings
