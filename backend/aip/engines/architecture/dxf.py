"""DXF export.

The claim that this system produces *editable vector geometry* rather than
pixels is only worth making if an architect can open the result in the software
they already own. SVG proves the geometry is vector; DXF proves it is CAD.

Written as AutoCAD R12 ASCII by hand, with no library. R12 is the most widely
readable DXF revision in existence - AutoCAD, BricsCAD, LibreCAD, QCAD,
DraftSight, Revit's importer and every online viewer accept it - and its entity
set (LINE, LWPOLYLINE, CIRCLE, ARC, TEXT) covers everything a plan at this stage
needs. Taking a dependency to emit a format this simple would trade a hundred
lines of code for a supply-chain risk and a wheel to build on every platform.

Layers follow the convention an Indian practice will recognise from a consultant
drawing set, so the file drops into an existing template without re-mapping:

    A-WALL      walls, poched as closed polylines at true thickness
    A-DOOR      door leaves and swing arcs
    A-GLAZ      windows and ventilators
    A-AREA      room names and areas
    A-DIMS      overall dimension strings
    A-GRID      structural grid and column positions
    S-COLS      columns
    A-ANNO      north point, scale note, title
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from aip.domain.geometry import Vec2
from aip.domain.plan import FloorPlan, Level, OpeningKind, Wall

#: AutoCAD Color Index per layer. These are the conventional assignments in
#: Indian practice, so a plotted sheet needs no pen-table editing.
LAYERS: dict[str, int] = {
    "A-WALL": 7,    # white / black
    "A-DOOR": 3,    # green
    "A-GLAZ": 4,    # cyan
    "A-AREA": 2,    # yellow
    "A-DIMS": 6,    # magenta
    "A-GRID": 8,    # dark grey
    "S-COLS": 1,    # red
    "A-ANNO": 5,    # blue
}


@dataclass(slots=True)
class DxfWriter:
    """Minimal R12 ASCII DXF emitter.

    A DXF file is a flat list of group-code / value pairs, two lines each. The
    whole format is that one rule, which is why hand-writing it is reasonable.
    """

    lines: list[str] = field(default_factory=list)

    def pair(self, code: int, value: object) -> None:
        self.lines.append(str(code))
        self.lines.append(f"{value:.6f}" if isinstance(value, float) else str(value))

    def emit(self, *pairs: tuple[int, object]) -> None:
        """Write a whole entity record at once.

        A DXF entity is nothing but an ordered run of group-code / value pairs,
        so writing one per call fragments the record across a dozen statements
        and hides what is actually being emitted. Grouping them keeps each
        entity legible as the single unit it is.
        """
        for code, value in pairs:
            self.pair(code, value)

    # -- structure ---------------------------------------------------------

    def begin(self, extent_min: Vec2, extent_max: Vec2) -> None:
        self.emit(
            (0, "SECTION"), (2, "HEADER"),
            (9, "$ACADVER"), (1, "AC1009"),                       # R12
            (9, "$INSUNITS"), (70, 6),                            # metres
            (9, "$EXTMIN"), (10, extent_min.x), (20, extent_min.y), (30, 0.0),
            (9, "$EXTMAX"), (10, extent_max.x), (20, extent_max.y), (30, 0.0),
            (0, "ENDSEC"),
        )

        self.emit(
            (0, "SECTION"), (2, "TABLES"),
            (0, "TABLE"), (2, "LAYER"), (70, len(LAYERS)),
        )
        for name, colour in LAYERS.items():
            self.emit(
                (0, "LAYER"), (2, name), (70, 0), (62, colour), (6, "CONTINUOUS"),
            )
        self.emit((0, "ENDTAB"), (0, "ENDSEC"))

        self.emit((0, "SECTION"), (2, "ENTITIES"))

    def end(self) -> str:
        self.emit((0, "ENDSEC"), (0, "EOF"))
        return "\n".join(self.lines) + "\n"

    # -- entities ----------------------------------------------------------

    def line(self, a: Vec2, b: Vec2, layer: str) -> None:
        self.emit(
            (0, "LINE"), (8, layer),
            (10, a.x), (20, a.y), (30, 0.0),
            (11, b.x), (21, b.y), (31, 0.0),
        )

    def polyline(self, points: list[Vec2], layer: str, closed: bool = True) -> None:
        """R12 POLYLINE/VERTEX/SEQEND.

        LWPOLYLINE is tidier but is an R14 entity; emitting the heavier R12
        form keeps the file readable by the widest range of software, which is
        the entire point of choosing R12.
        """
        if len(points) < 2:
            return
        self.emit(
            (0, "POLYLINE"), (8, layer),
            (66, 1),                           # vertices follow
            (70, 1 if closed else 0),
            (10, 0.0), (20, 0.0), (30, 0.0),
        )
        for point in points:
            self.emit(
                (0, "VERTEX"), (8, layer),
                (10, point.x), (20, point.y), (30, 0.0),
            )
        self.emit((0, "SEQEND"), (8, layer))

    def text(self, at: Vec2, value: str, layer: str, height: float = 0.25,
             rotation: float = 0.0, centred: bool = False) -> None:
        self.emit(
            (0, "TEXT"), (8, layer),
            (10, at.x), (20, at.y), (30, 0.0),
            (40, height), (1, value),
        )
        if rotation:
            self.pair(50, rotation)
        if centred:
            self.emit(
                (72, 1),                       # horizontally centred
                (11, at.x), (21, at.y), (31, 0.0),
            )

    def circle(self, centre: Vec2, radius: float, layer: str) -> None:
        self.emit(
            (0, "CIRCLE"), (8, layer),
            (10, centre.x), (20, centre.y), (30, 0.0),
            (40, radius),
        )

    def arc(self, centre: Vec2, radius: float, start_deg: float, end_deg: float, layer: str) -> None:
        self.emit(
            (0, "ARC"), (8, layer),
            (10, centre.x), (20, centre.y), (30, 0.0),
            (40, radius), (50, start_deg), (51, end_deg),
        )


def _wall_outline(wall: Wall) -> list[Vec2]:
    """The four corners of a wall at its true thickness."""
    direction = wall.direction_vector
    if direction.length < 1e-9:
        return []
    normal = direction.perpendicular() * (wall.thickness / 2)
    return [wall.start + normal, wall.end + normal, wall.end - normal, wall.start - normal]


def export_dxf(plan: FloorPlan, level_index: int = 0) -> str:
    """Emit one level as an R12 DXF drawing in metres."""
    level = plan.level_at(level_index)
    if level is None:
        writer = DxfWriter()
        writer.begin(Vec2(0, 0), Vec2(1, 1))
        writer.text(Vec2(0, 0), "NO LEVEL", "A-ANNO")
        return writer.end()

    env = level.envelope()
    writer = DxfWriter()
    writer.begin(Vec2(env.min_x - 2, env.min_y - 2), Vec2(env.max_x + 2, env.max_y + 2))

    _emit_grid(writer, plan)
    _emit_walls(writer, level)
    _emit_openings(writer, level)
    _emit_rooms(writer, plan, level)
    _emit_dimensions(writer, level)
    _emit_annotation(writer, plan, level, env)

    return writer.end()


def _emit_walls(w: DxfWriter, level: Level) -> None:
    for wall in level.walls:
        outline = _wall_outline(wall)
        if outline:
            w.polyline(outline, "A-WALL", closed=True)


def _emit_openings(w: DxfWriter, level: Level) -> None:
    for wall in level.walls:
        direction = wall.direction_vector
        if direction.length < 1e-9:
            continue
        for opening in wall.openings:
            centre = wall.point_at(opening.position)
            half = direction * (opening.width / 2)
            start, end = centre - half, centre + half

            if opening.kind.is_glazed:
                inner = direction.perpendicular() * (wall.thickness * 0.18)
                w.line(start + inner, end + inner, "A-GLAZ")
                w.line(start - inner, end - inner, "A-GLAZ")
                w.line(start, end, "A-GLAZ")
            else:
                # Leaf plus swing arc: the standard plan symbol, so the door
                # reads correctly the moment the file is opened.
                leaf_end = start + direction.perpendicular() * opening.width
                w.line(start, leaf_end, "A-DOOR")
                base = math.degrees(math.atan2(direction.y, direction.x))
                w.arc(start, opening.width, base, base + 90, "A-DOOR")
                if opening.kind is OpeningKind.MAIN_DOOR:
                    w.text(centre, "MAIN ENTRY", "A-DOOR", height=0.16, centred=True)


def _emit_rooms(w: DxfWriter, plan: FloorPlan, level: Level) -> None:
    for room in level.rooms:
        centre = room.centre
        box = room.bbox
        # The room boundary itself, as a closed polyline on the area layer.
        # This is what area takeoff and space schedules read in a practice's
        # own workflow, and it is also what makes the file re-importable:
        # walls alone do not say where one room stops and the next begins.
        w.polyline(list(room.polygon), "A-AREA", closed=True)
        if min(box.width, box.height) < 1.0:
            continue
        w.text(Vec2(centre.x, centre.y + 0.18), room.display_name().upper(),
               "A-AREA", height=0.26, centred=True)
        w.text(Vec2(centre.x, centre.y - 0.22), f"{room.area:.2f} SQ.M",
               "A-AREA", height=0.18, centred=True)
        w.text(Vec2(centre.x, centre.y - 0.52),
               f"{box.width:.2f} x {box.height:.2f}", "A-AREA", height=0.15, centred=True)


def _emit_grid(w: DxfWriter, plan: FloorPlan) -> None:
    grid = plan.column_grid
    if grid is None:
        return
    env = plan.envelope()
    xs, ys = [grid.origin.x], [grid.origin.y]
    for dx in grid.x_spacings:
        xs.append(xs[-1] + dx)
    for dy in grid.y_spacings:
        ys.append(ys[-1] + dy)

    for i, x in enumerate(xs):
        w.line(Vec2(x, env.min_y - 1.2), Vec2(x, env.max_y + 1.2), "A-GRID")
        w.circle(Vec2(x, env.max_y + 1.5), 0.28, "A-GRID")
        w.text(Vec2(x, env.max_y + 1.42), chr(ord("A") + i), "A-GRID", height=0.22, centred=True)
    for j, y in enumerate(ys):
        w.line(Vec2(env.min_x - 1.2, y), Vec2(env.max_x + 1.2, y), "A-GRID")
        w.circle(Vec2(env.min_x - 1.5, y), 0.28, "A-GRID")
        w.text(Vec2(env.min_x - 1.5, y - 0.08), str(j + 1), "A-GRID", height=0.22, centred=True)

    cw, cd = grid.column_size
    for x in xs:
        for y in ys:
            w.polyline([
                Vec2(x - cw / 2, y - cd / 2), Vec2(x + cw / 2, y - cd / 2),
                Vec2(x + cw / 2, y + cd / 2), Vec2(x - cw / 2, y + cd / 2),
            ], "S-COLS", closed=True)


def _emit_dimensions(w: DxfWriter, level: Level) -> None:
    """Overall dimension strings as plain geometry.

    R12 associative DIMENSION entities need a block table and a dimension style
    to render consistently across CAD packages; emitting the witness lines and
    text directly is portable and plots identically everywhere.
    """
    box = level.envelope()
    off = 0.9
    tick = 0.12

    y = box.min_y - off
    w.line(Vec2(box.min_x, y), Vec2(box.max_x, y), "A-DIMS")
    for x in (box.min_x, box.max_x):
        w.line(Vec2(x, y - tick), Vec2(x, y + tick), "A-DIMS")
        w.line(Vec2(x, y), Vec2(x, box.min_y), "A-DIMS")
    w.text(Vec2((box.min_x + box.max_x) / 2, y + 0.14), f"{box.width:.3f}",
           "A-DIMS", height=0.22, centred=True)

    x = box.min_x - off
    w.line(Vec2(x, box.min_y), Vec2(x, box.max_y), "A-DIMS")
    for yy in (box.min_y, box.max_y):
        w.line(Vec2(x - tick, yy), Vec2(x + tick, yy), "A-DIMS")
        w.line(Vec2(x, yy), Vec2(box.min_x, yy), "A-DIMS")
    w.text(Vec2(x - 0.16, (box.min_y + box.max_y) / 2), f"{box.height:.3f}",
           "A-DIMS", height=0.22, rotation=90.0)


def _emit_annotation(w: DxfWriter, plan: FloorPlan, level: Level, env) -> None:
    # North point, rotated to the site's true north.
    cx, cy = env.max_x + 1.2, env.max_y - 0.6
    angle = math.radians(-plan.site.north_angle)
    tip = Vec2(cx + 0.7 * math.sin(angle), cy + 0.7 * math.cos(angle))
    tail = Vec2(cx - 0.4 * math.sin(angle), cy - 0.4 * math.cos(angle))
    w.line(tail, tip, "A-ANNO")
    w.circle(Vec2(cx, cy), 0.75, "A-ANNO")
    w.text(Vec2(tip.x, tip.y + 0.12), "N", "A-ANNO", height=0.28, centred=True)

    y = env.min_y - 2.0
    for i, line in enumerate([
        f"{plan.name.upper()} - {level.display_name().upper()}",
        f"BUILT-UP {level.built_area:.2f} SQ.M   CARPET {level.carpet_area:.2f} SQ.M",
        f"FAR {plan.achieved_far:.2f} OF {plan.site.max_far:.2f}   "
        f"COVERAGE {(plan.footprint_area / plan.site.plot_area * 100) if plan.site.plot_area else 0:.1f}%",
        "UNITS: METRES.  ALL DIMENSIONS TO BE VERIFIED ON SITE.",
        "GENERATED BY ARCHITECT INTELLIGENCE PLATFORM - NOT FOR CONSTRUCTION.",
    ]):
        w.text(Vec2(env.min_x, y - i * 0.38), line, "A-ANNO", height=0.24)


def export_dxf_all_levels(plan: FloorPlan) -> dict[str, str]:
    """One DXF per level, keyed by a filename stem."""
    return {
        f"{plan.name.replace(' ', '_').lower()}_level_{level.index}": export_dxf(plan, level.index)
        for level in plan.levels
    }
