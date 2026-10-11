"""Measured reviews for the three judgement axes, when no model can answer.

Coherence, brief fidelity and livability are normally a model's judgement. The
free models queue and rate-limit, and an offline stub that scores every
scheme 0.25 "unavailable" says nothing true about the plan - it only drags
good schemes down. So when the model is not there, the same three questions
are answered from the geometry: what was asked for and is it drawn, can the
household live in it, does the parti hold together. Every number here is
something the plan can be checked against.
"""

from __future__ import annotations

import math

from aip.domain.plan import FloorPlan, Room, RoomType

T = RoomType
BEDS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM}
WET = {T.BATHROOM, T.TOILET, T.POWDER}
PASSAGE = {T.CORRIDOR, T.LOBBY}


def _touch(a: Room, b: Room, need: float = 0.9) -> bool:
    A, B = a.bbox, b.bbox
    tol = 0.05
    if abs(A.max_x - B.min_x) < tol or abs(B.max_x - A.min_x) < tol:
        return min(A.max_y, B.max_y) - max(A.min_y, B.min_y) >= need
    if abs(A.max_y - B.min_y) < tol or abs(B.max_y - A.min_y) < tol:
        return min(A.max_x, B.max_x) - max(A.min_x, B.min_x) >= need
    return False


def _doors(level) -> dict[str, set[str]]:
    g: dict[str, set[str]] = {}
    for w in level.walls:
        for o in w.openings:
            if o.kind.is_door and o.connects and all(o.connects):
                a, b = o.connects
                g.setdefault(a, set()).add(b)
                g.setdefault(b, set()).add(a)
    return g


def _frac(hits: int, total: int, default: float = 1.0) -> float:
    return hits / total if total else default


def brief_fidelity(plan: FloorPlan, brief) -> tuple[float, str, list[str]]:
    rooms = [r for lv in plan.levels for r in lv.rooms]
    have = {r.type for r in rooms}
    reqs = list(getattr(brief, "requirements", []) or [])
    concerns: list[str] = []
    # Everything asked for is drawn.
    wanted = {r.type for r in reqs if r.type not in PASSAGE and r.type is not T.STAIRCASE}
    if T.BALCONY in wanted and T.VERANDAH in have:
        have = have | {T.BALCONY}
    missing = sorted(t.label for t in wanted - have)
    presence = 1.0 - len(missing) / max(1, len(wanted))
    if missing:
        concerns.append("Not drawn: " + ", ".join(missing) + ".")
    # Counts: bedrooms, bathrooms, floors.
    asked_beds = sum(r.count for r in reqs if r.type in BEDS)
    asked_baths = sum(r.count for r in reqs if r.type in {T.BATHROOM, T.TOILET})
    beds = sum(1 for r in rooms if r.type in BEDS)
    baths = sum(1 for r in rooms if r.type in {T.BATHROOM, T.TOILET})
    counts = []
    if asked_beds:
        counts.append(min(beds, asked_beds) / asked_beds)
        if beds < asked_beds:
            concerns.append(f"{beds} of {asked_beds} bedrooms drawn.")
    if asked_baths:
        counts.append(min(baths, asked_baths) / asked_baths)
    levels_ok = 1.0 if len(plan.levels) == getattr(brief, "levels", len(plan.levels)) else 0.7
    counts.append(levels_ok)
    count_score = sum(counts) / len(counts)
    # Sizes against what was asked.
    sized = [r for r in rooms if float(r.metadata.get("brief_area") or 0) > 0
             and not r.type.is_outdoor and r.type not in PASSAGE | {T.STAIRCASE}]
    ok = 0
    for r in sized:
        k = r.area / float(r.metadata["brief_area"])
        if 0.8 <= k <= 1.5:
            ok += 1
        elif k < 0.8:
            concerns.append(f"{r.display_name()} is {r.area:.0f} m2 against {float(r.metadata['brief_area']):.0f} asked.")
    sizes = _frac(ok, len(sized))
    # Directions the client named.
    cx = sum(r.centre.x for r in rooms) / max(1, len(rooms))
    cy = sum(r.centre.y for r in rooms) / max(1, len(rooms))
    north = float(plan.site.north_angle or 0.0)
    dir_hits = dir_total = 0
    for req in reqs:
        d = getattr(req, "preferred_direction", None)
        if d is None:
            continue
        cands = [r for r in rooms if r.type is req.type]
        if not cands:
            continue
        dir_total += 1
        best = min(abs(((math.degrees(math.atan2(r.centre.x - cx, r.centre.y - cy)) - north) % 360 - d.bearing + 180) % 360 - 180)
                   for r in cands)
        if best <= 67.5:
            dir_hits += 1
        else:
            concerns.append(f"The {req.type.label.lower()} is not on the {d.value} side asked for.")
    directions = _frac(dir_hits, dir_total)
    # "Next to" and "opens off" requests.
    adj_hits = adj_total = 0
    for req in reqs:
        note = (req.notes or "").lower()
        if "requested" not in note:
            continue
        targets = list(req.must_be_adjacent_to or [])
        if "opens off the" in note:
            name = note.split("opens off the", 1)[1].split(".")[0].strip()
            targets += [t for t in RoomType if t.value.replace("_", " ") == name]
        for t in targets:
            adj_total += 1
            if any(_touch(a, b) for lv in plan.levels for a in lv.rooms if a.type is req.type
                   for b in lv.rooms if b.type is t):
                adj_hits += 1
            else:
                concerns.append(f"The {req.type.label.lower()} is not beside the {t.label.lower()}.")
    adjacency = _frac(adj_hits, adj_total)
    score = 0.35 * presence + 0.2 * count_score + 0.25 * sizes + 0.1 * directions + 0.1 * adjacency
    why = (f"Measured against the brief: {presence:.0%} of the rooms asked for are drawn, "
           f"{sizes:.0%} of rooms within their asked size, counts {count_score:.0%}, "
           f"named sides {directions:.0%}, requested neighbours {adjacency:.0%}.")
    return score, why, concerns[:4]


def livability(plan: FloorPlan, brief) -> tuple[float, str, list[str]]:
    from aip.engines.architecture.programme import walkability

    concerns: list[str] = []
    lit = lit_total = legal = routes = baths_ok = bed_total = 0
    kd = kd_total = ld = ld_total = 0
    for lv in plan.levels:
        by = {r.id: r for r in lv.rooms}
        g = _doors(lv)
        windows = {rid for w in lv.walls for o in w.openings if not o.kind.is_door for rid in w.rooms}
        for r in lv.rooms:
            if r.type.is_habitable:
                lit_total += 1
                lit += r.id in windows
        for route in walkability(plan, lv.index):
            routes += 1
            legal += route.legal
        shared = any(by[b].type in WET and any(by.get(z) and by[z].type in PASSAGE for z in g.get(b, ()))
                     for b in by)
        for r in lv.rooms:
            if r.type in BEDS:
                bed_total += 1
                if shared or any(by.get(x) and by[x].type in WET for x in g.get(r.id, ())):
                    baths_ok += 1
                else:
                    concerns.append(f"{r.display_name()} has no bathroom within reach.")
        kit = [r for r in lv.rooms if r.type is T.KITCHEN]
        din = [r for r in lv.rooms if r.type is T.DINING]
        liv = [r for r in lv.rooms if r.type is T.LIVING]
        if kit and din:
            kd_total += 1
            kd += any(_touch(k, d) for k in kit for d in din)
        if liv and din:
            ld_total += 1
            ld += any(_touch(a, d, 1.5) for a in liv for d in din)
    if lit < lit_total:
        concerns.append(f"{lit_total - lit} habitable room(s) without a window.")
    if kd < kd_total:
        concerns.append("The kitchen does not meet the dining room.")
    score = (0.25 * _frac(lit, lit_total) + 0.3 * _frac(legal, routes) + 0.2 * _frac(baths_ok, bed_total)
             + 0.15 * _frac(kd, kd_total) + 0.1 * _frac(ld, ld_total))
    why = (f"Measured for daily life: {_frac(lit, lit_total):.0%} of living rooms have a window, "
           f"{_frac(legal, routes):.0%} of rooms are reached the right way, "
           f"{_frac(baths_ok, bed_total):.0%} of bedrooms reach a bathroom, kitchen to dining "
           f"{_frac(kd, kd_total):.0%}, living to dining {_frac(ld, ld_total):.0%}.")
    return score, why, concerns[:4]


def coherence(plan: FloorPlan, brief) -> tuple[float, str, list[str]]:
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    from aip.engines.architecture.layout import aspect_limit

    concerns: list[str] = []
    poly = lambda r: Polygon([(p.x, p.y) for p in r.polygon]).buffer(0)  # noqa: E731
    # Floors that stack: the stair, the wet rooms, the walls.
    stair_ok, wet_ok, bearing = 1.0, 1.0, 1.0
    pairs = list(zip(plan.levels, plan.levels[1:]))
    if pairs:
        s_scores, w_scores, b_scores = [], [], []
        for lo, hi in pairs:
            sl = [poly(r) for r in lo.rooms if r.type is T.STAIRCASE]
            sh = [poly(r) for r in hi.rooms if r.type is T.STAIRCASE]
            if sl and sh:
                s_scores.append(1.0 if sl[0].symmetric_difference(sh[0]).area < 0.5 else 0.0)
            wl = unary_union([poly(r) for r in lo.rooms if r.type in WET]) if any(r.type in WET for r in lo.rooms) else None
            bad = [r for r in hi.rooms if r.type in WET and any(
                poly(r).intersection(poly(b)).area > 0.3 * r.area for b in lo.rooms if b.type in {T.KITCHEN, T.DINING, T.PUJA})]
            w_scores.append(1.0 - len(bad) / max(1, sum(1 for r in hi.rooms if r.type in WET)))
            if bad:
                concerns.append(f"{len(bad)} bathroom(s) on level {hi.index} over the kitchen, dining or shrine.")
            lines = unary_union([LineString([(w.start.x, w.start.y), (w.end.x, w.end.y)]).buffer(0.2) for w in lo.walls])
            total = sum(w.length for w in hi.walls) or 1.0
            borne = sum(LineString([(w.start.x, w.start.y), (w.end.x, w.end.y)]).intersection(lines).length for w in hi.walls)
            b_scores.append(min(1.0, borne / total / 0.75))
            del wl
        stair_ok = sum(s_scores) / len(s_scores) if s_scores else 1.0
        wet_ok = sum(w_scores) / len(w_scores)
        bearing = sum(b_scores) / len(b_scores)
    # Circulation in the band a good plan keeps to, and rooms in proportion.
    shares, props = [], []
    for lv in plan.levels:
        tot = sum(r.area for r in lv.rooms if not r.type.is_outdoor) or 1.0
        circ = sum(r.area for r in lv.rooms if r.type in PASSAGE) / tot
        shares.append(1.0 if circ <= 0.12 else max(0.0, 1.0 - (circ - 0.12) * 5))
        for r in lv.rooms:
            cap = aspect_limit(r.type)
            if cap is not None:
                props.append(1.0 if r.bbox.aspect_ratio <= cap + 0.05 else max(0.0, 1.0 - (r.bbox.aspect_ratio - cap) / 2))
    circulation = sum(shares) / len(shares)
    proportion = sum(props) / len(props) if props else 1.0
    if circulation < 0.9:
        concerns.append("Passages take more of the floor than a compact plan needs.")
    score = 0.2 * stair_ok + 0.2 * wet_ok + 0.2 * bearing + 0.2 * circulation + 0.2 * proportion
    why = (f"Measured for the parti: stair stacking {stair_ok:.0%}, bathrooms clear of the rooms below "
           f"{wet_ok:.0%}, walls standing on walls {bearing:.0%}, compact circulation {circulation:.0%}, "
           f"rooms in proportion {proportion:.0%}.")
    return score, why, concerns[:4]


REVIEWS = {"coherence": coherence, "brief_fidelity": brief_fidelity, "livability": livability}
