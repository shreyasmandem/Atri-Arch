"""Audit generated plans across every dimension an architect would check.

Each check returns findings; a plan is clean only when every dimension is.
Run:  python -m scripts.plan_audit [--n 30] [--json out.json]   (from backend/)
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from aip.domain.plan import FloorPlan, Level, RoomType
from aip.engines.architecture.layout import GeneratorConfig, InfeasibleBriefError, LayoutGenerator
from scripts.plan_sweep import briefs

T = RoomType
BEDS = {T.MASTER_BEDROOM, T.BEDROOM, getattr(T, "GUEST_BEDROOM", T.BEDROOM), getattr(T, "CHILDREN_BEDROOM", T.BEDROOM)}
WET = {T.BATHROOM, getattr(T, "TOILET", T.BATHROOM), getattr(T, "POWDER", T.BATHROOM)}
PUBLIC = {T.LIVING, T.DINING, T.KITCHEN, getattr(T, "FAMILY", T.LIVING), getattr(T, "DRAWING", T.LIVING)}
PASSAGE = {T.CORRIDOR, T.LOBBY}

#: The smallest rectangle the room's essential furniture and its clearances need.
FURNISH = {
    T.MASTER_BEDROOM: (3.3, 3.6), T.BEDROOM: (3.0, 3.0), T.LIVING: (3.6, 4.2),
    T.DINING: (2.7, 3.0), T.KITCHEN: (2.1, 2.7), T.BATHROOM: (1.5, 2.1),
    T.STAIRCASE: (2.3, 3.8), T.UTILITY: (1.2, 1.8), T.PUJA: (1.2, 1.2), T.FOYER: (1.5, 1.8),
}


def poly(r) -> Polygon:
    return Polygon([(p.x, p.y) for p in r.polygon]).buffer(0)


def shared(a, b) -> float:
    inter = poly(a).buffer(0.08).intersection(poly(b).buffer(0.08))
    return 0.0 if inter.is_empty else max(inter.bounds[2] - inter.bounds[0], inter.bounds[3] - inter.bounds[1])


def door_graph(level: Level) -> dict[str, set[str]]:
    g: dict[str, set[str]] = defaultdict(set)
    for w in level.walls:
        for o in w.openings:
            if o.kind.is_door and o.connects and all(o.connects):
                a, b = o.connects
                g[a].add(b)
                g[b].add(a)
    return g


def audit(plan: FloorPlan, brief) -> dict[str, list[str]]:
    f: dict[str, list[str]] = defaultdict(list)
    site = Polygon([(p.x, p.y) for p in plan.site.boundary]) if plan.site.boundary else None

    for lv in plan.levels:
        tag = f"L{lv.index}"
        rooms = lv.rooms
        by = {r.id: r for r in rooms}
        g = door_graph(lv)
        windows = Counter()
        for w in lv.walls:
            for o in w.openings:
                if not o.kind.is_door:
                    for rid in w.rooms:
                        windows[rid] += 1
        for r in rooms:
            n = r.display_name()
            bw, bh = sorted((r.bbox.width, r.bbox.height))
            # 1 Circulation shape: a passage is a strip, not a room.
            if r.type in PASSAGE and bw > 1.9:
                f["blob_passage"].append(f"{tag} {n} {bw:.1f}x{bh:.1f} m ({r.area:.0f} m2) - a room-sized passage")
            # 2 Furnishability.
            need = FURNISH.get(r.type)
            if need and (bw < need[0] - 0.05 or bh < need[1] - 0.05):
                f["unfurnishable"].append(f"{tag} {n} {bw:.1f}x{bh:.1f} m < {need[0]}x{need[1]}")
            # 3 Daylight.
            if r.type.is_habitable and windows[r.id] == 0:
                f["no_daylight"].append(f"{tag} {n}")
            # 4 Bedroom privacy: a bedroom should open off a passage or lobby, not the living/dining/kitchen.
            if r.type in BEDS:
                via = {by[x].type for x in g.get(r.id, ()) if x in by}
                if via and via <= PUBLIC:
                    f["bedroom_off_public"].append(f"{tag} {n} opens only into {', '.join(sorted(t.label for t in via))}")
            # 5 Toilets opening onto kitchen or dining.
            if r.type in WET:
                for x in g.get(r.id, ()):
                    if x in by and by[x].type in {T.KITCHEN, T.DINING}:
                        f["wc_into_kitchen_dining"].append(f"{tag} {n} -> {by[x].display_name()}")
            # 6 Doors: too many breaks a room.
            nd = len(g.get(r.id, ()))
            if r.type in BEDS and nd > 2:
                f["too_many_doors"].append(f"{tag} {n} {nd} doors")
            # 7 Proportions.
            ar = bh / max(bw, 1e-6)
            cap = {T.LIVING: 2.2, T.DINING: 2.0, T.MASTER_BEDROOM: 1.7, T.BEDROOM: 1.7, T.KITCHEN: 2.6}.get(r.type)
            if cap and ar > cap:
                f["bad_proportion"].append(f"{tag} {n} {ar:.1f}:1")
        # 7b Balance: no room swallows the plan or outgrows what the programme asked for.
        plate = sum(x.area for x in rooms) or 1.0
        for r in rooms:
            asked = float(r.metadata.get("brief_area") or r.metadata.get("target_area") or 0.0)
            if r.type.is_outdoor or r.type == T.STAIRCASE:
                continue
            if (asked > 0 and r.area > 1.6 * asked) or r.area > 0.28 * plate:
                f["area_balance"].append(f"{tag} {r.display_name()} {r.area:.0f} m2 (asked {asked:.0f}, plate {plate:.0f})")
        # 7c A stair is a dog-leg of about 2.4 x 4.5 m, not a hall.
        for r in rooms:
            if r.type == T.STAIRCASE and r.area > 12.0:
                f["stair_oversize"].append(f"{tag} Staircase {r.area:.1f} m2")
        # 7d The utility has an outside wall; a passage reaches at least three rooms.
        for r in rooms:
            if r.type == T.UTILITY and not any(w.kind.value == "exterior" and r.id in w.rooms for w in lv.walls):
                f["utility_interior"].append(f"{tag} Utility has no outside wall")
            if r.type == T.CORRIDOR and len(g.get(r.id, ())) < 3:
                f["stub_corridor"].append(f"{tag} Corridor reaches {len(g.get(r.id, ()))} rooms")
        # 7e Dining smaller than living; the opening between them wide; kitchen onto dining.
        liv = [x for x in rooms if x.type == T.LIVING]
        din = [x for x in rooms if x.type == T.DINING]
        kit = [x for x in rooms if x.type == T.KITCHEN]
        if liv and din and din[0].area > 0.85 * liv[0].area:
            f["dining_oversize"].append(f"{tag} Dining {din[0].area:.0f} m2 vs Living {liv[0].area:.0f} m2")
        kinds_between: dict[frozenset, set] = defaultdict(set)
        for w in lv.walls:
            for o in w.openings:
                if o.kind.is_door and o.connects and all(o.connects) and all(c in by for c in o.connects):
                    kinds_between[frozenset((by[o.connects[0]].type, by[o.connects[1]].type))].add(o.kind.value)
        if liv and din and "door" in kinds_between.get(frozenset((T.LIVING, T.DINING)), set())                 and "arch" not in kinds_between.get(frozenset((T.LIVING, T.DINING)), set()):
            f["living_dining_door"].append(f"{tag} living opens to dining through a door")
        if kit and din and frozenset((T.KITCHEN, T.DINING)) not in kinds_between:
            f["kitchen_not_on_dining"].append(f"{tag}")
        # 7f The master is the largest bedroom and every bedroom reaches a bathroom.
        mas = [x for x in rooms if x.type == T.MASTER_BEDROOM]
        oth = [x for x in rooms if x.type in (T.BEDROOM, getattr(T, "GUEST_BEDROOM", T.BEDROOM), getattr(T, "CHILDREN_BEDROOM", T.BEDROOM))]
        if mas and oth and mas[0].area < 1.05 * max(x.area for x in oth):
            f["master_not_largest"].append(f"{tag} master {mas[0].area:.0f} m2 vs {max(x.area for x in oth):.0f} m2")
        for x in mas + oth:
            baths = [y for y in g.get(x.id, ()) if y in by and by[y].type == T.BATHROOM]
            shared_bath = any(by[y].type == T.BATHROOM and any(by[z].type in PASSAGE for z in g.get(y, ()) if z in by) for y in by)
            if not baths and not shared_bath:
                f["bedroom_no_bath"].append(f"{tag} {x.display_name()}")
        # 7g A terrace or balcony is open on the perimeter, not a walled room inside the plan.
        for x in rooms:
            if x.type in (T.TERRACE, T.BALCONY):
                rail = any(w.kind.value == "parapet" and x.id in w.rooms for w in lv.walls)
                if not rail:
                    f["enclosed_terrace"].append(f"{tag} {x.display_name()} has no open edge")
        # 7h One wall per stretch of line: no two walls lie on top of each other.
        segs = [((round(w.start.x, 2), round(w.end.x, 2)), (round(w.start.y, 2), round(w.end.y, 2))) for w in lv.walls]
        dup = 0
        for i, ((ax, ay)) in enumerate(segs):
            for bx_, by_ in segs[i + 1:]:
                if ax[0] == ax[1] == bx_[0] == bx_[1]:       # both vertical on one line
                    lo, hi = max(min(ay), min(by_)), min(max(ay), max(by_))
                elif ay[0] == ay[1] == by_[0] == by_[1]:     # both horizontal on one line
                    lo, hi = max(min(ax), min(bx_)), min(max(ax), max(bx_))
                else:
                    continue
                if hi - lo > 0.05:
                    dup += 1
        if dup:
            f["duplicate_walls"].append(f"{tag} {dup} overlapping wall pairs")
        # 8 Adjacency the household expects.
        def kinds(t):
            return [r for r in rooms if r.type == t]
        for k in kinds(T.KITCHEN):
            if not any(shared(k, d) > 0.9 for d in kinds(T.DINING)) and kinds(T.DINING):
                f["kitchen_far_from_dining"].append(f"{tag}")
        for lvr in kinds(T.LIVING):
            if kinds(T.DINING) and not any(shared(lvr, d) > 0.9 for d in kinds(T.DINING)):
                f["living_far_from_dining"].append(f"{tag}")
        # 9 Puja sharing a wall with a toilet; toilet over kitchen handled below.
        for p in kinds(T.PUJA):
            for wc in [r for r in rooms if r.type in WET]:
                if shared(p, wc) > 0.5:
                    f["puja_beside_toilet"].append(f"{tag}")
        # 10 Passage share.
        total = sum(r.area for r in rooms) or 1
        share = sum(r.area for r in rooms if r.type in PASSAGE) / total
        if share > 0.12:
            f["passage_share"].append(f"{tag} {share:.0%}")
        # 11 Dead space.
        u = unary_union([poly(r) for r in rooms])
        holes = u.envelope.area - u.area
        if holes > 0.06 * u.envelope.area:
            f["dead_space"].append(f"{tag} {holes:.0f} m2")

    # 12 Entry: the ground floor's entrance room faces the road and leads to living.
    if plan.levels:
        g0 = door_graph(plan.levels[0])
        by0 = {r.id: r for r in plan.levels[0].rooms}
        foyer = next((r for r in plan.levels[0].rooms if r.type == T.FOYER), None)
        if foyer and not any(by0[x].type == T.LIVING for x in g0.get(foyer.id, ()) if x in by0):
            f["foyer_not_to_living"].append("L0")

    # 13 Vertical: stairs stack, wet areas stack, walls bear on walls.
    for lo, hi in zip(plan.levels, plan.levels[1:]):
        s_lo = [r for r in lo.rooms if r.type == T.STAIRCASE]
        s_hi = [r for r in hi.rooms if r.type == T.STAIRCASE]
        if s_lo and s_hi and poly(s_lo[0]).symmetric_difference(poly(s_hi[0])).area > 0.5:
            f["stairs_not_stacked"].append(f"L{lo.index}->L{hi.index}")
        wet_lo = unary_union([poly(r) for r in lo.rooms if r.type in WET]) if any(r.type in WET for r in lo.rooms) else None
        for r in hi.rooms:
            if r.type in WET and wet_lo is not None and poly(r).intersection(wet_lo).area < 0.3 * r.area:
                below = [b.display_name() for b in lo.rooms if poly(b).intersection(poly(r)).area > 0.3 * r.area]
                if any(n in ("Kitchen", "Puja", "Dining") for n in below):
                    f["toilet_over_kitchen_puja"].append(f"L{hi.index} {r.display_name()} over {', '.join(below)}")
        lines_lo = unary_union([LineString([(w.start.x, w.start.y), (w.end.x, w.end.y)]).buffer(0.2) for w in lo.walls])
        hi_len = sum(w.length for w in hi.walls) or 1
        borne = sum(LineString([(w.start.x, w.start.y), (w.end.x, w.end.y)]).intersection(lines_lo).length for w in hi.walls)
        if borne / hi_len < 0.6:
            f["walls_not_bearing"].append(f"L{hi.index}: {borne / hi_len:.0%} of walls over walls")

    # 14 Plot use: the house uses the site it was given.
    if site is not None and plan.levels:
        foot = unary_union([poly(r) for r in plan.levels[0].rooms]).area
        cover_target = min(site.area * float(getattr(plan.site, "max_ground_coverage", 0.6) or 0.6),
                           site.buffer(-1.5).area)
        if foot < 0.85 * cover_target and cover_target > 100 and foot >= 0.6 * cover_target:
            f["plate_fill"].append(f"footprint {foot:.0f} m2 of {cover_target:.0f} m2 allowed ({foot / cover_target:.0%})")
        if foot < 0.6 * cover_target and cover_target > 120:
            f["underuses_plot"].append(f"footprint {foot:.0f} m2 of {cover_target:.0f} m2 allowed ({foot / cover_target:.0%})")
    return f


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    tally: Counter[str] = Counter()
    examples: dict[str, str] = {}
    clean = 0
    infeasible = 0
    reqs = briefs(args.n)
    from aip.api.schemas import SimpleBriefRequest
    reqs += [SimpleBriefRequest(plot_width=40, plot_depth=60, levels=4, bedrooms=6, bathrooms=6, road_direction="W"),
             SimpleBriefRequest(plot_width=30, plot_depth=40, levels=2, bedrooms=4, bathrooms=4, road_direction="N")]
    for i, req in enumerate(reqs):
        brief = req.to_brief()
        try:
            plan = LayoutGenerator(brief, GeneratorConfig(seed=100 + i)).generate(1)[0]
        except InfeasibleBriefError as exc:
            # A typed refusal is the right answer for a programme the plot cannot
            # hold; it is counted apart from the defects.
            infeasible += 1
            print(f"{i:2d} {req.plot_width:>3.0f}x{req.plot_depth:<3.0f} L{req.levels} {req.bedrooms}bhk  INFEASIBLE: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            tally["error:" + type(exc).__name__] += 1
            print(f"{i:2d} {type(exc).__name__}: {str(exc)[:90]}")
            continue
        f = audit(plan, brief)
        for k, v in f.items():
            tally[k] += 1
            examples.setdefault(k, v[0])
        clean += not f
        print(f"{i:2d} {req.plot_width:>3.0f}x{req.plot_depth:<3.0f} L{req.levels} {req.bedrooms}bhk  " + (" ".join(f"{k}:{len(v)}" for k, v in f.items()) or "clean"))
    print(f"\nclean {clean}/{len(reqs)}")
    for k, n in tally.most_common():
        print(f"{n:3d}  {k:28s} e.g. {examples.get(k, '')}")
    if args.json:
        json.dump({"tally": tally, "examples": examples}, open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
