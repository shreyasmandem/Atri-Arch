"""The row-house planner: narrow plots, planned the way Indian towns build them.

On a plot six or seven metres wide a hall running the length of the house
eats a sixth of every floor. The row house does without one:

* A **front band** across the full width - the living room on the ground
  floor, the main bedroom suite upstairs - with a verandah or a balcony in
  front of it.
* A **middle zone** of two columns either side of a short passage: the stair
  in one column (identical on every floor), the bath, puja, utility and any
  room narrow enough in the other. Every room in it has a door on the passage.
* A **back band** across the full width - dining and kitchen on the ground
  floor, the second bedroom suite upstairs - reached from the passage's end.

The passage runs only between the two bands, so it is a few square metres,
not twenty. Anything a band holds besides its main room (a suite's bath, the
kitchen beside the dining room) is reached through that room, as it should be.
"""

from __future__ import annotations

from dataclasses import dataclass

from aip.domain.plan import Room
from aip.engines.architecture.spine import BEDS, MIN_DIM, SMALL, UNDER, Item, SpinePlanner, T, _items

PASSAGE = 1.05
STAIR_COL = 2.4         # a dog-leg 2.4 m wide
STAIR_RUN = 3.81
WET = {T.BATHROOM, T.TOILET, T.POWDER, T.UTILITY, T.LAUNDRY}
MAX_WIDTH = 8.6          # wider than this, the spine planner does better
# A band runs the plot's width, so a room in it only needs its short side here.
BAND_MIN = {T.LIVING: 3.6, T.DRAWING: 3.3, T.MASTER_BEDROOM: 3.3, T.DINING: 2.7, T.FAMILY: 3.0}


@dataclass(frozen=True, slots=True)
class RowVariant:
    stair_low: bool       # the stair column on the low-u side of the passage
    big_front: bool       # the bigger bedroom suite at the front (else the back)


def row_variants() -> list[RowVariant]:
    return [RowVariant(s, b) for s in (True, False) for b in (True, False)]


def _d(it: Item, w: float) -> float:
    """A room's depth across a column or band of width w."""
    return max(MIN_DIM.get(it.type, 1.4), it.area / w, 1.2)


@dataclass(slots=True)
class Band:
    main: Item
    side: Item | None      # reached through the main room: a suite's bath, the kitchen
    depth: float
    side_w: float = 0.0


class RowHousePlanner(SpinePlanner):
    def fits(self) -> bool:
        return self.W <= MAX_WIDTH and self.W - PASSAGE - STAIR_COL >= 2.0

    def _band(self, main: Item, side: Item | None, room_for_side: float) -> Band | None:
        W = self.W
        d = max(BAND_MIN.get(main.type, MIN_DIM.get(main.type, 2.4)), (main.area + (side.area if side else 0.0)) / W)
        if side is None:
            return Band(main, None, d)
        for _ in range(4):
            sw = min(room_for_side, max(MIN_DIM.get(side.type, 1.4), side.area / d))
            mw = W - sw
            if mw < MIN_DIM.get(main.type, 2.4):
                return None
            d = max(d, main.area / mw, side.area / sw if sw else 0.0)
        return Band(main, side, d, sw)

    def plan(self, levels: list[list], v: RowVariant) -> list[list[Room]] | None:  # type: ignore[override]
        self.tr = False
        for scale in (1.0, 0.9, 0.8):
            out = self._plan(levels, v, scale)
            if out is not None:
                return out
        return None

    def _plan(self, levels: list[list], v: RowVariant, scale: float) -> list[list[Room]] | None:
        W, D = self.W, self.D
        stair = self.stair_on
        sw = STAIR_COL
        ca = (0.0, sw) if v.stair_low else (W - sw, W)
        pa = (sw, sw + PASSAGE) if v.stair_low else (W - sw - PASSAGE, W - sw)
        cb = (sw + PASSAGE, W) if v.stair_low else (0.0, W - sw - PASSAGE)
        wa, wb = ca[1] - ca[0], cb[1] - cb[0]
        side_room = max(wa, wb)        # a band's side room sits over one column, clear of the passage

        floors = []
        for li, reqs in enumerate(levels):
            items = _items(reqs)
            for it in items:
                for x in (it, it.bath):
                    if x is None:
                        continue
                    asked = getattr(x.req, "asked_area", None) or x.area
                    floor = asked * 0.85 if scale > 0.85 else max(asked * 0.72, MIN_DIM.get(x.type, 1.4) ** 2 * 1.05)
                    x.area = max(x.area * scale, min(x.area, floor))
            # A car porch the client did not ask for is let go; one they did, this parti cannot hold.
            if any(i.type is T.GARAGE and "Requested" in (getattr(i.req, "notes", "") or "") for i in items):
                self.why = 102; return None
            items = [i for i in items if i.type is not T.GARAGE]
            front_strip = back_strip = None
            fs = [i for i in items if i.type in (T.VERANDAH, T.BALCONY)]
            ts = [i for i in items if i.type is T.TERRACE]
            if len(fs) > 1 or len(ts) > 1:
                self.why = 107; return None
            if fs:
                front_strip = fs[0]
            if ts:
                back_strip = ts[0]
            rest = [i for i in items if i not in fs and i not in ts]
            beds = sorted([i for i in rest if i.type in BEDS], key=lambda i: (i.type is not T.MASTER_BEDROOM, -i.area))
            if not v.big_front and len(beds) >= 2:
                beds[0], beds[1] = beds[1], beds[0]
            front = back = None
            if li == 0:
                main = next((i for i in rest if i.type is T.LIVING), None) or next((i for i in rest if i.type is T.DRAWING), None)
                dining = next((i for i in rest if i.type is T.DINING), None)
                kitchen = next((i for i in rest if i.type is T.KITCHEN), None)
                # The puja opens off the living room, as it does in most homes.
                puja = next((i for i in rest if i.type is T.PUJA), None)
                if main is not None:
                    front = (puja and self._band(main, puja, min(side_room, 2.0))) or self._band(main, None, side_room)
                if dining is not None or kitchen is not None:
                    back = self._band(dining or kitchen, kitchen if dining else None, side_room)
            else:
                if beds:
                    front = self._band(beds[0], beds[0].bath, side_room)
                if len(beds) > 1:
                    back = self._band(beds[1], beds[1].bath, side_room)
                elif back_strip is None:
                    other = next((i for i in rest if i.type in (T.FAMILY, T.LIVING, T.STUDY)), None)
                    if other is not None:
                        back = self._band(other, None, side_room)
            used = {id(b.main) for b in (front, back) if b} | {id(b.side) for b in (front, back) if b and b.side}
            # The rest go to the columns, each room on the passage.
            colA, colB = [], []
            for it in rest:
                if id(it) in used:
                    continue
                if it.type in SMALL and it.bath is None:
                    continue
                if wb < MIN_DIM.get(it.type, 2.4):
                    self.why = 143; return None
                colB.append(it)
                if it.bath is not None:
                    colB.append(it.bath)
            dA = STAIR_RUN if stair else 0.0
            dB = sum(_d(i, wb) for i in colB)
            smalls = sorted([i for i in rest if id(i) not in used and i.type in SMALL and i.bath is None],
                            key=lambda i: i.type is not T.PUJA)
            for it in smalls:
                # A puja never shares a wall with a toilet: it takes the other column.
                if it.type is T.PUJA:
                    to_a = not any(x.type is not T.PUJA for x in colA)
                elif any(x.type is T.PUJA for x in colA):
                    to_a = False
                elif any(x.type is T.PUJA for x in colB):
                    to_a = True
                else:
                    to_a = dA + _d(it, wa) <= dB + _d(it, wb)
                if to_a and wa >= MIN_DIM.get(it.type, 1.4):
                    colA.append(it); dA += _d(it, wa)
                else:
                    colB.append(it); dB += _d(it, wb)
            fd = (max(1.5, min(1.8 if front_strip.type is T.BALCONY else 2.4, front_strip.area / W)) if front_strip else 0.0)
            td = (max(1.5, min(3.0, back_strip.area / W)) if back_strip else 0.0)
            floors.append(dict(front=front, back=back, fs=front_strip, fd=fd, ts=back_strip, td=td,
                               colA=colA, colB=colB, dA=dA, dB=dB))

        # The stair sits right behind the deepest front; every floor's front reaches it.
        F = max(f["fd"] + (f["front"].depth if f["front"] else 0.0) for f in floors)
        s1 = D - F
        s0 = s1 - (STAIR_RUN if stair else 0.0)
        for f in floors:
            f["mid"] = s1 - max(f["dA"], f["dB"], 1.2 if f["front"] and f["back"] else 0.0)
            f["need"] = f["mid"] - (f["back"].depth if f["back"] else 0.0) - f["td"]
        v_back = min(f["need"] for f in floors)
        if v_back < -1e-6:
            self.why = 179; return None
        v_back = max(0.0, v_back)

        out, below = [], []
        for li, f in enumerate(floors):
            rooms: list[Room] = []

            def add(t, a0, b0, a1, b1, req=None, name=None, _rooms=rooms, _li=li):
                if a1 - a0 < 0.9 or b1 - b0 < 0.9:
                    return None
                area = round((a1 - a0) * (b1 - b0), 2)
                r = Room(name=name or getattr(req, "label", None) or t.label, type=t, polygon=self._poly(a0, b0, a1, b1), level=_li,
                         ceiling_height=3.0,
                         metadata={"_c": (a0, b0, a1, b1), "notes": getattr(req, "notes", "") or "",
                                   "target_area": getattr(req, "target_area", None) or area,
                                   "brief_area": getattr(req, "asked_area", None) or getattr(req, "target_area", None) or area,
                                   "planner": "row"})
                _rooms.append(r)
                return r

            def bad(a0, b0, a1, b1):
                return sum(w * max(0.0, min(a1, c[2]) - max(a0, c[0])) * max(0.0, min(b1, c[3]) - max(b0, c[1]))
                           for w, c in below)

            def band(b: Band, lo: float, hi: float):
                if b.side is None:
                    add(b.main.type, 0.0, lo, W, hi, b.main.req)
                    return
                # The side room over one column, clear of the passage; upstairs,
                # over whichever end keeps a bath off the kitchen below.
                ends = [e for e in ((0.0, b.side_w), (W - b.side_w, W)) if e[1] <= pa[0] + 1e-6 or e[0] >= pa[1] - 1e-6]
                if not ends:
                    ends = [(cb if wb >= wa else ca)]
                # A puja goes over the stair column, away from the baths in the other.
                e = min(ends, key=lambda e: (bad(e[0], lo, e[1], hi) if li else 0.0,
                                             b.side.type is T.PUJA and abs(e[0] - ca[0]) > 1e-6))
                add(b.side.type, e[0], lo, e[1], hi, b.side.req)
                m0, m1 = (e[1], W) if e[0] < 1e-6 else (0.0, e[0])
                add(b.main.type, m0, lo, m1, hi, b.main.req)

            top = D
            if f["fs"] is not None:
                add(f["fs"].type, 0.0, D - f["fd"], W, D, f["fs"].req)
                top = D - f["fd"]
            if f["front"] is not None:
                band(f["front"], s1, top)
            mid = f["mid"]
            # The back band takes up to a quarter more depth; the columns the rest.
            if f["back"] is not None:
                bd = f["back"].depth
                room = mid - f["td"] - v_back - bd
                grow = min(room, bd * 0.25)
                mid -= room - grow
                gap = s0 - mid
                if stair and not f["colA"] and 0.05 < gap < 1.2:
                    # Behind the stair, either a room's worth (a store) or nothing:
                    # the back band gives up its growth, or takes the sliver.
                    if s0 - 1.2 >= v_back + f["td"] + bd - 1e-6:
                        mid = s0 - 1.2
                    elif s1 - f["dB"] >= s0 - 1e-6:
                        mid = s0
                    else:
                        self.why = 236; return None
                band(f["back"], v_back + f["td"], mid)
            elif f["td"] == 0.0:
                mid = v_back
            if f["ts"] is not None:
                if f["back"] is None:
                    mid = v_back + f["td"]
                add(f["ts"].type, 0.0, v_back, W, v_back + f["td"], f["ts"].req)
            add(T.CORRIDOR, pa[0], mid, pa[1], s1, name="Corridor")
            if stair:
                add(T.STAIRCASE, ca[0], s0, ca[1], s1, name="Staircase")
            if self._column(add, f["colA"], ca, s0 if stair else s1, mid):
                self.why = 250; return None       # a sliver no room can use
            if li and below:
                # Upstairs, the order down the column that keeps its baths off the kitchen below.
                def wet_bad(order, col=cb):
                    cur, tot = s1, 0.0
                    for it in order:
                        d = _d(it, col[1] - col[0])
                        if it.type in WET:
                            tot += bad(col[0], cur - d, col[1], cur)
                        cur -= d
                    return tot
                f["colB"] = min((f["colB"], f["colB"][::-1]), key=wet_bad)
            self._column(add, f["colB"], cb, s1, mid)
            if li == 0:
                below = [(UNDER[r.type], r.metadata["_c"]) for r in rooms if r.type in UNDER]
            out.append(rooms)
        return out

    def _column(self, add, items: list[Item], col: tuple[float, float], top: float, bottom: float):
        """Stack rooms down a column from `top`; what is left grows the rooms or becomes a store."""
        w = col[1] - col[0]
        if top - bottom < 0.05:
            return None
        ds = [_d(i, w) for i in items]
        spare = (top - bottom) - sum(ds)
        # Rooms grow to fill the column before any store is drawn: the main
        # rooms by up to a third, then the small ones by up to a quarter.
        for grow, k_ in (([k for k, i in enumerate(items) if i.type not in SMALL], 1.3),
                         ([k for k, i in enumerate(items) if i.type in SMALL], 1.25)):
            if spare > 0 and grow:
                for k in grow:
                    extra = min(spare / len(grow), max(0.0, items[k].area * k_ / w - ds[k]))
                    ds[k] += extra
                spare = (top - bottom) - sum(ds)
        cur = top
        made = []
        for it, d in zip(items, ds, strict=True):
            r = add(it.type, col[0], cur - d, col[1], cur, it.req)
            if r is not None:
                made.append(r)
            cur -= d
        if spare >= 1.2:
            add(T.STORE, col[0], bottom, col[1], cur, name="Store")
        elif spare > 0.05 and made:
            r = made[-1]
            c = r.metadata["_c"]
            nc = (c[0], bottom, c[2], c[3])
            r.polygon = self._poly(*nc); r.metadata["_c"] = nc
        elif spare > 0.05:
            return (bottom, cur)
        return None
