"""The corridor planner: a plan that is valid by construction.

The other planners search for a parti and sometimes find none that holds on a
small or awkward plot. This one never searches for validity, it builds it:

* one **passage** runs the depth of the house, with the front door at its
  head; every room has a door on it, so nobody walks through a bedroom to
  reach another room and no wet room opens onto the dining table;
* rooms stand in two **columns** either side of the passage, each as wide as
  the column and as deep as its area wants, between the least a room of its
  kind may be (statutory area and width) and what it usefully is;
* a bedroom's **bath** sits behind it in the same column, opening from it;
* the **stair** is one rectangle at the back of one column, the same on
  every floor, so floors stack;
* the **car porch** is at the head of a column, beside the foyer, on the road.

Because the structure is fixed, what varies is only which column takes which
rooms, where the stair stands and how deep the house is - a handful of
variants, each valid, ranked by the same judge as every other plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from aip.domain.geometry import BoundingBox, Direction
from aip.domain.plan import Room, RoomType
from aip.engines.architecture.parti import _fit
from aip.engines.architecture.spine import SpinePlanner, _items

T = RoomType
BEDS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM}
BATHS = {T.BATHROOM, T.TOILET, T.POWDER}
PUBLIC_ORDER = [T.VERANDAH, T.DRAWING, T.LIVING, T.FAMILY, T.DINING, T.KITCHEN, T.PANTRY, T.UTILITY, T.LAUNDRY]
PRIVATE_ORDER = {T.PUJA: 0, T.STUDY: 1, T.HOME_OFFICE: 1, T.LIBRARY: 1, T.GYM: 1, T.HOME_THEATRE: 1, T.SERVANT: 2,
                 T.POWDER: 3, T.TOILET: 3, T.BATHROOM: 3, T.STORE: 3, T.GUEST_BEDROOM: 4, T.CHILDREN_BEDROOM: 5,
                 T.BEDROOM: 5, T.MASTER_BEDROOM: 6}

#: The narrowest a room is drawn (statutory width for habitable rooms is 2.4 m).
MINW = {T.MASTER_BEDROOM: 3.0, T.BEDROOM: 2.7, T.GUEST_BEDROOM: 2.7, T.CHILDREN_BEDROOM: 2.7, T.LIVING: 3.2,
        T.DRAWING: 3.0, T.FAMILY: 3.0, T.DINING: 2.5, T.KITCHEN: 2.1, T.STUDY: 2.4, T.HOME_OFFICE: 2.4,
        T.LIBRARY: 2.4, T.GYM: 2.7, T.HOME_THEATRE: 3.0, T.BATHROOM: 1.5, T.TOILET: 1.2, T.POWDER: 1.2,
        T.PUJA: 1.5, T.STORE: 1.5, T.UTILITY: 1.5, T.PANTRY: 1.4, T.LAUNDRY: 1.5, T.GARAGE: 2.5, T.SERVANT: 2.4,
        T.BALCONY: 1.2, T.TERRACE: 1.5, T.VERANDAH: 1.5, T.COURTYARD: 2.4}
#: The least depth a room is drawn at when its width is generous (a room is never under
#: the statutory 2.4 m across, and a living room not under 2.8).
MIND = {T.LIVING: 2.8, T.DRAWING: 2.8, T.FAMILY: 2.8, T.MASTER_BEDROOM: 2.9, T.DINING: 2.4, T.KITCHEN: 1.9}
#: The least area a room is drawn at (the code's own floor where there is one).
MINA = {T.MASTER_BEDROOM: 11.0, T.BEDROOM: 9.6, T.GUEST_BEDROOM: 9.6, T.CHILDREN_BEDROOM: 9.6, T.LIVING: 12.0,
        T.DRAWING: 10.0, T.FAMILY: 10.0, T.DINING: 7.5, T.KITCHEN: 6.0, T.STUDY: 7.6, T.HOME_OFFICE: 7.6,
        T.LIBRARY: 7.0, T.GYM: 8.0, T.HOME_THEATRE: 10.0, T.BATHROOM: 3.0, T.TOILET: 2.0, T.POWDER: 1.9,
        T.PUJA: 2.0, T.STORE: 2.0, T.UTILITY: 2.4, T.PANTRY: 2.4, T.LAUNDRY: 2.4, T.GARAGE: 12.5, T.SERVANT: 8.0,
        T.BALCONY: 3.0, T.TERRACE: 4.0, T.VERANDAH: 4.0, T.COURTYARD: 6.0}
#: What a room usefully is at most, as a multiple of the area asked.
GROW = 1.4
CORRIDOR_W = 1.2
FOYER_W = 1.5
FOYER_D = 1.9


@dataclass(slots=True)
class CVariant:
    public_left: bool       # the public column is the low-u one
    stair_back: bool        # the stair at the back of its column (else beside the front)
    deep: float             # 0 shallowest feasible house .. 1 deepest
    narrow: float = 1.0     # share of the buildable width used
    transverse: bool = False  # the passage runs along the road: two bands, front and back


def corridor_variants() -> list[CVariant]:
    straight = [CVariant(pl, True, d, 1.0) for pl in (True, False) for d in (0.0, 1.0)]
    across = [CVariant(False, True, d, 1.0, True) for d in (0.0, 0.6, 1.0)]
    return across + straight


@dataclass(slots=True)
class _Row:
    type: RoomType
    area: float
    req: object | None = None
    host: int | None = None         # index of the row this one serves (a bedroom's bath)
    name: str | None = None

    @property
    def minw(self) -> float:
        return MINW.get(self.type, 1.5)

    @property
    def mina(self) -> float:
        return MINA.get(self.type, 4.0)

    @property
    def mind(self) -> float:
        return MIND.get(self.type, self.minw)


class CorridorPlanner(SpinePlanner):
    """Valid-by-construction plans for any plot the programme fits."""

    cover = 0.0

    # ----------------------------------------------------------------- rows --

    def _rows(self, items: list, li: int) -> tuple[list[_Row], list[_Row], list[_Row]]:
        """(public rows, private rows, outdoor rows) of one floor, each in drawing order."""
        pub, priv, out = [], [], []
        by_type = {t: i for i, t in enumerate(PUBLIC_ORDER)}
        for it in items:
            if it.type.is_outdoor and it.type not in (T.COURTYARD,):
                out.append(_Row(it.type, it.area, it.req, name=getattr(it.req, "label", None)))
            elif it.type in by_type:
                pub.append(_Row(it.type, it.area, it.req, name=getattr(it.req, "label", None)))
            elif it.type is T.GARAGE:
                priv.insert(0, _Row(it.type, it.area, it.req, name=getattr(it.req, "label", None)))
            else:
                priv.append(_Row(it.type, it.area, it.req, name=getattr(it.req, "label", None)))
        pub.sort(key=lambda r: by_type[r.type])
        garage = [r for r in priv if r.type is T.GARAGE]
        rest = sorted([r for r in priv if r.type is not T.GARAGE], key=lambda r: PRIVATE_ORDER.get(r.type, 3))
        return pub, garage + rest, out

    @staticmethod
    def _with_baths(items: list) -> list[_Row]:
        """Bedrooms with their baths behind them; other rooms as they are."""
        rows: list[_Row] = []
        for it in items:
            rows.append(_Row(it.type, it.area, it.req, name=getattr(it.req, "label", None)))
            if it.bath is not None:
                rows.append(_Row(it.bath.type, it.bath.area, it.bath.req, host=len(rows) - 1))
        return rows

    # ----------------------------------------------------------------- plan --

    def plan(self, levels: list[list], v: CVariant, _single: bool = False) -> list[list[Room]] | None:
        self.tr = v.transverse
        W, D = (self.D, self.W) if v.transverse else (self.W, self.D)
        levels = [list(l) for l in levels]
        for l in levels[1:]:
            for r in [r for r in l if r.type in {T.COURTYARD, T.VERANDAH, T.GARAGE}]:
                l.remove(r)
                levels[0].append(r)
        # Every floor with a bedroom has a bathroom on it.
        def count(l, ts): return sum(1 for r in l if r.type in ts)
        for l in levels:
            while count(l, BEDS) > count(l, BATHS):
                donor = next((d for d in levels if d is not l and count(d, BATHS) > max(count(d, BEDS), 1)), None)
                if donor is None:
                    break
                b = next(r for r in donor if r.type in BATHS)
                donor.remove(b)
                l.append(b)
        floors = [_items(l) for l in levels]
        multi = len(levels) > 1 and self.stair_on
        cw = FOYER_W if (W >= 6.8 and not v.transverse) else CORRIDOR_W
        Wh = min(W, 12.0) * v.narrow
        col_total = Wh - cw
        # Under 4.8 m for two columns: one column, the rooms in a single row on the passage.
        single = _single or col_total < 2 * 2.4
        if col_total < 2.4:
            self.why = 1
            return None

        # Which rows stand in which column, floor by floor.
        plan_cols: list[tuple[list[_Row], list[_Row], list[_Row]]] = []
        def merged(cols):
            if not single:
                return cols
            shift = len(cols[0])
            for r in cols[1]:
                if r.host is not None:
                    r.host += shift          # the second column's rows now follow the first's
            return (cols[0] + cols[1], [], cols[2])

        w_est = col_total if single else col_total / 2.0
        plan_cols.append(merged(self._columns(floors[0], 0, v, w_est, multi)))
        # The stair column is the lighter one on the ground floor, the same above.
        stair_col = (0 if single else self._stair_column(plan_cols[0])) if multi else None
        for li, items in enumerate(floors[1:], start=1):
            plan_cols.append(merged(self._columns(items, li, v, w_est, multi, stair_col)))
        st_len = 3.5 if multi else 0.0           # refined below once the column width is known

        # Column widths: wide enough for the widest least-width in each, shared by all floors.
        need_l = max((max((r.minw for r in cols[0]), default=2.4) for cols in plan_cols), default=2.4)
        need_r = 0.0 if single else max((max((r.minw for r in cols[1]), default=2.4) for cols in plan_cols), default=2.4)
        if stair_col is not None:
            need_l = max(need_l, 2.0) if stair_col == 0 else need_l
            need_r = max(need_r, 2.0) if stair_col == 1 else need_r
        if need_l + need_r > col_total + 1e-6:
            if not single:
                return self.plan(levels, v, _single=True)
            self.why = 2
            return None
        area_l = max((sum(r.area for r in cols[0]) for cols in plan_cols), default=1.0) or 1.0
        area_r = max((sum(r.area for r in cols[1]) for cols in plan_cols), default=1.0) or 1.0
        # The split of the width that keeps rooms nearest a sensible shape on every floor.
        def shape_cost(w_left: float) -> float:
            cost = 0.0
            for cols in plan_cols:
                for side, w in ((0, w_left), (1, col_total - w_left)):
                    for r in cols[side]:
                        d = max(r.area / w, r.minw)
                        asp = max(w, d) / max(min(w, d), 0.5)
                        limit = 3.0 if r.type in BATHS | {T.PUJA, T.STORE, T.UTILITY, T.PANTRY, T.GARAGE,
                                                          T.BALCONY, T.TERRACE} else 1.7
                        cost += r.area * max(0.0, asp - limit) ** 2
            return cost

        lo_w, hi_w = need_l, col_total - need_r
        if single:
            lo_w = hi_w = col_total
        steps = max(1, int((hi_w - lo_w) / 0.1))
        wl = min(range(steps + 1), key=lambda k: shape_cost(lo_w + k * 0.1))
        wl = min(lo_w + wl * 0.1, hi_w)
        wr = col_total - wl
        widths = (wl, wr)
        if multi:
            # The stair is two flights and a landing: about 7 m2, as long as the column is wide allows.
            st_len = max(2.0, min(4.0, math.ceil(7.2 / max(widths[stair_col], 2.0) * 4) / 4))

        # The depth: from the least every column needs to what the rooms ask for.
        def depths(li: int, Dh: float):
            res = []
            for side, rows in enumerate(plan_cols[li][:2]):
                w = widths[side]
                rows = list(rows)
                reserve = st_len if (stair_col == side and multi) else 0.0
                d_room = Dh - reserve
                if not rows:
                    res.append([])
                    continue
                nat = [max(r.area / w, 1.0) for r in rows]
                mins = [max(r.mina / w, r.mind) for r in rows]
                maxs = [max(r.area * GROW, r.mina) / w for r in rows]
                ds = _fit(d_room, nat, mins, maxs)
                if ds is None:
                    self.why = 3
                    return None
                res.append(ds)
            return res

        def need_depth(li: int) -> float:
            best = 0.0
            for side, rows in enumerate(plan_cols[li][:2]):
                w = widths[side]
                tot = sum(max(r.mina / w, r.mind) for r in rows)
                tot += st_len if (stair_col == side and multi) else 0.0
                best = max(best, tot)
            return best

        lo = max(need_depth(li) for li in range(len(floors)))
        self.dbg = {'lo': round(lo, 2), 'W': round(W, 2), 'D': round(D, 2), 'wl': round(wl, 2), 'wr': round(wr, 2), 'stair_col': stair_col,
                    'cols': [[[(r.type.value, round(r.area, 1)) for r in cols[0]], [(r.type.value, round(r.area, 1)) for r in cols[1]]] for cols in plan_cols]}
        nat = max(max((sum(max(r.area / widths[s], 1.0) for r in cols[s]) + (st_len if (stair_col == s and multi) else 0.0)
                       for s in (0, 1)), default=0.0) for cols in plan_cols)
        hi = min(D, (self.cover / Wh) if self.cover else D, max(lo, nat * 1.12))
        if lo > min(D, (self.cover / Wh) if self.cover else D) + 1e-6:
            self.why = 4
            return None
        Dh = lo + (max(hi, lo) - lo) * v.deep
        Dh = round(Dh * 4) / 4 + (0.0 if round(Dh * 4) / 4 >= lo else 0.25)
        if Dh > D + 1e-6:
            self.why = 5
            return None

        # Build.
        u_col_l = (0.0, wl)
        u_cor = (wl, wl + cw)
        u_col_r = (wl + cw, Wh)
        if not v.public_left:
            # Turn the house over: the high-u column becomes the first.
            pass
        out_levels: list[list[Room]] = []
        for li in range(len(floors)):
            ds = depths(li, Dh)
            if ds is None:
                self.why = 6
                return None
            rooms: list[Room] = []
            ids: dict[int, Room] = {}

            def add(t, a0, b0, a1, b1, req=None, name=None, key=None, _rooms=rooms, _li=li):
                if a1 - a0 < 0.9 or b1 - b0 < 0.9:
                    self.why = 7
                    return None
                area = round((a1 - a0) * (b1 - b0), 2)
                room = Room(name=name or getattr(req, "label", None) or t.label, type=t,
                            polygon=self._poly(a0, b0, a1, b1), level=_li, ceiling_height=3.0,
                            metadata={"_c": (a0, b0, a1, b1), "notes": getattr(req, "notes", "") or "",
                                      "target_area": getattr(req, "target_area", None) or area,
                                      "brief_area": getattr(req, "asked_area", None) or getattr(req, "target_area", None) or area,
                                      "planner": "corridor"})
                _rooms.append(room)
                if key is not None:
                    ids[key] = room
                return room

            # The passage; the foyer heads it on the ground floor.
            if li == 0 and cw >= FOYER_W - 1e-6 and not v.transverse:
                add(T.FOYER, u_cor[0], Dh - FOYER_D, u_cor[1], Dh, name="Foyer")
                add(T.CORRIDOR, u_cor[0], 0.0, u_cor[1], Dh - FOYER_D, name="Passage")
            else:
                add(T.CORRIDOR if li == 0 else T.LOBBY, u_cor[0], 0.0, u_cor[1], Dh,
                    name="Passage" if li == 0 else "Lobby")
            for side in (0, 1):
                rows = plan_cols[li][side]
                u0, u1 = (u_col_l if side == 0 else u_col_r)
                vcur = Dh
                for k, (row, d) in enumerate(zip(rows, ds[side])):
                    bu0, bu1 = u0, u1
                    extra = None
                    if row.host is not None and (u1 - u0) > 3.4 and d >= 1.7:
                        # A suite bath in a wide column: a bath on the outside wall and a
                        # dressing room beside it, not a bath as wide as the bedroom.
                        wb = min(max(row.area / d, 1.5), 2.6)
                        if (u1 - u0) - wb >= 1.2:
                            if side == 0:
                                bu0, bu1 = u0, u0 + wb
                                extra = (u0 + wb, u1)
                            else:
                                bu0, bu1 = u1 - wb, u1
                                extra = (u0, u1 - wb)
                    room = add(row.type, bu0, vcur - d, bu1, vcur, row.req, row.name, key=(side, k))
                    if extra is not None:
                        # Beside the passage, so it has its own door there; the bedroom's
                        # one reserved door is the bath's.
                        add(T.STORE, extra[0], vcur - d, extra[1], vcur, name="Dressing")
                    if room is not None and row.host is not None:
                        host = ids.get((side, row.host))
                        if host is not None:
                            room.metadata["suite_of"] = host.id
                    elif room is not None and row.type in BATHS:
                        room.metadata["common"] = True
                    vcur -= d
                if multi and stair_col == side:
                    add(T.STAIRCASE, u0, 0.0, u1, st_len, name="Staircase")
            out_levels.append(rooms)
        # Public side to the other hand: mirror the plan across the frontage.
        if not v.public_left:
            for rooms in out_levels:
                for room in rooms:
                    a0, b0, a1, b1 = room.metadata["_c"]
                    nc = (Wh - a1, b0, Wh - a0, b1)
                    room.polygon = self._poly(*nc)
                    room.metadata["_c"] = nc
        return out_levels

    # -------------------------------------------------------------- columns --

    def _columns(self, items: list, li: int, v: CVariant, w_est: float = 3.5, multi: bool = False,
                 stair_col: int | None = None):
        """Rows of one floor split between the two columns, balanced by area, each
        column in drawing order (front first)."""
        pub, priv, out = self._rows(items, li)
        # Suites: a bedroom takes its bath behind it.
        bedroom_items = [it for it in items if it.type in BEDS]
        suite_rows: list[list[_Row]] = []
        for it in sorted(bedroom_items, key=lambda i: -i.area):
            grp = [_Row(it.type, it.area, it.req, name=getattr(it.req, "label", None))]
            if it.bath is not None:
                grp.append(_Row(it.bath.type, it.bath.area, it.bath.req, host=0))
            suite_rows.append(grp)
        bed_types = {id(it) for it in bedroom_items}
        other_priv = [r for r in priv if r.type not in BEDS]
        left: list[list[_Row]] = []      # groups, each a chain of rows kept together
        right: list[list[_Row]] = []
        load = [0.0, 0.0]

        def put(group: list[_Row], side: int, front: bool = False):
            (left if side == 0 else right).insert(0 if front else len(left if side == 0 else right), group)
            load[side] += sum(r.area for r in group)

        # Public rooms in the first column: living at the front, dining then kitchen behind it.
        if pub:
            chain = [[r] for r in pub]
            for grp in chain:
                put(grp, 0)
        for r in out:
            if r.type in (T.BALCONY, T.TERRACE):
                continue
        # A car porch heads the other column, on the road.
        garage = [r for r in other_priv if r.type is T.GARAGE]
        for r in garage:
            put([r], 1, front=True)
        # Small private rooms go where the load is lighter, bedroom suites alternate by area.
        smalls = [r for r in other_priv if r.type is not T.GARAGE]
        groups = [[r] for r in smalls] + suite_rows
        groups.sort(key=lambda g: -sum(r.area for r in g))
        for grp in groups:
            side = 0 if load[0] <= load[1] else 1
            # Wet rooms and puja stay off the public column when there is one.
            if pub and grp[0].type in {T.PUJA, T.STORE, T.POWDER, T.TOILET} and load[1] <= load[0] * 1.6:
                side = 1
            put(grp, side)
        # Balconies and terraces take the front of the upper floor's lighter column.
        for r in out:
            if r.type in (T.BALCONY, T.TERRACE, T.VERANDAH):
                side = 0 if load[0] <= load[1] else 1
                put([r], side, front=(r.type is not T.VERANDAH or True))
        # Even out the least depth each column needs (the stair stands in the lighter one),
        # so neither is deeper than the house can be.
        def mind(g):
            return sum(max(r.mina / max(w_est, 1.0), r.minw) for r in g)

        st = 3.5 if multi else 0.0
        for _ in range(8):
            dl, dr = sum(mind(g) for g in left), sum(mind(g) for g in right)
            on_left = (dl <= dr) if stair_col is None else (stair_col == 0)
            eff_l = dl + (st if on_left else 0.0)
            eff_r = dr + (0.0 if on_left else st)
            src, dst, big = (left, right, eff_l - eff_r) if eff_l > eff_r else (right, left, eff_r - eff_l)
            movable = [g for g in src[1:] if g[0].type is not T.GARAGE and g[0].type is not T.LIVING]
            if not movable or big < 0.3:
                break
            g = min(movable, key=lambda g: abs(mind(g) - big / 2))
            if mind(g) >= big:
                break
            src.remove(g)
            dst.append(g)
        cols = [[r for g in left for r in g], [r for g in right for r in g]]
        # Host indices are per group; make them per column.
        for side, grps in ((0, left), (1, right)):
            idx = 0
            for g in grps:
                for r in g:
                    if r.host is not None:
                        r.host = idx
                idx += len(g)
        # The public column's order is front-first living; the other column's first rows are its head.
        return cols[0], cols[1], out

    @staticmethod
    def _stair_column(cols) -> int:
        a = sum(r.area for r in cols[0])
        b = sum(r.area for r in cols[1])
        return 0 if a <= b else 1
