"""Score the importer against the fixtures written by import_fixtures.

For each file: did it import, how many rooms came back against the truth,
how many truth rooms were matched by name and position, and the mean
intersection-over-union of matched rooms.

Run:  python -m scripts.import_bench   (from backend/)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from shapely.geometry import Polygon

from aip.domain.plan import FloorPlan
from aip.engines.architecture.importer import ImportError_, import_floorplan

FIX = Path(__file__).resolve().parent.parent / "var" / "fixtures"


def poly(room) -> Polygon:
    return Polygon([(p.x, p.y) for p in room.polygon]).buffer(0)


def score(truth: FloorPlan, got: FloorPlan) -> dict:
    t_rooms = truth.levels[0].rooms
    g_rooms = got.levels[0].rooms if got.levels else []
    # Align: imported plans are re-scaled to the plot, so compare in each
    # plan's own normalised frame.
    def frame(rooms):
        ps = [poly(r) for r in rooms]
        xs = [c for p in ps for c in p.bounds[0::2]]
        ys = [c for p in ps for c in p.bounds[1::2]]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        sx, sy = (x1 - x0) or 1, (y1 - y0) or 1
        from shapely import affinity
        return [affinity.scale(affinity.translate(p, -x0, -y0), 1 / sx, 1 / sy, origin=(0, 0)) for p in ps]

    if not g_rooms:
        return {"rooms": 0, "matched": 0, "named": 0, "iou": 0.0}
    tp, gp = frame(t_rooms), frame(g_rooms)
    matched = named = 0
    ious = []
    used = set()
    for i, t in enumerate(tp):
        best, bj = 0.0, None
        for j, g in enumerate(gp):
            if j in used:
                continue
            inter = t.intersection(g).area
            iou = inter / max(t.union(g).area, 1e-9)
            if iou > best:
                best, bj = iou, j
        if bj is not None and best > 0.5:
            used.add(bj)
            matched += 1
            ious.append(best)
            if g_rooms[bj].type == t_rooms[i].type:
                named += 1
    return {"rooms": len(g_rooms), "matched": matched, "named": named,
            "iou": round(sum(ious) / len(ious), 3) if ious else 0.0}


async def main() -> None:
    truth = FloorPlan.model_validate(json.loads((FIX / "truth.json").read_text(encoding="utf-8")))
    print(f"truth: {len(truth.levels[0].rooms)} rooms")
    for name in ["own.dxf", "own.svg", "walls.dxf", "walls.svg", "scan.png", "sketch.jpg"]:
        path = FIX / name
        t0 = time.perf_counter()
        try:
            res = await import_floorplan(path.read_bytes(), name, plot_width=None, plot_depth=None)
            s = score(truth, res.plan)
            print(f"{name:12s} OK   {time.perf_counter()-t0:5.1f}s  rooms={s['rooms']:2d} matched={s['matched']:2d}/{len(truth.levels[0].rooms)} named={s['named']:2d} iou={s['iou']}")
        except ImportError_ as exc:
            print(f"{name:12s} FAIL {time.perf_counter()-t0:5.1f}s  {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name:12s} CRASH {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
