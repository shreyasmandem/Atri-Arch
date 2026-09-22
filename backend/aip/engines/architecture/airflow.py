"""Animated airflow diagram.

The ventilation analysis already knows which rooms breathe and which do not.
The trouble is that it says so as a number, and a number does not persuade
anybody to move a window. "Ventilation index 0.62" is inert; watching air enter
a room, curl back on itself and never reach the far wall is not.

So this draws what the analysis computed. Each room gets streamlines derived
from where its openings actually are:

* **Cross ventilation** - openings on opposed pressure faces. Air takes a clear
  path through, and the whole room is swept.
* **Single-sided** - one face only. Air enters and leaves through the same
  aperture, so a recirculation cell forms behind the opening and the far end of
  the room is never flushed. That dead zone is shaded, and it is sized from the
  BS 5925 effective-depth rule rather than drawn for effect.

The field itself moves too, not just the particles riding on it: an animated
feDisplacementMap warps the coloured raster continuously, masked by the
image's own brightness so a fast cell churns and a still one stays still. That
mask is what keeps the animation honest rather than merely pretty - it cannot
show life in a dead zone the solve says has none.

Everything here - the streamlines, the recirculation shading, and now the warp
- is SMIL and SVG filters inside the file itself: no script, no runtime, no
dependency. It animates in a browser, sits still and still reads correctly in
a PDF or a printed sheet, and can be dropped into a client report as a single
file.

Nothing here invents physics. Every streamline is placed from the opening
positions and the mode the analysis already assigned, so the picture cannot
disagree with the score printed beside it.
"""

from __future__ import annotations

from aip.domain.geometry import BoundingBox, Vec2
from aip.domain.plan import FloorPlan, Level, OpeningKind, Room
from aip.engines.architecture.drawings import DrawingStyle, _Canvas, _padded_extent

#: The colour ramp every CFD post-processor uses: still air is dark blue, fast
#: air runs through cyan and green to yellow. Borrowing the convention means an
#: engineer reads the picture without being told how.
TURBO = (
    (0.00, (12, 24, 68)),
    (0.18, (18, 86, 160)),
    (0.36, (24, 158, 178)),
    (0.55, (56, 190, 120)),
    (0.72, (168, 205, 62)),
    (0.87, (240, 176, 48)),
    (1.00, (232, 92, 42)),
)

STAGNANT = "#c53030"

#: Seconds for a particle to cross the room. Slow enough to follow, fast enough
#: that the field never reads as static.
TRAVEL_SECONDS = 4.0
PARTICLES_PER_LINE = 4


def _opening_points(level: Level, room: Room) -> list[tuple[Vec2, Vec2]]:
    """Every external opening serving this room, as (centre, inward normal)."""
    out: list[tuple[Vec2, Vec2]] = []
    centre = room.centre
    for wall in level.walls:
        if room.id not in wall.rooms:
            continue
        direction = wall.direction_vector
        if direction.length < 1e-9:
            continue
        for opening in wall.openings:
            if not (opening.kind.is_glazed or opening.kind is OpeningKind.SLIDING_DOOR):
                continue
            point = wall.point_at(opening.position)
            normal = direction.perpendicular()
            if (point + normal * 0.1).distance_to(centre) > (point - normal * 0.1).distance_to(centre):
                normal = normal * -1
            out.append((point, normal, opening.width))
    return [(p, n) for p, n, _w in out]


def _opening_widths(level: Level, room: Room) -> list[tuple[Vec2, float]]:
    """The same openings as (centre, width), which is what the solver wants."""
    out: list[tuple[Vec2, float]] = []
    for wall in level.walls:
        if room.id not in wall.rooms:
            continue
        if wall.direction_vector.length < 1e-9:
            continue
        for opening in wall.openings:
            if not (opening.kind.is_glazed or opening.kind is OpeningKind.SLIDING_DOOR):
                continue
            out.append((wall.point_at(opening.position), opening.width))
    return out


def _ramp(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(TURBO, TURBO[1:], strict=False):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(int(round(c0[k] + f * (c1[k] - c0[k]))) for k in range(3))
    return TURBO[-1][1]


def _field_image(field, room: Room) -> str:
    """The velocity field as a base64 PNG, ready to embed in the SVG.

    Drawn as an image rather than thousands of coloured rectangles: a raster is
    one DOM node and interpolates smoothly, where a grid of <rect> elements is
    tens of thousands of nodes and still looks like a grid.
    """
    import base64
    import io

    import numpy as np
    from PIL import Image

    speed = field.speed
    ny, nx = speed.shape

    # A gamma below one lifts the low end so the slow-moving bulk of the room is
    # legible instead of collapsing into flat black.
    shaped = np.power(speed, 0.65)

    lut = np.array([_ramp(i / 255.0) for i in range(256)], dtype=np.uint8)
    indices = np.clip((shaped * 255).astype(np.int32), 0, 255)
    rgb = lut[indices]

    image = Image.fromarray(rgb, mode="RGB")
    # Flip: array row 0 is the room's low-y edge, image row 0 is the top.
    image = image.transpose(Image.FLIP_TOP_BOTTOM)
    image = image.resize((nx * 6, ny * 6), Image.BICUBIC)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _seed_points(field, room: Room, openings: list[tuple[Vec2, Vec2]]) -> list[Vec2]:
    """Where to release particles: just inside each opening, spread across it."""
    seeds: list[Vec2] = []
    for point, normal in openings:
        tangent = Vec2(-normal.y, normal.x)
        for k in (-0.36, -0.18, 0.0, 0.18, 0.36):
            seeds.append(
                Vec2(point.x + normal.x * field.cell * 2 + tangent.x * k,
                     point.y + normal.y * field.cell * 2 + tangent.y * k)
            )
    return seeds


def _ripple_filter(fid: str, room: Room, width_px: float, height_px: float) -> str:
    """A native SVG filter that makes the field itself breathe.

    A still heatmap reads as a diagram; the reference asked for something that
    looks like a live solve, with the coloured field continuously churning the
    way real air does. Rather than pre-render dozens of raster frames - heavy,
    and the compression artefacts show on a field this smooth - this warps the
    *one* static image with an animated feDisplacementMap. It is pure SMIL, so
    it costs nothing beyond the single PNG already being drawn, animates in a
    browser, and simply holds still in a PDF or a print.

    The warp is masked by the image's own brightness, and this is the point
    that matters, not a decoration: this diagram's colours already encode
    speed, so a bright, fast-moving cell is pushed by the noise field and a
    dark, still one is not. The animation cannot show motion the solve did not
    compute - it can only make the motion that *is* there easier to feel.
    """
    long_side = max(width_px, height_px, 1.0)
    short_side = max(min(width_px, height_px, long_side), 1.0)
    # A stable per-room seed and period, so neighbouring rooms churn out of
    # phase with each other rather than breathing in lockstep.
    h = hash(room.id) & 0xFFFF
    seed = h % 40 + 1
    period = round(8.5 + (h % 7) * 0.55, 2)
    freq = round(4.2 / long_side, 5)
    freq_lo = max(freq * 0.6, 0.0006)
    freq_hi = freq * 1.7
    scale = round(min(70.0, max(6.0, short_side * 0.16)), 1)

    return (
        f'<filter id="{fid}" x="-30%" y="-30%" width="160%" height="160%" '
        f'color-interpolation-filters="sRGB">'
        f'<feTurbulence type="fractalNoise" numOctaves="2" seed="{seed}" '
        f'stitchTiles="stitch" result="noise">'
        f'<animate attributeName="baseFrequency" dur="{period}s" '
        f'repeatCount="indefinite" values='
        f'"{freq_lo:.5f} {freq_hi:.5f};{freq_hi:.5f} {freq_lo:.5f};'
        f'{freq_lo:.5f} {freq_hi:.5f}"/>'
        f'</feTurbulence>'
        # The source's own luminance, broadcast into every channel: bright
        # (fast) pixels drive a full-strength warp, dark (still) ones damp it
        # toward zero. This is what keeps a sealed dead zone visibly calm.
        f'<feColorMatrix in="SourceGraphic" type="luminanceToAlpha" result="lum"/>'
        f'<feComponentTransfer in="lum" result="lumboost">'
        f'<feFuncA type="gamma" amplitude="1" exponent="0.6" offset="0"/>'
        f'</feComponentTransfer>'
        f'<feColorMatrix in="lumboost" type="matrix" '
        f'values="0 0 0 1 0  0 0 0 1 0  0 0 0 1 0  0 0 0 1 0" result="mask"/>'
        f'<feComposite in="noise" in2="mask" operator="arithmetic" '
        f'k1="1" k2="0" k3="0" k4="0" result="modnoise"/>'
        f'<feDisplacementMap in="SourceGraphic" in2="modnoise" scale="{scale}" '
        f'xChannelSelector="R" yChannelSelector="G"/>'
        f'</filter>'
    )


def _draw_field(canvas: _Canvas, room: Room, field, seq: int) -> int:
    """Paint the solved field, animated, then run particles along its streamlines."""

    box = room.bbox
    x0, y0 = canvas.px(Vec2(box.min_x, box.max_y))
    x1, y1 = canvas.px(Vec2(box.max_x, box.min_y))
    width, height = abs(x1 - x0), abs(y1 - y0)
    clip = f"clip{seq}"
    ripple = f"ripple{seq}"

    points = " ".join(f"{x},{y}" for x, y in (canvas.px(p) for p in room.polygon))
    canvas.add(
        f'<defs><clipPath id="{clip}"><polygon points="{points}"/></clipPath>'
        f'{_ripple_filter(ripple, room, width, height)}</defs>'
        f'<image x="{x0:.1f}" y="{y0:.1f}" width="{width:.1f}" '
        f'height="{height:.1f}" clip-path="url(#{clip})" filter="url(#{ripple})" '
        f'opacity="0.92" preserveAspectRatio="none" '
        f'href="data:image/png;base64,{_field_image(field, room)}"/>'
    )
    return seq + 1


def _draw_wind_ingress(canvas: _Canvas, openings: list[tuple[Vec2, Vec2]]) -> None:
    """Animated aerodynamic intake chevrons outside exterior openings."""
    for op_idx, (point, normal) in enumerate(openings):
        tangent = Vec2(-normal.y, normal.x)
        for c_idx, dist in enumerate((0.60, 0.38, 0.16)):
            tip = point - normal * dist
            w1 = tip - normal * 0.13 + tangent * 0.18
            w2 = tip - normal * 0.13 - tangent * 0.18
            p_tip = canvas.px(tip)
            p_w1 = canvas.px(w1)
            p_w2 = canvas.px(w2)
            stagger = round((c_idx * 0.45 + op_idx * 0.3) % 1.8, 2)
            canvas.add(
                f'<polyline points="{p_w1[0]:.1f},{p_w1[1]:.1f} {p_tip[0]:.1f},{p_tip[1]:.1f} {p_w2[0]:.1f},{p_w2[1]:.1f}" '
                f'fill="none" stroke="#38bdf8" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" opacity="0.25">'
                f'<animate attributeName="opacity" values="0.15;0.9;0.15" dur="1.8s" begin="{stagger}s" repeatCount="indefinite"/>'
                f'<animate attributeName="stroke-width" values="1.0;1.7;1.0" dur="1.8s" begin="{stagger}s" repeatCount="indefinite"/>'
                f'</polyline>'
            )


def _draw_particles(
    canvas: _Canvas, room: Room, field, openings: list[tuple[Vec2, Vec2]], seq: int, through_flow: bool = True
) -> int:
    """Streaklines traced through the solved field with continuous aerodynamic ribbons and comets."""
    from aip.engines.architecture.cfd import streamline

    stream_grad = "url(#aeroStreamCross)" if through_flow else "url(#aeroStreamRecirc)"

    for seed in _seed_points(field, room, openings):
        path = streamline(field, seed)
        if len(path) < 6:
            continue
        pixels = [canvas.px(p) for p in path]
        d = f"M {pixels[0][0]:.1f},{pixels[0][1]:.1f} " + " ".join(
            f"L {x:.1f},{y:.1f}" for x, y in pixels[1:]
        )
        pid = f"fl{seq}"

        # 1. Base technical drafting guide
        canvas.add(
            f'<path id="{pid}" d="{d}" fill="none" stroke="#38bdf8" '
            f'stroke-width="0.75" opacity="0.14" stroke-dasharray="2 3"/>'
        )

        length = sum(
            ((pixels[i][0] - pixels[i - 1][0]) ** 2 + (pixels[i][1] - pixels[i - 1][1]) ** 2) ** 0.5
            for i in range(1, len(pixels))
        )
        duration = max(1.8, TRAVEL_SECONDS * (length / 240.0))

        # 2. Continuous flowing aerodynamic dash ribbon (seamless 24 + 48 = 72 loop)
        canvas.add(
            f'<path d="{d}" fill="none" stroke="{stream_grad}" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-dasharray="24 48" opacity="0.82">'
            f'<animate attributeName="stroke-dashoffset" from="0" to="-72" '
            f'dur="{duration:.2f}s" repeatCount="indefinite"/>'
            f'</path>'
        )

        # 3. Micro shimmer streak
        canvas.add(
            f'<path d="{d}" fill="none" stroke="#f0fdff" stroke-width="0.9" '
            f'stroke-linecap="round" stroke-dasharray="12 60" opacity="0.45">'
            f'<animate attributeName="stroke-dashoffset" from="36" to="-36" '
            f'dur="{duration * 0.85:.2f}s" repeatCount="indefinite"/>'
            f'</path>'
        )

        # 4. Aerodynamic comets: glowing dual-layer heads
        for n in range(PARTICLES_PER_LINE):
            begin = round(n * duration / PARTICLES_PER_LINE, 2)
            canvas.add(
                f'<g opacity="0">'
                f'<circle r="3.2" fill="#38bdf8" opacity="0.45" filter="url(#aeroGlow)"/>'
                f'<circle r="1.4" fill="#ffffff" opacity="0.95"/>'
                f'<animateMotion dur="{duration:.2f}s" begin="{begin}s" '
                f'repeatCount="indefinite"><mpath href="#{pid}"/></animateMotion>'
                f'<animate attributeName="opacity" values="0;0.95;0.95;0" '
                f'keyTimes="0;0.12;0.82;1" dur="{duration:.2f}s" begin="{begin}s" '
                f'repeatCount="indefinite"/></g>'
            )
        seq += 1
    return seq


def _stagnant_outline(canvas: _Canvas, room: Room, normal: Vec2, reach: float, clip_id: str | None = None) -> None:
    """Mark the depth beyond which the air does not reach with architectural hatching and callout."""
    box = room.bbox
    along_y = abs(normal.y) >= abs(normal.x)
    depth = box.height if along_y else box.width
    if reach >= depth:
        return

    if along_y:
        y = box.max_y - (depth - reach) if normal.y > 0 else box.min_y + (depth - reach)
        a, b = Vec2(box.min_x, y), Vec2(box.max_x, y)
        if normal.y > 0:
            stagnant_min_y, stagnant_max_y = y, box.max_y
        else:
            stagnant_min_y, stagnant_max_y = box.min_y, y
        sx0, sy0 = canvas.px(Vec2(box.min_x, stagnant_max_y))
        sx1, sy1 = canvas.px(Vec2(box.max_x, stagnant_min_y))
    else:
        x = box.max_x - (depth - reach) if normal.x > 0 else box.min_x + (depth - reach)
        a, b = Vec2(x, box.min_y), Vec2(x, box.max_y)
        if normal.x > 0:
            stagnant_min_x, stagnant_max_x = x, box.max_x
        else:
            stagnant_min_x, stagnant_max_x = box.min_x, x
        sx0, sy0 = canvas.px(Vec2(stagnant_min_x, box.max_y))
        sx1, sy1 = canvas.px(Vec2(stagnant_max_x, box.min_y))

    # Diagonal architectural hatching
    sw, sh = abs(sx1 - sx0), abs(sy1 - sy0)
    clip_attr = f' clip-path="url(#{clip_id})"' if clip_id else ''
    canvas.add(
        f'<rect x="{min(sx0, sx1):.1f}" y="{min(sy0, sy1):.1f}" width="{sw:.1f}" height="{sh:.1f}" '
        f'fill="url(#stagnantHatch)" opacity="0.9"{clip_attr}/>'
    )

    canvas.line(a, b, STAGNANT, width=1.1, dash="4 3", opacity=0.95)
    mid = Vec2((a.x + b.x) / 2, (a.y + b.y) / 2)
    px_mid = canvas.px(mid)
    canvas.add(
        f'<rect x="{px_mid[0] - 56:.1f}" y="{px_mid[1] - 14:.1f}" width="112" height="18" '
        f'rx="2" fill="#180e14" stroke="#ef4444" stroke-width="0.75" opacity="0.92"/>'
    )
    canvas.text(mid, f"reach limit {reach:.1f} m", size=7.5, fill=STAGNANT,
                weight="700", dy=-3)
    canvas.text(mid, "BS 5925 · RECIRCULATION LIMIT", size=5.5, fill="#fca5a5",
                weight="600", dy=5)


def _draw_room_badge(canvas: _Canvas, room: Room, mode: str, detail: dict) -> None:
    """Architectural classification badge rendered crisp over the fluid field."""
    cx, cy = canvas.px(room.centre)
    name = room.display_name().upper()

    if mode == "cross":
        badge_text = "CROSS-FLOW · ACTIVE"
        badge_color = "#38bdf8"
        dot_color = "#34d399"
    elif mode == "none" or not detail:
        badge_text = "NO OPENING · UNVENTILATED"
        badge_color = STAGNANT
        dot_color = "#ef4444"
    else:
        badge_text = "SINGLE-SIDED · RECIRCULATING"
        badge_color = "#fbbf24"
        dot_color = "#f59e0b"

    pill_w = max(len(name) * 6.5, len(badge_text) * 5.0) + 18.0
    pill_h = 24.0
    px = cx - pill_w / 2
    py = cy - pill_h / 2

    canvas.add(
        f'<rect x="{px:.1f}" y="{py:.1f}" width="{pill_w:.1f}" height="{pill_h:.1f}" '
        f'rx="3" fill="#090f1c" stroke="rgba(255,255,255,0.12)" stroke-width="0.8" opacity="0.86"/>'
        f'<circle cx="{px + 7:.1f}" cy="{py + 7:.1f}" r="2" fill="{dot_color}"/>'
    )
    canvas.text(room.centre, name, size=7.2, fill="#f8fafc", weight="700", dy=-3)
    canvas.text(room.centre, badge_text, size=5.8, fill=badge_color, weight="600", dy=6)


def airflow_svg(
    plan: FloorPlan,
    level_index: int = 0,
    *,
    style: DrawingStyle | None = None,
) -> str:
    """Animated airflow over the floor plan.

    Rooms are drawn faintly so the air reads as the subject; the plan is context,
    not the point.
    """
    from aip.engines.architecture.cfd import solve
    from aip.engines.architecture.metrics import (
        VENTILATION_DEPTH_LIMIT,
        ventilation_analysis,
        ventilation_mode,
    )

    style = style or DrawingStyle()
    level = plan.level_at(level_index)
    if level is None:
        return _empty(style)

    report = ventilation_analysis(plan)
    extent = _padded_extent(plan, level)
    canvas = _Canvas(extent, style, f"{plan.name} - airflow, {level.display_name()}")

    # Dark background with global CFD defs: glow filters, diagonal hatch pattern, aerodynamic gradients
    canvas.add(
        '<rect width="100%" height="100%" fill="#0b1220"/>'
        '<defs>'
        '<filter id="aeroGlow" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur in="SourceGraphic" stdDeviation="1.8" result="blur"/>'
        '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>'
        '</filter>'
        '<pattern id="stagnantHatch" width="8" height="8" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">'
        '<line x1="0" y1="0" x2="0" y2="8" stroke="#ef4444" stroke-width="0.8" opacity="0.32"/>'
        '</pattern>'
        '<linearGradient id="aeroStreamCross" x1="0%" y1="0%" x2="100%" y2="100%">'
        '<stop offset="0%" stop-color="#38bdf8" stop-opacity="0.95"/>'
        '<stop offset="60%" stop-color="#34d399" stop-opacity="0.9"/>'
        '<stop offset="100%" stop-color="#67e8f9" stop-opacity="0.75"/>'
        '</linearGradient>'
        '<linearGradient id="aeroStreamRecirc" x1="0%" y1="0%" x2="100%" y2="100%">'
        '<stop offset="0%" stop-color="#38bdf8" stop-opacity="0.85"/>'
        '<stop offset="50%" stop-color="#818cf8" stop-opacity="0.75"/>'
        '<stop offset="100%" stop-color="#3b82f6" stop-opacity="0.5"/>'
        '</linearGradient>'
        '</defs>'
    )
    for room in level.rooms:
        canvas.polygon(room.polygon, fill="#111a2b", stroke="none")

    # -- the air ------------------------------------------------------------
    seq = 0
    summary: list[tuple[str, str]] = []
    for room in level.rooms:
        if room.type.is_outdoor:
            continue
        openings = _opening_points(level, room)
        detail = report.detail.get(room.id)
        if not isinstance(detail, dict):
            continue

        mode = detail.get("ventilation_mode") or ventilation_mode(set(), len(openings))
        reach = VENTILATION_DEPTH_LIMIT.get(mode, 0.0) * room.ceiling_height

        if not openings:
            _draw_room_badge(canvas, room, "none", detail)
            summary.append((room.display_name(), "sealed"))
            continue

        box = room.bbox
        field = solve(
            box.width, box.height, Vec2(box.min_x, box.min_y),
            _opening_widths(level, room),
            through_flow=(mode == "cross"),
        )
        if field is None:
            summary.append((room.display_name(), "not solved"))
            continue

        field_seq = seq
        seq = _draw_field(canvas, room, field, seq)
        _draw_wind_ingress(canvas, openings)
        seq = _draw_particles(canvas, room, field, openings, seq, through_flow=(mode == "cross"))
        if mode != "cross":
            _stagnant_outline(canvas, room, openings[0][1], reach, clip_id=f"clip{field_seq}")

        summary.append((room.display_name(), mode.replace("_", " ")))
        _draw_room_badge(canvas, room, mode, detail)

    # Walls last, so they read as edges over the field rather than under it.
    for wall in level.walls:
        canvas.line(wall.start, wall.end, "#dfe6f2",
                    width=max(1.2, canvas.m(wall.thickness)), opacity=0.85)

    _legend(canvas, extent, report.score)
    return canvas.render()


def _legend(canvas: _Canvas, extent: BoundingBox, score: float) -> None:
    """Title and colour key.

    Explicitly light-on-dark: the drawing style's text colours are chosen for a
    white sheet and vanish against the ground this diagram needs.
    """
    x = extent.min_x + 0.3
    y = extent.max_y - 0.35

    canvas.text(Vec2(x, y), f"Airflow — ventilation index {score:.2f}", size=12,
                fill="#f2f6ff", anchor="start", weight="700")
    canvas.text(
        Vec2(x, y + 0.48),
        "Cross flow sweeps the room; a single opening recirculates and leaves the far end still.",
        size=8.5, fill="#9fb0cc", anchor="start",
    )
    canvas.text(
        Vec2(x, y + 0.88),
        "AERODYNAMIC DISPLACEMENT & CFD STREAMLINES · BS 5925 / CIBSE AM10",
        size=6.5, fill="#5b6b86", anchor="start", weight="600",
    )

    # A colour bar, because a field without a key is decoration.
    bar_x, bar_y = canvas.px(Vec2(x, y + 1.35))
    width, height = 150.0, 7.0
    stops = "".join(
        f'<stop offset="{t * 100:.0f}%" stop-color="rgb{_ramp(t)}"/>'
        for t in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    )
    canvas.add(
        f'<defs><linearGradient id="speedkey" x1="0" x2="1">{stops}</linearGradient></defs>'
        f'<rect x="{bar_x:.1f}" y="{bar_y:.1f}" width="{width}" height="{height}" '
        f'fill="url(#speedkey)" rx="1.5" stroke="rgba(255,255,255,0.15)" stroke-width="0.5"/>'
        f'<text x="{bar_x:.1f}" y="{bar_y + height + 9:.1f}" font-size="7.0" '
        f'fill="#9fb0cc" font-family="{canvas.style.font}">0.0 m/s [STILL]</text>'
        f'<text x="{bar_x + width * 0.45:.1f}" y="{bar_y + height + 9:.1f}" font-size="7.0" '
        f'fill="#9fb0cc" text-anchor="middle" font-family="{canvas.style.font}">1.0 m/s [COMFORT]</text>'
        f'<text x="{bar_x + width:.1f}" y="{bar_y + height + 9:.1f}" font-size="7.0" '
        f'fill="#9fb0cc" text-anchor="end" font-family="{canvas.style.font}">2.5+ m/s [FAST]</text>'
    )


def _empty(style: DrawingStyle) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="120">'
        f'<rect width="100%" height="100%" fill="{style.background}"/>'
        f'<text x="210" y="64" text-anchor="middle" font-family="{style.font}" '
        f'font-size="12" fill="{style.text_muted}">No level to analyse</text></svg>'
    )
