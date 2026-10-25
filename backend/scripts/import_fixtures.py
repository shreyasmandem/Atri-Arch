"""Realistic floor-plan files for exercising the importer.

Writes, into backend/var/fixtures/:

* own.dxf / own.svg          - the platform's own exports (rooms as closed shapes)
* walls.dxf                  - what AutoCAD users actually send: walls as LINE
                               and LWPOLYLINE linework with gaps at the doors,
                               room names as TEXT/MTEXT, a dimension layer and
                               furniture blocks as noise, units in millimetres
* walls.svg                  - the same linework as SVG <line>/<path> inside a
                               transformed <g>, labels as <text>, like Illustrator
                               or Inkscape exports
* scan.png                   - a raster rendering: thick black walls with door
                               gaps, text labels, dimension strings, a little
                               noise and a slight rotation, like a phone photo
                               of a printed plan
* sketch.jpg                 - a lower-contrast JPEG with thinner walls

Run:  python -m scripts.import_fixtures   (from backend/)
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from aip.domain.brief import default_residence_brief
from aip.domain.plan import FloorPlan
from aip.engines.architecture.drawings import floor_plan_svg
from aip.engines.architecture.dxf import export_dxf
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator

OUT = Path(__file__).resolve().parent.parent / "var" / "fixtures"


def site_wh(plan: FloorPlan) -> tuple[float, float]:
    xs = [p.x for p in plan.site.boundary] or [0, 12]
    ys = [p.y for p in plan.site.boundary] or [0, 18]
    return max(xs) - min(xs), max(ys) - min(ys)


def make_plan() -> FloorPlan:
    brief = default_residence_brief()
    return LayoutGenerator(brief, GeneratorConfig(population=36, generations=32, seed=23, spine=False)).generate(1)[0]


def wall_segments(plan: FloorPlan, level: int = 0) -> list[tuple[tuple[float, float], tuple[float, float], float, list[tuple[float, float]]]]:
    """(start, end, thickness, door gaps as (t0, t1) fractions) per wall."""
    out = []
    lv = plan.levels[level]
    for w in lv.walls:
        gaps = []
        length = max(w.length, 1e-6)
        for o in w.openings:
            if not o.kind.is_door:
                continue
            half = (o.width / 2) / length
            gaps.append((max(0.0, o.position - half), min(1.0, o.position + half)))
        out.append(((w.start.x, w.start.y), (w.end.x, w.end.y), w.thickness, sorted(gaps)))
    return out


def pieces(seg, gaps):
    (x0, y0), (x1, y1) = seg
    cuts = [0.0]
    for a, b in gaps:
        cuts += [a, b]
    cuts.append(1.0)
    for i in range(0, len(cuts), 2):
        a, b = cuts[i], cuts[i + 1]
        if b - a > 1e-3:
            yield (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)


def walls_dxf(plan: FloorPlan) -> str:
    mm = 1000.0
    ents: list[str] = []

    def line(layer, a, b):
        ents.append(f"0\nLINE\n8\n{layer}\n10\n{a[0]*mm:.1f}\n20\n{a[1]*mm:.1f}\n30\n0\n11\n{b[0]*mm:.1f}\n21\n{b[1]*mm:.1f}\n31\n0")

    for (s, e, t, gaps) in wall_segments(plan):
        # Each wall drawn as its two faces, as a draughtsperson would.
        dx, dy = e[0] - s[0], e[1] - s[1]
        L = math.hypot(dx, dy) or 1
        nx, ny = -dy / L * t / 2, dx / L * t / 2
        for a, b in pieces((s, e), gaps):
            line("A-WALL", (a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny))
            line("A-WALL", (a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny))
    for r in plan.levels[0].rooms:
        c = r.centre
        ents.append(f"0\nMTEXT\n8\nA-ANNO\n10\n{c.x*mm:.1f}\n20\n{c.y*mm:.1f}\n30\n0\n40\n250\n1\n\\fArial|b1;{r.display_name().upper()}\\P{r.area:.1f} SQ.M")
    # Noise: a dimension line and a sofa block outline.
    sw, _ = site_wh(plan)
    line("A-DIMS", (0, -1.0), (sw, -1.0))
    ents.append(f"0\nTEXT\n8\nA-DIMS\n10\n{sw*mm/2:.1f}\n20\n{-1.3*mm:.1f}\n30\n0\n40\n200\n1\n{sw*mm:.0f}")
    body = "\n".join(ents)
    return f"0\nSECTION\n2\nHEADER\n9\n$INSUNITS\n70\n4\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n{body}\n0\nENDSEC\n0\nEOF\n"


def walls_svg(plan: FloorPlan) -> str:
    k = 30.0
    SW, H = site_wh(plan)
    parts = []
    for (s, e, t, gaps) in wall_segments(plan):
        for a, b in pieces((s, e), gaps):
            parts.append(f'<line x1="{a[0]*k:.1f}" y1="{(H-a[1])*k:.1f}" x2="{b[0]*k:.1f}" y2="{(H-b[1])*k:.1f}" stroke="#000" stroke-width="{max(4, t*k):.1f}"/>')
    for r in plan.levels[0].rooms:
        c = r.centre
        parts.append(f'<text x="{c.x*k:.1f}" y="{(H-c.y)*k:.1f}" font-size="11">{r.display_name()}</text>')
    inner = "\n".join(parts)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{SW*k+200:.0f}" height="{H*k+200:.0f}">'
            f'<g transform="translate(100,100)">{inner}</g></svg>')


def raster(plan: FloorPlan, *, px_per_m=60, wall_px=None, rotate=1.2, noise=10, jpeg=False, path: Path) -> None:
    W, H = site_wh(plan)
    M = 80
    img = Image.new("L", (int(W * px_per_m + 2 * M), int(H * px_per_m + 2 * M)), 250)
    d = ImageDraw.Draw(img)
    to = lambda p: (M + p[0] * px_per_m, M + (H - p[1]) * px_per_m)  # noqa: E731
    try:
        font = ImageFont.truetype("arial.ttf", int(px_per_m * 0.28))
        small = ImageFont.truetype("arial.ttf", int(px_per_m * 0.2))
    except OSError:
        font = small = ImageFont.load_default()
    for (s, e, t, gaps) in wall_segments(plan):
        width = wall_px or max(5, int(t * px_per_m))
        for a, b in pieces((s, e), gaps):
            d.line([to(a), to(b)], fill=20, width=width)
    for r in plan.levels[0].rooms:
        x, y = to((r.centre.x, r.centre.y))
        d.text((x, y - px_per_m * 0.18), r.display_name().upper(), fill=30, font=font, anchor="mm")
        d.text((x, y + px_per_m * 0.18), f"{r.bbox.width:.1f} x {r.bbox.height:.1f}", fill=60, font=small, anchor="mm")
    # A dimension string along the bottom, like a real drawing.
    y = M + H * px_per_m + 40
    d.line([(M, y), (M + W * px_per_m, y)], fill=60, width=2)
    d.text((M + W * px_per_m / 2, y + 16), f"{W*1000:.0f}", fill=40, font=small, anchor="mm")
    img = img.rotate(rotate, resample=Image.BICUBIC, expand=True, fillcolor=250)
    rnd = random.Random(7)
    px = img.load()
    for _ in range(int(img.width * img.height * 0.01)):
        x, yv = rnd.randrange(img.width), rnd.randrange(img.height)
        px[x, yv] = max(0, min(255, px[x, yv] + rnd.randint(-noise * 6, noise * 6)))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    if jpeg:
        img = img.point(lambda v: 70 + v * 0.65)   # washed out, like a phone photo
        img.convert("RGB").save(path, quality=72)
    else:
        img.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    plan = make_plan()
    (OUT / "truth.json").write_text(plan.model_dump_json(indent=1), encoding="utf-8")
    (OUT / "own.dxf").write_text(export_dxf(plan, 0), encoding="utf-8")
    (OUT / "own.svg").write_text(floor_plan_svg(plan, 0), encoding="utf-8")
    (OUT / "walls.dxf").write_text(walls_dxf(plan), encoding="utf-8")
    (OUT / "walls.svg").write_text(walls_svg(plan), encoding="utf-8")
    raster(plan, path=OUT / "scan.png")
    raster(plan, px_per_m=45, wall_px=4, rotate=-2.0, jpeg=True, path=OUT / "sketch.jpg")
    print("rooms in truth:", [(r.display_name(), round(r.area, 1)) for r in plan.levels[0].rooms])
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
