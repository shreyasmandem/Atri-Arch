"""The spine planner: plans laid out the way an architect sketches them.

The genetic search partitions a rectangle and hopes the partition reads as a
house. This does the opposite: it starts from the parti most good Indian
houses share and fits the programme to it.

* A **hall spine** runs from the front door to the back. Every room opens off
  it, so no bedroom is reached through the living room, no toilet opens onto
  the dining table, and nobody walks through one room to reach another.
* Rooms sit in two **stacks**, one either side of the spine, so every room has
  a door on the spine and a window on an outside wall. Small rooms (puja,
  utility, powder room) share a row side by side rather than becoming slots.
* The **stair** is one rectangle beside the spine, identical on every floor.
* A bedroom and its **attached bath** are a suite: the bath behind the room,
  on the same outside wall.
* Rooms are **sized, not stretched**: a stack is as wide and as deep as its
  rooms want to be, capped at what a room of its kind usefully is. A big plot
  gets a bigger house (more and more generous rooms, set by the programme),
  with the rest of the plot left as garden rather than turned into a 70 m2
  dining room.

Everything is computed in a canonical frame (the road at the front, high v)
and turned to the real road at the end. Variants - which side the public rooms
take, where the stair sits, suite order, snug or generous stacks - give the
selector real choices.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

from aip.domain.geometry import BoundingBox, Direction, Vec2, rectangle
from aip.domain.plan import Room, RoomType

T = RoomType
BEDS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM}
PUBLIC = [T.LIVING, T.DRAWING, T.FAMILY, T.DINING, T.KITCHEN, T.PANTRY, T.UTILITY, T.LAUNDRY]
SKIP = {T.STAIRCASE, T.CORRIDOR, T.LOBBY, T.SHAFT, T.FOYER, T.WARDROBE}
#: Rooms small enough to share a row with a neighbour.
SMALL = {T.PUJA, T.UTILITY, T.LAUNDRY, T.POWDER, T.TOILET, T.STORE, T.PANTRY, T.BATHROOM}
WETS = {T.UTILITY, T.LAUNDRY, T.POWDER, T.TOILET, T.BATHROOM}
#: The smallest dimension a room can have and still be furnished.
MIN_DIM = {T.MASTER_BEDROOM: 3.4, T.BEDROOM: 3.0, T.GUEST_BEDROOM: 3.0, T.CHILDREN_BEDROOM: 3.0,
           T.LIVING: 4.2, T.DINING: 3.0, T.KITCHEN: 2.4, T.BATHROOM: 1.6, T.TOILET: 1.4, T.POWDER: 1.3,
           T.UTILITY: 1.4, T.PUJA: 1.4, T.STUDY: 2.6, T.FAMILY: 3.2, T.DRAWING: 3.4, T.GARAGE: 5.0,
           T.STORE: 1.4, T.BALCONY: 1.5, T.VERANDAH: 1.8, T.COURTYARD: 3.0, T.FOYER: 1.8, T.HOME_THEATRE: 3.6, T.GYM: 3.0, T.LIBRARY: 2.6, T.HOME_OFFICE: 2.6, T.SERVANT: 2.6}
#: How far a room may grow past its programme area; beyond it the plot is garden.
GROW = 1.1
SPINE = 1.4
FOYER = 2.2
STAIR_W, STAIR_L = 2.5, 4.6
BATH_DEPTH = 1.7


@dataclass(slots=True)
class Item:
    type: RoomType
    area: float
    req: object | None = None
    bath: Item | None = None


@dataclass(slots=True)
class Row:
    """One row of a stack: one room, a suite's bath, or small rooms side by side."""
    parts: list[Item]
    suite: bool = False
    depth: float = 0.0
    cap: float = 0.0
    grow: bool = True
    widths: list | None = None     # explicit widths, hall side first, for rooms side by side


@dataclass(slots=True)
class Variant:
    public_left: bool
    stair_at: float
    bath_behind: bool
    wide: float          # 0 snug .. 1 generous stacks
    transverse: bool = False   # spine parallel to the road (wide, shallow plots)
    single: bool = False       # narrow plots: one row of rooms beside a side hall


def variants() -> list[Variant]:
    return [Variant(pl, sa, bb, w, tr) for tr, pl, sa, bb, w in
            itertools.product((False, True), (True, False), (0.3, 0.7), (True, False), (0.0, 1.0))
            if not (tr and pl)] + [Variant(pl, sa, True, 0.0, tr, True) for pl in (True, False) for sa in (0.0, 0.4) for tr in (False, True)]         + [Variant(pl, 0.0, True, 0.0, tr) for pl in (True, False) for tr in (False, True) if not (tr and pl)]


def _items(reqs: list) -> list[Item]:
    items = [Item(r.type, float(r.target_area), r) for r in reqs if r.type not in SKIP]
    beds = sorted([i for i in items if i.type in BEDS], key=lambda i: (i.type is not T.MASTER_BEDROOM, -i.area))
    baths = sorted([i for i in items if i.type in {T.BATHROOM, T.TOILET}], key=lambda i: -i.area)
    # With fewer baths than bedrooms, one stays common, off the hall, so the
    # bedrooms without their own still have a bathroom they can reach.
    attach = len(baths) - (1 if 0 < len(baths) < len(beds) else 0)
    for bed in beds[:attach]:
        bed.bath = baths.pop(0)
        items.remove(bed.bath)
        if bed.req is not None and hasattr(bed.req, "attached_bathroom"):
            bed.req.attached_bathroom = True
    return items


ORDER_PUB = [T.FOYER, T.DRAWING, T.LIVING, T.DINING, T.KITCHEN, T.PANTRY, T.UTILITY, T.LAUNDRY]
PUBLIC = [t for t in ORDER_PUB if t is not T.FOYER]
RANK = {T.PUJA: 0, T.STUDY: 1, T.HOME_OFFICE: 1, T.LIBRARY: 1, T.GUEST_BEDROOM: 2, T.POWDER: 3,
        T.TOILET: 3, T.BATHROOM: 3, T.STORE: 3, T.CHILDREN_BEDROOM: 4, T.BEDROOM: 4, T.MASTER_BEDROOM: 5}


class SpinePlanner:
    def __init__(self, envelope: BoundingBox, road: Direction | None, stair_on: bool) -> None:
        self.env = envelope
        r = (road.cardinal if road is not None else Direction.N).value
        self.road = r if r in {"N", "S", "E", "W"} else "N"
        across_x = self.road in {"N", "S"}
        self.W = envelope.width if across_x else envelope.height
        self.D = envelope.height if across_x else envelope.width
        self.stair_on = stair_on

    def _poly(self, u0: float, v0: float, u1: float, v1: float):
        if getattr(self, "tr", False):
            u0, v0, u1, v1 = v0, u0, v1, u1
        e, W, D = self.env, self.W, self.D
        if self.road == "N":
            x0, y0, x1, y1 = e.min_x + u0, e.min_y + v0, e.min_x + u1, e.min_y + v1
        elif self.road == "S":
            x0, y0, x1, y1 = e.min_x + (W - u1), e.min_y + (D - v1), e.min_x + (W - u0), e.min_y + (D - v0)
        elif self.road == "E":
            x0, y0, x1, y1 = e.min_x + v0, e.min_y + (W - u1), e.min_x + v1, e.min_y + (W - u0)
        else:
            x0, y0, x1, y1 = e.min_x + (D - v1), e.min_y + u0, e.min_x + (D - v0), e.min_y + u1
        return rectangle(Vec2(x0, y0), x1 - x0, y1 - y0)

    def _rows(self, items: list[Item], width: float, v: Variant) -> list[Row]:
        rows: list[Row] = []
        smalls: list[Item] = []

        def flush():
            while smalls:
                take, used = [], 0.0
                while smalls and len(take) < 3 and used + max(MIN_DIM.get(smalls[0].type, 1.4), 1.6) <= width + 1e-6:
                    if take and ((smalls[0].type is T.PUJA) != (take[0].type is T.PUJA)):
                        break
                    it = smalls.pop(0)
                    take.append(it)
                    used += max(MIN_DIM.get(it.type, 1.4), 1.6)
                if not take:
                    take = [smalls.pop(0)]
                area = sum(i.area for i in take)
                # Alone, a small room runs the stack's width at its minimum depth.
                d = (max(1.2, 5.5 / width) if take[0].type is T.PUJA else max(MIN_DIM.get(take[0].type, 1.4), 1.5))                     if len(take) == 1 else max(area / width, 1.6)
                rows.append(Row(take, depth=d, cap=max(d, 2.4), grow=False))

        pending = list(items)
        while pending:
            it = pending.pop(0)
            if it.type in SMALL and it.bath is None:
                smalls.append(it)
                continue
            flush()
            mn = MIN_DIM.get(it.type, 2.4)
            # A wide stack takes two rooms side by side: a bedroom with its bath
            # beyond it, or the dining room with the kitchen beyond it.
            if it.bath is not None and width >= mn + 1.8:
                bw = min(2.4, max(1.6, width - mn - 0.0)) if width < mn + 2.4 else 2.0
                d = max(it.area / (width - bw), mn, it.bath.area / bw, 2.0)
                rows.append(Row([it, it.bath], depth=d, cap=d, grow=False, widths=[width - bw, bw]))
                continue
            nxt = pending[0] if pending else None
            if it.type is T.DINING and nxt is not None and nxt.type is T.KITCHEN and width >= 5.4:
                pending.pop(0)
                wk = max(2.4, width * nxt.area / (nxt.area + it.area))
                d = max((it.area + nxt.area) / width, 3.0)
                rows.append(Row([it, nxt], depth=d, cap=d * 1.15, widths=[width - wk, wk]))
                continue
            d = max(it.area / width, MIN_DIM.get(it.type, 2.4))
            fixed = it.type in {T.VERANDAH, T.COURTYARD, T.GARAGE, T.FOYER, T.BALCONY}
            asked = getattr(it.req, "asked_area", None) or it.area
            main = Row([it], depth=d, cap=d if fixed else max(d, min(it.area * GROW, asked * 1.45) / width), grow=not fixed)
            if it.bath is not None:
                bath = Row([it.bath], suite=True, depth=BATH_DEPTH, cap=BATH_DEPTH, grow=False)
                rows.extend([main, bath] if v.bath_behind else [bath, main])
            else:
                rows.append(main)
        flush()
        # A puja never shares a wall with a toilet: move it away from wet rows.
        wet = lambda r: any(x.type in WETS for x in r.parts) or r.suite  # noqa: E731
        for k, r in enumerate(rows):
            if any(x.type is T.PUJA for x in r.parts):
                near = [rows[j] for j in (k - 1, k + 1) if 0 <= j < len(rows)]
                if any(wet(n) for n in near):
                    rows.pop(k)
                    spot = next((j for j in range(len(rows) + 1)
                                 if not any(wet(rows[x]) for x in (j - 1, j) if 0 <= x < len(rows))), 0)
                    rows.insert(spot, r)
                break
        return rows

    def plan(self, levels: list[list], v: Variant) -> list[list[Room]] | None:
        # Transverse: the same parti turned so the spine runs along the road.
        self.tr = v.transverse
        W, D = (self.D, self.W) if v.transverse else (self.W, self.D)
        self.outer = {}
        levels = [list(l) for l in levels]
        self.verandah = None
        # Courtyards, verandahs and car porches are ground-floor rooms.
        for l in levels[1:]:
            for r in [r for r in l if r.type in {T.COURTYARD, T.VERANDAH, T.GARAGE}]:
                l.remove(r); levels[0].append(r)
        # A bedroom floor needs its bathrooms on it: pull a spare one from a floor that has more.
        def count(l, ts): return sum(1 for r in l if r.type in ts)
        for li, l in enumerate(levels):
            while count(l, BEDS) > count(l, {T.BATHROOM, T.TOILET}):
                donor = next((d for d in levels if d is not l and count(d, {T.BATHROOM, T.TOILET}) > max(count(d, BEDS), 1)), None)
                if donor is None:
                    break
                b = next(r for r in donor if r.type in {T.BATHROOM, T.TOILET})
                donor.remove(b); l.append(b)
        split = []
        for li, items in enumerate(_items(r) for r in levels):
            terr = [i for i in items if i.type is T.TERRACE]
            if len(terr) > 1:
                items = [i for i in items if i.type is not T.TERRACE] + [Item(T.TERRACE, min(sum(i.area for i in terr), 20.0), terr[0].req)]
            out = [i for i in items if i.type.is_outdoor or i.type is T.GARAGE]
            rest = [i for i in items if i not in out]
            pub = sorted([i for i in rest if i.type in PUBLIC], key=lambda i: ORDER_PUB.index(i.type))
            priv = sorted([i for i in rest if i not in pub], key=lambda i: RANK.get(i.type, 3))
            if li == 0 and v.transverse:
                # The spine no longer reaches the road: the foyer heads the public stack.
                pub.insert(0, Item(T.FOYER, 6.5))
            if li > 0 and not pub:
                # Bedrooms either side of the hall, balanced by depth (the
                # stair already takes some of the private side).
                pub, priv2, dp, dq = [], [], 0.0, STAIR_L if self.stair_on else 0.0
                for it in sorted(priv, key=lambda i: -(i.area + (i.bath.area if i.bath else 0))):
                    d = it.area / 4 + (BATH_DEPTH if it.bath else 0)
                    if dp <= dq:
                        pub.append(it); dp += d
                    else:
                        priv2.append(it); dq += d
                pub.sort(key=lambda i: RANK.get(i.type, 3)); priv = sorted(priv2, key=lambda i: RANK.get(i.type, 3))
            # Outdoor rooms: a sit-out heads the public stack, a car porch the
            # private one, a courtyard opens in the private stack; upstairs,
            # balconies and terraces take the front of the private stack.
            fronts = []
            for it in out:
                if li == 0 and it.type is T.VERANDAH:
                    if v.transverse:
                        pub.insert(1 if pub and pub[0].type is T.FOYER else 0, Item(T.VERANDAH, min(it.area, 9.0), it.req))
                    else:
                        self.verandah = Item(T.VERANDAH, it.area, it.req)   # a band across the front
                elif li == 0 and it.type is T.GARAGE:
                    priv.insert(0, Item(T.GARAGE, it.area, it.req))
                elif li == 0 and it.type is T.COURTYARD:
                    priv.insert(min(2, len(priv)), Item(T.COURTYARD, min(it.area, 16.0), it.req))
                elif li > 0 and it.type in {T.BALCONY, T.TERRACE}:
                    fronts.append(Item(it.type, min(it.area, 8.0 if it.type is T.BALCONY else 14.0), it.req))
            # A balcony that opens off a named room goes beside that room, in its
            # stack, behind its suite - at the back wall, so it is open to the sky.
            for it in list(fronts):
                note = (getattr(it.req, "notes", "") or "").lower()
                if "opens off the" not in note:
                    continue
                host_name = note.split("opens off the", 1)[1].strip(" .")
                host_type = next((t for t in BEDS | {T.LIVING, T.FAMILY, T.STUDY, T.DINING, T.KITCHEN}
                                  if t.value.replace("_", " ") == host_name), None)
                for stack in (pub, priv):
                    host = next((x for x in stack if x.type is host_type), None)
                    if host is not None:
                        fronts.remove(it)
                        stack.insert(stack.index(host) + 1, Item(T.BALCONY, min(it.area, 7.0), it.req))
                        break
            split.append((pub, priv, fronts))

        def want(items, lo, hi):
            if not items:
                return lo
            need = max(MIN_DIM.get(i.type, 2.4) for i in items)
            return min(hi, max(lo, need + 0.2, (max(i.area for i in items) * 1.15) ** 0.5))
        hall_w = SPINE
        if v.single:
            # A narrow plot: every room in one row beside a side hall.
            split = [([], ([Item(T.FOYER, 4.5)] if li == 0 else [])
                      + [i for i in sorted(p, key=lambda i: ORDER_PUB.index(i.type) if i.type in ORDER_PUB else 0)] + q, f)
                     for li, (p, q, f) in enumerate(split)]
            hall_w = 1.2
            pw, qw = 0.0, min(W - hall_w, 6.5)
            if qw < 3.0:
                self.why = 1
                return None
        else:
            pw = max(want(p, 3.6, 4.6 + 1.6 * v.wide) for p, _, _ in split)
            qw = max(want(q, 3.2, min(3.6 if self.stair_on else 4.6, 4.2 + 1.4 * v.wide)) for _, q, _ in split)
        if self.stair_on:
            qw = max(qw, STAIR_W)
        if not v.single and pw + SPINE + qw > W:
            free = W - SPINE
            if free < 2 * 2.8:
                self.why = 2
                return None
            k = free / (pw + qw)
            pw, qw = pw * k, qw * k
        SP = hall_w
        self.spine = None
        Wh = pw + SP + qw
        u_off = (W - Wh) / 2 if not v.transverse else W - Wh   # transverse: the house against the road
        self.house = (u_off, u_off + Wh)
        if v.public_left:
            pl, spine, ql = (u_off, u_off + pw), (u_off + pw, u_off + pw + SP), (u_off + pw + SP, u_off + Wh)
        else:
            ql, spine, pl = (u_off, u_off + qw), (u_off + qw, u_off + qw + SP), (u_off + qw + SP, u_off + Wh)

        # A dog-leg of about 11 m2: deeper when the stack is narrow, shallower when wide.
        wq = ql[1] - ql[0]
        # The stair spans its stack (so it always opens onto the hall), as deep
        # as a dog-leg of about 11 m2 needs: 3.8 m when narrow, less when wide.
        sw = wq
        stair_len = 3.81 if self.stair_on else 0.0     # a dog-leg's run, whatever the stack width
        plans, need_d, cap_d = [], 0.0, 0.0
        for li, (pub, priv, fronts) in enumerate(split):
            head = FOYER if li == 0 and not v.transverse and not v.single else 0.0
            # Upstairs, the side over the kitchen puts each bath in front of its
            # bedroom (toward the living room), not over the kitchen at the back.
            vv = v if li == 0 else replace(v, bath_behind=False)
            ver = 1.8 if li == 0 and self.verandah is not None else 0.0
            fitted = self._fit_level(pub, priv, fronts, pl[1] - pl[0], ql[1] - ql[0], D - ver, stair_len + head, vv)
            if fitted is None:
                self.why = 3
                return None
            prow, qrow, fronts = fitted
            fdepth = sum(max(1.5, min(1.8 if i.type is T.BALCONY else 3.0, i.area / (ql[1] - ql[0]))) for i in fronts)
            need_d = max(need_d, sum(r.depth for r in prow) + ver, sum(r.depth for r in qrow) + stair_len + fdepth + head + ver)
            cap_d = max(cap_d, sum(r.cap for r in prow), sum(r.cap for r in qrow) + stair_len + fdepth + head)
            plans.append((prow, qrow, fronts))
        if need_d > D + 1e-6:
            self.why = 4
            return None
        Dh = min(D, max(need_d, cap_d))
        v0 = D - Dh
        self.spine = spine
        stair = None
        if self.stair_on:
            # The stair takes the stack's full width (a roomier landing) unless
            # the stack is wide enough to leave a useful room beside it.
            # The stair on the outer side; any strip between it and the hall is its landing lobby.
            su0 = ql[1] - sw if v.public_left else ql[0]
            free = Dh - STAIR_L
            head0 = (FOYER if not v.transverse and not v.single else 0.0) + (1.8 if self.verandah is not None else 0.0)
            free = Dh - stair_len - head0
            sv0 = v0 + free * v.stair_at
            # Never leave a sliver beside the stair that no room can use.
            if (D - head0) - (sv0 + stair_len) < 2.4:
                sv0 = D - head0 - stair_len
            if sv0 - v0 < 2.4:
                sv0 = v0
            stair = (su0, sv0, su0 + sw, sv0 + stair_len)

        out_levels = []
        for li, (prow, qrow, fronts) in enumerate(plans):
            rooms: list[Room] = []

            def add(t, a0, b0, a1, b1, req=None, name=None, _rooms=rooms, _li=li):
                if a1 - a0 < 0.9 or b1 - b0 < 0.9:
                    return
                area = round((a1 - a0) * (b1 - b0), 2)
                _rooms.append(Room(name=name or t.label, type=t, polygon=self._poly(a0, b0, a1, b1), level=_li,
                                   ceiling_height=3.0,
                                   metadata={"_c": (a0, b0, a1, b1), "notes": getattr(req, "notes", "") or "",
                                             "target_area": getattr(req, "target_area", None) or area,
                                             "brief_area": getattr(req, "asked_area", None) or getattr(req, "target_area", None) or area,
                                             "planner": "spine"}))
            s0, s1 = spine
            Dl = D
            if li == 0 and self.verandah is not None:
                # A covered verandah across the whole front, the house behind it.
                Dl = D - 1.8
                add(T.VERANDAH, self.house[0], Dl, self.house[1], D, self.verandah.req, name="Verandah")
            foyer_cut = 0.0
            if li == 0 and not v.transverse and not v.single:
                # The entrance hall: across the head of the hall and the front of
                # the private stack, so it opens straight onto the living room.
                fu0, fu1 = min(s0, ql[0]), max(s1, ql[1])
                add(T.FOYER, fu0, Dl - FOYER, fu1, Dl, name="Foyer")
                foyer_cut = FOYER
                add(T.CORRIDOR, s0, v0, s1, Dl - FOYER, name="Corridor")
            else:
                add(T.CORRIDOR, s0, v0, s1, Dl, name="Corridor")
            if stair:
                add(T.STAIRCASE, *stair, name="Staircase")
            self.level = li
            self.v0 = v0
            self.rooms_ref = rooms
            if not self._fill(add, pl, prow, v0, Dl, None, []):
                self.why = 5
                return None
            if not self._fill(add, ql, qrow, v0, Dl - foyer_cut, stair, fronts):
                self.why = 6
                return None
            out_levels.append(rooms)
        return out_levels

    def _fit_level(self, pub, priv, fronts, wp, wq, D, stair_len, v):
        """Make a floor's programme fit its two stacks, the way a designer would:
        move a bedroom suite to the other side of the hall, then let go of the
        extras the programme added to fill a generous plot, then draw rooms a
        little smaller - never below what they need to be furnished."""
        pub, priv, fronts = list(pub), list(priv), list(fronts)
        optional = [T.COURTYARD, T.VERANDAH, T.HOME_THEATRE, T.GYM, T.LIBRARY, T.FAMILY, T.STUDY, T.TERRACE,
                    T.GARAGE, T.BALCONY, T.STORE]
        def depth(items, w, extra=0.0, scale=1.0):
            saved = [(i, i.area) for i in items] + [(i.bath, i.bath.area) for i in items if i.bath]
            for i, a in saved:
                i.area = shrink(i, a, scale)
            rows = self._rows(items, w, v)
            for i, a in saved:
                i.area = a
            return sum(r.depth for r in rows) + extra
        def fdep():
            return sum(max(1.5, min(1.8 if i.type is T.BALCONY else 3.0, i.area / wq)) for i in fronts)
        def shrink(i, a, scale):
            # Draw a room smaller than the generous size the programme grew it
            # to, but never below 85 % of what the client asked for.
            asked = getattr(i.req, "asked_area", None) or a
            return max(a * scale, min(a, asked * 0.85))
        for scale in (1.0, 0.9, 0.8, 0.7, 0.6):
            for _ in range(12):
                dp, dq = depth(pub, wp, 0.0, scale), depth(priv, wq, stair_len + fdep() + (1.0 if stair_len and 0.0 < v.stair_at < 1.0 else 0.0), scale)
                if dp <= D + 1e-6 and dq <= D + 1e-6:
                    if scale < 1.0:
                        for i in pub + priv:
                            i.area = shrink(i, i.area, scale)
                            if i.bath:
                                i.bath.area = max(shrink(i.bath, i.bath.area, scale), 3.2)
                    return self._rows(pub, wp, v), self._rows(priv, wq, v), fronts
                # Move a suite or room across the hall to the emptier side.
                src, dst, ws, wd = (priv, pub, wq, wp) if dq > dp else (pub, priv, wp, wq)
                if wp <= 0:
                    src, dst, ws, wd = priv, [], wq, 0.0
                movable = [i for i in src if i.type in BEDS or i.type in {T.STUDY, T.FAMILY, T.STORE, T.PUJA}]
                moved = False
                for it in (sorted(movable, key=lambda i: -(i.area + (i.bath.area if i.bath else 0))) if wd > 0 else []):
                    trial_src = [i for i in src if i is not it]
                    trial_dst = dst + [it]
                    a_src = depth(trial_src, ws, (stair_len + fdep()) if src is priv else 0.0, scale)
                    a_dst = depth(trial_dst, wd, (stair_len + fdep()) if dst is priv else 0.0, scale)
                    if max(a_src, a_dst) < max(dp, dq) - 0.05:
                        src.remove(it); dst.append(it)
                        moved = True
                        break
                if moved:
                    continue
                # Let go of the extras, least needed first.
                for t in optional:
                    # Never what the client asked for - only what the programme added.
                    pool = [x for x in (fronts if t in {T.TERRACE, T.BALCONY} else (priv if dq > dp else pub))
                            if x.type is t and "Requested" not in (getattr(x.req, "notes", "") or "")]
                    if pool:
                        (fronts if t in {T.TERRACE, T.BALCONY} else (priv if dq > dp else pub)).remove(pool[-1])
                        moved = True
                        break
                if not moved:
                    break
        return None

    def _trim_hall(self, rooms: list[Room], li: int, spine, v0: float) -> None:
        """Stop the hall at the last door it serves; the back room on one side
        takes the end of the spine instead of leaving a dead-end passage."""
        s0, s1 = spine
        canon = {id(r): r.metadata.get("_c") for r in rooms}
        hall = next((r for r in rooms if r.type is T.CORRIDOR), None)
        if hall is None:
            return
        backs = []
        for side in ((None, s0), (s1, None)):
            cands = [r for r in rooms if r is not hall and canon[id(r)] and abs(canon[id(r)][1] - v0) < 0.01
                     and ((side[1] is not None and abs(canon[id(r)][2] - s0) < 0.01) or (side[0] is not None and abs(canon[id(r)][0] - s1) < 0.01))]
            if cands:
                backs.append(cands[0])
        if len(backs) != 2:
            return
        a, b = sorted(backs, key=lambda r: canon[id(r)][3] - canon[id(r)][1])
        da, db = canon[id(a)][3] - v0, canon[id(b)][3] - v0
        if db - da < 1.0 or a.type in {T.STAIRCASE, T.TERRACE} or a.type.is_wet:
            return
        hc = canon[id(hall)]
        # The shallower back room widens across the spine; the hall starts above it.
        ac = canon[id(a)]
        na = (min(ac[0], s0), ac[1], max(ac[2], s1), ac[3])
        nh = (hc[0], v0 + da, hc[2], hc[3])
        a.polygon = self._poly(*na); a.metadata["_c"] = na
        hall.polygon = self._poly(*nh); hall.metadata["_c"] = nh

    def _fill(self, add, side, rows: list[Row], v0: float, D: float, stair, fronts: list[Item]) -> bool:
        u0, u1 = side
        width = u1 - u0
        spans = [(v0, D)]
        if stair and stair[0] < u1 - 0.01 and stair[2] > u0 + 0.01:
            sv0, sv1 = stair[1], stair[3]
            if width - (stair[2] - stair[0]) >= 1.4:
                inner = (stair[2], u1) if stair[0] <= u0 + 0.01 else (u0, stair[0])
                add(T.STORE, inner[0], sv0, inner[1], sv1, name="Store")
            spans = [(sv1, D), (v0, sv0)]
        top = D
        front_floor = max(lo for lo, hi in spans if hi >= D - 1e-6)   # the stair, if it sits at the front
        for it in fronts:
            d = max(1.5, min(1.8 if it.type is T.BALCONY else 3.0, it.area / width))
            if top - d < front_floor - 1e-6:
                continue            # no room in front of the stair; the floor's leftover becomes terrace
            add(it.type, u0, top - d, u1, top, it.req)
            top -= d
        bins = [[lo, min(hi, top)] for lo, hi in spans if min(hi, top) - lo > 0.05]
        groups, k = [], 0
        while k < len(rows):
            g = [rows[k]]
            if k + 1 < len(rows) and rows[k].suite != rows[k + 1].suite and (rows[k].suite or rows[k + 1].suite):
                g.append(rows[k + 1])
            groups.append(g)
            k += len(g)
        placed: list[list[Row]] = [[] for _ in bins]
        bi, left = 0, (bins[0][1] - bins[0][0]) if bins else 0.0
        for g in groups:
            gd = sum(r.depth for r in g)
            while bi < len(bins) and gd > left + 1e-6:
                bi += 1
                left = (bins[bi][1] - bins[bi][0]) if bi < len(bins) else 0.0
            if bi >= len(bins):
                return False
            placed[bi].extend(g)
            left -= gd
        for (lo, hi), rs in zip(bins, placed, strict=True):
            spare = (hi - lo) - sum(r.depth for r in rs)
            for _ in range(4):
                room_for = [r for r in rs if r.grow and r.cap - r.depth > 1e-3]
                if spare <= 1e-3 or not room_for:
                    break
                share = spare / len(room_for)
                for r in room_for:
                    d = min(share, r.cap - r.depth)
                    r.depth += d
                    spare -= d
            # What is left after every room reached its natural size: shared by
            # the main rooms up to half again their depth; anything beyond that
            # becomes a room of its own at the back (a sitting room downstairs,
            # an open terrace upstairs) or, if too small for one, goes to the
            # biggest room.
            if spare > 1e-3 and rs:
                takers = [r for r in rs if r.grow and r.cap - r.depth > 1e-3]
                for r in takers:
                    r.depth += min(spare * r.depth / sum(t.depth for t in takers), r.cap - r.depth)
                spare = (hi - lo) - sum(r.depth for r in rs)
                growable = [r for r in rs if r.grow]
                if 1e-3 < spare < 1.2 and growable:
                    max(growable, key=lambda r: r.depth).depth += spare
                    spare = 0.0
            cursor = hi
            for r in rs:
                b0 = cursor - r.depth
                if r.widths:
                    hall_low = abs(u0 - self.spine[1]) < 0.01
                    a = u0 if hall_low else u1
                    for part, w in zip(r.parts, r.widths, strict=True):
                        if hall_low:
                            add(part.type, a, b0, a + w, cursor, part.req); a += w
                        else:
                            add(part.type, a - w, b0, a, cursor, part.req); a -= w
                elif len(r.parts) == 1:
                    add(r.parts[0].type, u0, b0, u1, cursor, r.parts[0].req)
                else:
                    tot = sum(max(p.area, 1.0) for p in r.parts)
                    a = u0
                    outer_low = abs(u0 - self.house[0]) < 0.01
                    parts = sorted(r.parts, key=lambda p: (p.type in WETS) != outer_low)
                    for p in parts:
                        w = width * max(p.area, 1.0) / tot
                        add(p.type, a, b0, a + w, cursor, p.req)
                        a += w
                cursor = b0
            if cursor - lo > 0.05:
                gap = cursor - lo
                if self.level > 0 and gap >= 1.5 and abs(lo - self.v0) < 0.01:
                    add(T.TERRACE, u0, lo, u1, cursor, name="Terrace")
                elif self.level == 0 and gap >= 3.0:
                    add(T.FAMILY, u0, lo, u1, cursor, name="Family")
                elif gap >= 1.4 and not (rs and rs[-1].grow):
                    add(T.STORE, u0, lo, u1, cursor, name="Store")
                elif rs:
                    # Too small to be a room: every room on the last row reaches down to close it.
                    for room in self.rooms_ref:
                        c = room.metadata.get("_c")
                        if c and abs(c[1] - cursor) < 0.01 and c[0] >= u0 - 0.01 and c[2] <= u1 + 0.01:
                            nc = (c[0], lo, c[2], c[3])
                            room.polygon = self._poly(*nc); room.metadata["_c"] = nc
        return True
