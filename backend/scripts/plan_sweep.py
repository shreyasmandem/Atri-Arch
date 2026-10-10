"""Generate plans across a spread of realistic briefs and score each for the
defects a client spots in the first ten seconds.

Run:  python -m scripts.plan_sweep [--n 30] [--svg]   (from backend/)

Writes var/sweep/report.json and, with --svg, one floor-plan SVG per level so
the worst plans can be looked at, not just counted.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from aip.api.schemas import SimpleBriefRequest
from aip.domain.geometry import Direction
from aip.domain.plan import FloorPlan, RoomType
from aip.engines.architecture.layout import GeneratorConfig, InfeasibleBriefError, LayoutGenerator

OUT = Path(__file__).resolve().parent.parent / "var" / "sweep"

PUBLIC = {RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN}
WET = {RoomType.BATHROOM, RoomType.TOILET} if hasattr(RoomType, "TOILET") else {RoomType.BATHROOM}


def briefs(n: int, seed: int = 11) -> list[SimpleBriefRequest]:
    rng = random.Random(seed)
    out = []
    shapes = [(9, 12), (9, 15), (10, 14), (12, 18), (12, 20), (15, 20), (15, 25), (18, 24), (20, 30), (24, 18), (30, 15)]
    for i in range(n):
        w, d = rng.choice(shapes)
        levels = rng.choice([1, 1, 2, 2, 2, 3])
        beds = rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5])
        out.append(SimpleBriefRequest(
            project_name=f"sweep {i}",
            plot_width=w, plot_depth=d, levels=levels, bedrooms=beds,
            bathrooms=max(1, min(beds + rng.choice([-1, 0, 0, 1]), 6)),
            road_direction=rng.choice([Direction(v) for v in ("N", "NE", "E", "SE", "S", "SW", "W", "NW")]),
            vastu=rng.choice(["ignore", "advisory", "balanced", "strict"]),
            amenities=rng.sample(["pooja", "dining", "study", "utility", "balcony", "parking"], rng.randint(1, 4)),
            occupant_elders=rng.choice([0, 0, 1, 2]),
            setback_front=rng.choice([1.5, 2.0, 3.0]), setback_rear=1.5,
            setback_left=rng.choice([1.0, 1.2]), setback_right=rng.choice([1.0, 1.2]),
        ))
    return out


def large_briefs() -> list[SimpleBriefRequest]:
    """Generous plots: the house must grow to the site it is given, not sit in a corner of it."""
    common = {"road_direction": Direction("N"), "vastu": "balanced", "occupant_elders": 1,
              "amenities": ["pooja", "dining", "study", "utility", "balcony", "parking"],
              "setback_front": 3.0, "setback_rear": 1.5, "setback_left": 1.2, "setback_right": 1.2}
    return [
        SimpleBriefRequest(project_name="large 40x60", plot_width=40, plot_depth=60, levels=4,
                           bedrooms=6, bathrooms=6, **common),
        SimpleBriefRequest(project_name="large 30x40", plot_width=30, plot_depth=40, levels=2,
                           bedrooms=4, bathrooms=4, **common),
    ]


def footprint_report(plan: FloorPlan, gen: LayoutGenerator) -> dict[str, float]:
    """How much of the plot's allowance the floor plate uses, and the largest room against its cap."""
    from aip.engines.architecture.feasibility import luxury_max

    site = plan.site
    env = gen._envelope  # noqa: SLF001
    allowed = min(gen._footprint_cap() or env.area, site.max_footprint)  # noqa: SLF001
    over = [(r.display_name(), r.area, luxury_max(r.type)) for r in plan.all_rooms
            if luxury_max(r.type) is not None and r.area > luxury_max(r.type) + 0.5]
    return {"footprint_m2": round(env.area, 1), "allowed_m2": round(allowed, 1),
            "fill": round(env.area / allowed, 3), "rooms_over_cap": len(over)}


def defects(plan: FloorPlan, gen: LayoutGenerator) -> dict[str, list[str]]:
    d: dict[str, list[str]] = {}

    def add(kind: str, msg: str) -> None:
        d.setdefault(kind, []).append(msg)

    for msg in gen._sanity(plan):  # noqa: SLF001 - the generator's own guardrail
        add("guardrail", msg)

    for level in plan.levels:
        rooms = level.rooms
        by_id = {r.id: r for r in rooms}
        doors = [o for w in level.walls for o in w.openings if o.kind.is_door]
        windows = {r.id: 0 for r in rooms}
        door_count = Counter()
        for w in level.walls:
            for o in w.openings:
                if o.kind.is_door and o.connects:
                    for rid in o.connects:
                        door_count[rid] += 1
                elif not o.kind.is_door:
                    for rid in w.rooms:
                        if rid in windows:
                            windows[rid] += 1
        tag = f"L{level.index}"
        for r in rooms:
            name = r.display_name()
            if r.type.is_habitable and windows.get(r.id, 0) == 0:
                add("no_window", f"{tag} {name}")
            if not r.type.is_outdoor and door_count[r.id] == 0 and len(rooms) > 1:
                add("no_door", f"{tag} {name}")
            if door_count[r.id] > 3 and not r.type.is_circulation:
                add("cut_up", f"{tag} {name} has {door_count[r.id]} doors")
            if r.type in (RoomType.LIVING, RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.DINING) and r.bbox.aspect_ratio > 2.2:
                add("long_room", f"{tag} {name} {r.bbox.aspect_ratio:.1f}:1")
        # A bathroom whose only door opens into the kitchen, living or dining room.
        for o in doors:
            if not o.connects:
                continue
            a, b = (by_id.get(x) for x in o.connects)
            if a and b:
                pair = {a.type, b.type}
                if pair & WET and pair & PUBLIC:
                    add("wc_off_public", f"{tag} {a.display_name()}-{b.display_name()}")
        # Holes and slivers inside the building: space nobody can use.
        polys = [Polygon([(p.x, p.y) for p in r.polygon]).buffer(0) for r in rooms if len(r.polygon) >= 3]
        if polys:
            union = unary_union(polys)
            hull = union.envelope
            hole_area = hull.area - union.area
            if hole_area > 0.08 * hull.area:
                add("dead_space", f"{tag} {hole_area:.1f} m2 ({hole_area / hull.area:.0%}) of the footprint unused")
        # Passages only: a foyer is a room and a staircase is unavoidable.
        circ = sum(r.area for r in rooms if r.type in (RoomType.CORRIDOR, RoomType.LOBBY))
        total = sum(r.area for r in rooms) or 1
        if circ / total > 0.12:
            add("too_much_corridor", f"{tag} {circ / total:.0%}")
    # Stairs stacked on top of each other.
    stairs = [[r for r in lv.rooms if r.type == RoomType.STAIRCASE] for lv in plan.levels]
    if len(plan.levels) > 1 and all(len(s) == 1 for s in stairs):
        c0 = stairs[0][0].centre
        for s in stairs[1:]:
            if s[0].centre.distance_to(c0) > 0.6:
                add("stairs_misaligned", f"offset {s[0].centre.distance_to(c0):.1f} m")
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--svg", action="store_true")
    ap.add_argument("--large", action="store_true", help="run the generous-plot cases instead")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    tally: Counter[str] = Counter()
    infeasible = 0
    slowest = 0.0
    for i, req in enumerate(large_briefs() if args.large else briefs(args.n)):
        brief = req.to_brief()
        t0 = time.perf_counter()
        try:
            gen = LayoutGenerator(brief, GeneratorConfig(seed=(900 if args.large else 100) + i))
            plan = gen.generate(1)[0]
        except InfeasibleBriefError as exc:
            # The typed refusal is the right answer for a programme that cannot
            # be drawn on the plot, so it is counted apart from the defects.
            infeasible += 1
            secs = time.perf_counter() - t0
            rows.append({"i": i, "plot": [req.plot_width, req.plot_depth], "levels": req.levels,
                         "beds": req.bedrooms, "infeasible": str(exc)})
            print(f"{i:2d} {req.plot_width:>4.0f}x{req.plot_depth:<4.0f} L{req.levels} {req.bedrooms}bhk road {req.road_direction.value:<2} {secs:5.1f}s  INFEASIBLE: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            rows.append({"i": i, "error": f"{type(exc).__name__}: {exc}"})
            tally["crash"] += 1
            print(f"{i:2d} CRASH {type(exc).__name__}: {exc}")
            continue
        secs = time.perf_counter() - t0
        slowest = max(slowest, secs)
        d = defects(plan, gen)
        for k in d:
            tally[k] += 1
        advised = " +" + str(len(plan.metadata.get("advisories", []))) + "adv" if plan.metadata.get("advisories") else ""
        rows.append({"i": i, "plot": [req.plot_width, req.plot_depth], "levels": req.levels,
                     "drawn_levels": len(plan.levels),
                     "beds": req.bedrooms, "road": req.road_direction.value, "secs": round(secs, 1),
                     "advisories": plan.metadata.get("advisories", []), "defects": d})
        flag = " ".join(f"{k}:{len(v)}" for k, v in d.items()) or "clean"
        print(f"{i:2d} {req.plot_width:>4.0f}x{req.plot_depth:<4.0f} L{req.levels}->{len(plan.levels)} {req.bedrooms}bhk road {req.road_direction.value:<2} {secs:5.1f}s  {flag}{advised}")
        if args.large:
            print("   footprint", footprint_report(plan, gen))
            for adv in plan.metadata.get("advisories", []):
                print("   -", adv)
        if args.svg:
            from aip.engines.architecture.drawings import floor_plan_svg
            for lv in plan.levels:
                (OUT / f"p{i:02d}_L{lv.index}.svg").write_text(floor_plan_svg(plan, lv.index), encoding="utf-8")
    clean = sum(1 for r in rows if "defects" in r and not r["defects"])
    print(f"\nclean {clean}/{len(rows)}   infeasible (typed refusal) {infeasible}   "
          f"slowest {slowest:.1f}s   defect frequency: {dict(tally.most_common())}")
    (OUT / "report.json").write_text(json.dumps({"tally": tally, "infeasible": infeasible, "rows": rows}, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
