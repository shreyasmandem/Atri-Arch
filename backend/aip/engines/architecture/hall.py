"""The hall planner: a generous plot filled with house, and no corridor.

On a plot far larger than the rooms asked for, the other planners draw the
house they know - a compact block with a passage down it - and leave the rest
as paving. This one starts from the plate the plot allows (everything but the
lawn the client kept, within the setbacks, coverage and FAR) and fills it:

* the plate is three **bands**. The middle one is the house's hall - the living
  and dining rooms downstairs, the family lounge upstairs - and every other room
  stands in the front or back band with a door straight onto it. Nobody walks
  down a passage, and nobody walks through a bedroom;
* the hall reaches both ends of the plate, so every room in it has windows;
  every room in the outer bands has the outside wall behind it;
* a bedroom's bath and dressing room stand beside it, entered from it; the
  kitchen has its wash area and store beside it, on the outside wall;
* the **stair** is at one end of a band, in the same place on every floor, with
  the common bath or a store behind it;
* rooms are placed for **Vastu**: each arrangement is scored by the zone each
  room falls in (kitchen south-east, master south-west, puja north-east, the
  stair south or west, the centre kept to the living room), and the best are
  offered;
* what the rooms cannot fill at their largest sensible size goes to the rooms
  a house that size has (a study, a gym, a library, a theatre), and upstairs to
  a terrace on the north-east, which Vastu wants kept light.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from aip.domain.geometry import BoundingBox, Direction
from aip.domain.plan import Room, RoomType
from aip.engines.architecture.corridor import MINA, MINW
from aip.engines.architecture.programme import is_through, may_enter
from aip.engines.architecture.spine import SpinePlanner, _items

T = RoomType
BEDS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM}
BATHS = {T.BATHROOM, T.TOILET, T.POWDER}
HALL = {T.LIVING, T.DINING, T.FAMILY, T.DRAWING}
SKIP = {T.CORRIDOR, T.LOBBY, T.SHAFT}
GROWS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM, T.LIVING, T.DINING, T.FAMILY,
         T.DRAWING, T.KITCHEN, T.STUDY, T.HOME_OFFICE, T.LIBRARY, T.GYM, T.HOME_THEATRE, T.FOYER,
         T.TERRACE, T.VERANDAH, T.BALCONY}
#: Aspect each kind may take before the judge calls it a slot.
ASPECT = {T.MASTER_BEDROOM: 1.65, T.BEDROOM: 1.65, T.GUEST_BEDROOM: 1.65, T.CHILDREN_BEDROOM: 1.65,
          T.DINING: 1.95, T.LIVING: 2.15, T.DRAWING: 2.15, T.FAMILY: 2.15, T.KITCHEN: 2.3}
#: Rooms added, in order, when the rooms asked for cannot fill a floor.
UPPER_EXTRAS = ((T.HOME_THEATRE, 22.0, "Home theatre"), (T.FAMILY, 20.0, "Play room"), (T.LIBRARY, 16.0, "Library"),
                (T.OTHER, 16.0, "Hobby room"), (T.GYM, 18.0, "Gym"), (T.HOME_OFFICE, 14.0, "Home office"),
                (T.DRAWING, 18.0, "Sitting room"), (T.OTHER, 16.0, "Music room"), (T.FAMILY, 20.0, "Guest lounge"),
                (T.OTHER, 14.0, "Art room"), (T.OTHER, 14.0, "Yoga room"), (T.OTHER, 18.0, "Games room"),
                (T.OTHER, 14.0, "Home spa"), (T.OTHER, 14.0, "Reading room"), (T.OTHER, 14.0, "Craft room"))
GROUND_EXTRAS = ((T.STUDY, 14.0, "Study"), (T.FAMILY, 24.0, "Family lounge"), (T.HOME_OFFICE, 14.0, "Home office"),
                 (T.GYM, 18.0, "Gym"), (T.DRAWING, 18.0, "Sitting room"), (T.HOME_THEATRE, 22.0, "Home theatre"),
                 (T.OTHER, 16.0, "Music room"), (T.FAMILY, 20.0, "Play room"), (T.LIBRARY, 16.0, "Library"))
FILLER = "Added to fill a generous plot."
STAIR_W = 2.7
STAIR_L = 4.6

#: Vastu: the zones each room is drawn toward, the zones it must not take, and how much it matters.
VASTU = {
    # The same zones the Vastu engine judges by (aip.engines.vastu.knowledge), read on its 3 x 3 grid.
    T.KITCHEN: ({"SE"}, {"SW", "N", "NE"}, 1.4),
    T.MASTER_BEDROOM: ({"SW"}, {"SE", "NE"}, 1.3),
    T.BEDROOM: ({"S", "W", "SW", "NW"}, {"NE"}, 0.6),
    T.CHILDREN_BEDROOM: ({"W", "NW"}, {"NE"}, 0.4),
    T.GUEST_BEDROOM: ({"NW"}, {"NE"}, 0.35),
    T.PUJA: ({"NE"}, {"S", "SW"}, 1.4),
    T.TOILET: ({"NW", "W"}, {"NE", "E", "CENTRE"}, 0.8),
    T.BATHROOM: ({"N", "E"}, {"SE", "NE", "CENTRE"}, 0.5),
    T.STAIRCASE: ({"S", "W", "SW"}, {"NE", "CENTRE"}, 0.8),
    T.LIVING: ({"N", "E", "NE"}, {"SW"}, 0.65),
    T.DINING: ({"W", "E"}, set(), 0.4),
    T.STORE: ({"S", "SW"}, {"NE"}, 0.5),
    T.UTILITY: ({"NW", "W"}, {"NE"}, 0.4),
    T.STUDY: ({"E", "N", "NE"}, {"SW"}, 0.45),
    T.TERRACE: ({"NE", "N", "E"}, {"SW"}, 0.4),
    T.BALCONY: ({"NE", "N", "E"}, set(), 0.4),
    T.VERANDAH: ({"NE", "N", "E"}, {"SW"}, 0.45),
    T.GUEST_BEDROOM: ({"NW"}, {"NE"}, 0.35),
}


def _engine_rules() -> dict:
    """The Vastu engine's placement rule for each kind of room (its zones and how it grades them)."""
    from aip.engines.vastu.knowledge import RULES

    out = {}
    for r in RULES:
        if r.subject is not None and r.ideal and r.subject not in out:
            out[r.subject] = r
    return out


_RULES = _engine_rules()


@dataclass(slots=True)
class Piece:
    type: RoomType
    area: float
    req: object | None = None
    name: str | None = None
    brief: float = 0.0
    host: Piece | None = None          # the bedroom a bath or dressing room belongs to
    common: bool = False
    extra: bool = False                # added to fill the plot

    @property
    def minw(self) -> float:
        if self.type is T.STAIRCASE:
            return STAIR_W
        return max(MINW.get(self.type, 1.5), 2.4 if self.type.is_habitable else 0.0)

    @property
    def mina(self) -> float:
        return MINA.get(self.type, 3.0)


@dataclass(slots=True)
class Column:
    """One column of a band: a room the depth of the band, or two, one behind the other
    (the first touches the hall)."""
    pieces: list[Piece]
    split: float = 0.5               # share of the band's depth the inner piece takes
    w: float = 0.0
    fixed_w: float | None = None
    tag: str = ""
    grp: int = -1                    # columns of one group (a suite, the kitchen) stay side by side


@dataclass(slots=True)
class Floor:
    hall: list[Piece]
    groups: list[list[Column]]       # each kept together, in order
    stair: Column | None = None
    rooms: list[Room] = field(default_factory=list)


class HallPlanner(SpinePlanner):
    """Plans that fill a generous plate, every room off a hall."""

    def __init__(self, box: BoundingBox, road: Direction | None, stair_on: bool, *, plate: float,
                 cap: Callable[[RoomType], float | None], north_angle: float = 0.0, elders: bool = False,
                 seed: int = 0, side: int = 0, far: float = 0.0, centre: tuple[float, float] | None = None) -> None:
        super().__init__(box, road, stair_on, side=side)
        self.plate = plate
        self.far = far
        # Vastu reads every direction from the centre of the plot: the house is centred on it.
        self.centre = centre or ((box.min_x + box.max_x) / 2, (box.min_y + box.max_y) / 2)
        self.cap = cap
        self.north = north_angle
        self.elders = elders
        self.seed = seed
        self.why: dict[str, int] = {}

    # ----------------------------------------------------------------- api --

    def plans(self, levels: list[list], count: int = 6, tries: int = 260) -> list[list[list[Room]]]:
        floors = self._programme(levels)
        if floors is None:
            return []
        found: list[tuple[float, list[list[Room]]]] = []
        for transverse in (False, True):
            for stair_end in (0, 1):
                for depth_pick in (0, 1):
                    rng = random.Random(self.seed * 7 + transverse * 3 + stair_end * 11 + depth_pick * 5)
                    shape = self._shape(transverse, depth_pick, floors)
                    if shape is None:
                        continue
                    for _ in range(3):
                        got = self._build(floors, shape, stair_end, rng, tries)
                        if got is not None:
                            found.append(got)
        found.sort(key=lambda x: -x[0])
        out, seen = [], set()
        for score, rooms in found:
            sig = tuple(sorted((r.type.value, round(r.centre.x), round(r.centre.y)) for lv in rooms for r in lv))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(rooms)
            if len(out) >= count:
                break
        return out

    # ----------------------------------------------------------- programme --

    def _programme(self, levels: list[list]) -> list[list] | None:
        """Each floor's pieces, with a bedroom's bath beside it and a hall on every floor."""
        reqs = [[r for r in lv if r.type not in SKIP and not (r.notes == FILLER and r.type in (T.COURTYARD, T.VERANDAH))
                 and "fills the footprint" not in (r.notes or "")] for lv in levels]
        if not reqs or not reqs[0]:
            return None
        # An elder sleeps downstairs: the smallest bedroom upstairs comes down with its bath.
        if self.elders and len(reqs) > 1 and not any(r.type in BEDS for r in reqs[0]):
            # From the floor with the most bedroom on it, so the floors above stay about as full.
            for lv in sorted(reqs[1:], key=lambda l: -sum(r.target_area for r in l if r.type in BEDS)):
                beds = sorted([r for r in lv if r.type in (T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM)],
                              key=lambda r: r.target_area)
                if beds:
                    lv.remove(beds[0])
                    reqs[0].append(beds[0])
                    if not any(r.type in BATHS for r in reqs[0]):
                        bath = next((r for r in lv if r.type is T.BATHROOM), None)
                        if bath is not None:
                            lv.remove(bath)
                            reqs[0].append(bath)
                    break
        # Every bedroom keeps its own bath where the client asked for as many: a bath left
        # on a floor with more baths than bedrooms goes to a floor with fewer.
        def n(lv, kinds):
            return sum(1 for r in lv if r.type in kinds)
        for _ in range(4):
            short = [lv for lv in reqs if n(lv, BEDS) > n(lv, {T.BATHROOM})]
            spare = [lv for lv in reqs if n(lv, {T.BATHROOM}) > n(lv, BEDS) and (lv is not reqs[0] or n(lv, BEDS))]
            if not short or not spare:
                break
            bath = next(r for r in spare[0] if r.type is T.BATHROOM)
            spare[0].remove(bath)
            short[0].append(bath)
        out = []
        for li, lv in enumerate(reqs):
            items = _items(lv)
            pieces: list[Piece] = []
            for it in items:
                p = self._piece(it.type, it.area, it.req)
                pieces.append(p)
                if it.bath is not None:
                    b = self._piece(it.bath.type, it.bath.area, it.bath.req)
                    b.host = p
                    pieces.append(b)
            # A bath nobody's bedroom claimed is everyone's.
            for p in pieces:
                if p.type in BATHS and p.host is None:
                    p.common = True
            if li > 0 and not any(p.type in HALL for p in pieces):
                pieces.append(Piece(T.FAMILY, 22.0, None, "Upper lounge", 0.0))
            if li == 0 and not any(p.type in (T.LIVING, T.DRAWING) for p in pieces):
                return None
            out.append(pieces)
        return out

    def _piece(self, t: RoomType, area: float, req) -> Piece:
        # Measured against the room as the plot's growth sized it (see `_grow_programme`):
        # on a generous plot that is the room the client is being offered.
        brief = float(getattr(req, "target_area", None) or getattr(req, "asked_area", None) or area)
        return Piece(t, float(area), req, getattr(req, "label", None), brief)

    def _max_area(self, p: Piece, plate: float) -> float:
        cap = self.cap(p.type)
        top = 0.27 * plate
        if p.brief and p.req is not None:
            top = min(top, 1.55 * p.brief)
        if cap is not None:
            top = min(top, 1.07 * cap)
        if p.type in (T.TERRACE, T.VERANDAH, T.BALCONY):
            top = 0.35 * plate
        return max(top, p.mina)

    # --------------------------------------------------------------- shape --

    def _shape(self, transverse: bool, pick: int, floors) -> dict | None:
        """The plate: its length along the bands (L) and depth across them (S), and the bands."""
        W, D = self.W, self.D
        # In the transverse shape the bands run back from the road, so the road is an end of every band.
        long_side, cross_side = (D, W) if transverse else (W, D)
        target = min(self.plate, W * D)
        # The hall is never a passage: deep enough to furnish, and its rooms not slots.
        best = None
        for S in [x * 0.25 for x in range(52, 86)]:          # 13 .. 21.25 m across the bands
            if S > cross_side + 1e-6:
                break
            L = min(long_side, target / S)
            if L < 9.0:
                continue
            dM = min(6.0, max(4.8, L / 4.6))
            rest = S - dM
            if rest < 2 * 4.2 or rest > 2 * 7.2:
                continue
            fill = L * S / target
            cand = (abs(1.0 - fill) + 0.02 * abs(rest / 2 - 5.6) + (0.1 if pick and S < 15 else 0.0), L, S, dM)
            if best is None or cand < best:
                best = cand
        if best is None:
            self.why["shape"] = self.why.get("shape", 0) + 1
            return None
        _, L, S, dM = best
        L = math.floor(L * 4) / 4
        dF = round((S - dM) / 2 * 4) / 4
        dB = S - dM - dF
        # The plate's place: centred on the plot's centre, inside the setbacks.
        uc, vc = self._to_uv(*self.centre)
        Wu, Dv = (L, S) if not transverse else (S, L)
        u0 = min(max(0.0, uc - Wu / 2), W - Wu)
        v1 = max(min(D, vc + Dv / 2), Dv)
        return {"tr": transverse, "L": L, "S": S, "dM": dM, "dF": dF, "dB": dB, "u0": u0, "v1": v1}

    def _to_uv(self, x: float, y: float) -> tuple[float, float]:
        """Plan coordinates back to the planner's (u, v)."""
        def c(u, v):
            pts = self._poly(u, v, u + 1.0, v + 1.0)
            return sum(q.x for q in pts) / len(pts), sum(q.y for q in pts) / len(pts)
        o, eu, ev = c(0.0, 0.0), c(1.0, 0.0), c(0.0, 1.0)
        au, bu = eu[0] - o[0], eu[1] - o[1]
        av, bv = ev[0] - o[0], ev[1] - o[1]
        det = au * bv - av * bu
        dx, dy = x - o[0], y - o[1]
        u = (dx * bv - av * dy) / det
        v = (au * dy - dx * bu) / det
        return u + 0.5, v + 0.5

    # --------------------------------------------------------------- build --

    def _build(self, floors, shape, stair_end, rng, tries) -> tuple[float, list[list[Room]]] | None:
        L, S = shape["L"], shape["S"]
        plate_area = L * S
        multi = len(floors) > 1 and self.stair_on
        stair_band = rng.choice((0, 2))
        total = 0.0
        levels_out: list[list[Room]] = []
        below: list[Room] = []
        self._span = (0.0, L)
        self._box = None
        self._extras: set[str] = set()          # rooms added to fill, once in the house each
        ups = len(floors) - 1
        self._quota = {li: max(1, math.ceil(len(UPPER_EXTRAS) / max(1, ups)) // 2 + 1) for li in range(1, len(floors))}
        for li, pieces in enumerate(floors):
            best = None
            for _ in range(tries):
                lay = self._arrange(li, pieces, shape, stair_band if multi else None, stair_end, rng, plate_area)
                if lay is None:
                    continue
                rooms, score, span = lay
                score -= self._stack_penalty(rooms, below)
                if best is None or score > best[0]:
                    best = (score, rooms, span)
            if best is None:
                self.why[f"level{li}"] = self.why.get(f"level{li}", 0) + 1
                return None
            total += best[0]
            levels_out.append(best[1])
            self._extras |= {r.name for r in best[1] if r.metadata.get("extra")}
            below = best[1]
            if li == 0:
                # The floors above stand over the living and dining rooms; the courtyard stays open to the sky.
                self._span = best[2]
                xs = [q.x for r in best[1] for q in r.polygon]
                ys = [q.y for r in best[1] for q in r.polygon]
                self._box = (min(xs), min(ys), max(xs), max(ys))
        # The FAR counts every floor's built area (courtyards, terraces and verandahs are open).
        built = sum(r.area for lv in levels_out for r in lv if not r.type.is_outdoor)
        if self.far and built > self.far:
            self.why["far"] = self.why.get("far", 0) + 1
            return None
        return total, levels_out

    def _stack_penalty(self, rooms: list[Room], below: list[Room]) -> float:
        bad = 0.0
        for r in rooms:
            if r.type not in BATHS:
                continue
            for b in below:
                if b.type in (T.KITCHEN, T.PUJA, T.DINING) and _overlap(r, b) > 0.3 * r.area:
                    bad += 3.0
        return bad

    def _arrange(self, li, pieces, shape, stair_band, stair_end, rng, plate_area):
        """One arrangement of a floor: groups into bands, widths, rooms, and its Vastu score."""
        L, dM, dF, dB = shape["L"], shape["dM"], shape["dF"], shape["dB"]
        tr = shape["tr"]
        a0, a1 = (0.0, L) if li == 0 else self._span
        span = a1 - a0
        pcs = list(pieces)
        up_span = (0.0, L)
        if li == 0:
            living = next((p for p in pcs if p.type is T.LIVING), None) or next((p for p in pcs if p.type is T.DRAWING), None)
            dining = next((p for p in pcs if p.type is T.DINING), None)
            if living is None:
                return None
            pcs.remove(living)
            if dining is not None:
                pcs.remove(dining)
            # Each at its largest sensible size and shape; past that the hall opens into a
            # courtyard, open to the sky, at the end away from the stair.
            ll = min(1.05 * (self.cap(living.type) or 1e9), 1.55 * living.brief) / dM
            ll = min(ll, 2.1 * dM)
            dl = (min(min(1.05 * (self.cap(T.DINING) or 1e9), 1.55 * dining.brief) / dM, 1.9 * dM, 0.8 * ll)
                  if dining is not None else 0.0)
            court = L - ll - dl
            if court < 3.5:
                f = L / (ll + dl)
                ll, dl, court = ll * f, dl * f, 0.0
            ll *= 0.9 + 0.2 * rng.random() if court else 1.0
            court = L - ll - dl
            living.area, hall = ll * dM, [living]
            if dining is not None:
                dining.area = dl * dM
                hall.append(dining)
                if rng.random() < 0.5:
                    hall.reverse()
            if court > 1e-6:
                yard = Piece(T.COURTYARD, court * dM, None, "Courtyard", 0.0)
                court_last = (stair_end == 0) if not tr else False
                if court_last:
                    hall.append(yard)
                    up_span = (0.0, L - court)
                else:
                    hall.insert(0, yard)
                    up_span = (court, L)
        else:
            hall = [p for p in pcs if p.type is T.FAMILY][:1]
            if not hall:
                return None
            pcs.remove(hall[0])
            # A second lounge where one would be too large or too long to be a room.
            if span * dM > 1.08 * (self.cap(T.FAMILY) or 1e9) or span / dM > ASPECT[T.FAMILY]:
                hall.append(Piece(T.FAMILY, 20.0, None, "Lounge", 0.0))
                if rng.random() < 0.5:
                    hall.reverse()
            self._hall_lengths(hall, span, dM, plate_area)

        groups: list[list[Column]] = []
        used: set[int] = set()

        def take(p):
            used.add(id(p))
            return p

        # Bedroom suites: the bedroom, then its dressing room and bath one behind the other.
        for p in [p for p in pcs if p.type in BEDS]:
            bath = next((b for b in pcs if b.host is p), None)
            ward = next((w for w in pcs if w.type is T.WARDROBE and id(w) not in used), None)
            group = [Column([take(p)])]
            if bath is not None:
                # The bath beside its bedroom, the depth of the band, on the outside wall.
                # (A dressing room as well would be the bedroom's third door.)
                if ward is not None and "Requested" in (getattr(ward.req, "notes", "") or ""):
                    ward.host = p
                    group.append(Column([take(ward), take(bath)], split=0.45))
                else:
                    group.append(Column([take(bath)], tag="bath"))
            groups.append(group)
        # The kitchen, with its wash area on the outside wall and a store between.
        kit = next((p for p in pcs if p.type is T.KITCHEN), None)
        if kit is not None:
            serv = [p for p in pcs if p.type in (T.UTILITY, T.PANTRY, T.LAUNDRY) and id(p) not in used]
            store = next((p for p in pcs if p.type is T.STORE and id(p) not in used), None)
            group = [Column([take(kit)], tag="kitchen")]
            if serv:
                inner = take(store) if store is not None else Piece(T.PANTRY if T.PANTRY not in {s.type for s in serv} else T.STORE,
                                                                    3.5, None, "Pantry", 0.0)
                group.append(Column([inner, take(serv[0])], split=0.4))
                for s in serv[1:]:
                    group.append(Column([take(s)]))
            groups.append(group)
        # The entrance: the foyer the depth of the band, the shrine beside it.
        foyer = next((p for p in pcs if p.type is T.FOYER), None)
        entry: list[Column] | None = None
        if li == 0:
            if foyer is None:
                foyer = Piece(T.FOYER, 8.0, None, "Foyer", 0.0)
            else:
                take(foyer)
            entry = [Column([foyer], tag="foyer")]
            for pj in [p for p in pcs if p.type is T.PUJA]:
                st = next((p for p in pcs if p.type is T.STORE and id(p) not in used), None)
                entry.append(Column([take(pj), take(st) if st is not None else Piece(T.STORE, 2.5, None, "Shoe store", 0.0)],
                                    split=0.6))
            groups.append(entry)
        # The stair, the same everywhere, with the common bath (or a store) behind it.
        stair_col = None
        common = [p for p in pcs if p.type in BATHS and p.common and id(p) not in used]
        if stair_band is not None:
            stair = next((p for p in pcs if p.type is T.STAIRCASE), None)
            if stair is None:
                stair = Piece(T.STAIRCASE, STAIR_W * STAIR_L, None, "Staircase", 0.0)
            else:
                take(stair)
            band_d = dF if stair_band == 0 else dB
            behind = None
            if band_d - STAIR_L >= 1.5:
                behind = take(common.pop(0)) if common else Piece(T.STORE, 3.0, None, "Store", 0.0)
            stair_col = Column([stair] + ([behind] if behind else []), split=min(1.0, STAIR_L / band_d), fixed_w=STAIR_W, tag="stair")
        # What is left: each its own column the depth of a band (a common bath with a store behind it).
        for p in pcs:
            if id(p) in used or p.type is T.WARDROBE:
                continue
            if p.type in BATHS:
                st = next((q for q in pcs if q.type is T.STORE and id(q) not in used and q is not p), None)
                groups.append([Column([take(p), take(st) if st is not None else Piece(T.STORE, 2.5, None, "Linen store", 0.0)],
                                      split=0.6)])
            elif p.type is T.STAIRCASE:
                continue
            else:
                groups.append([Column([take(p)])])

        # Into the bands: random, the entrance on the road.
        bands: list[list[list[Column]]] = [[], []]       # front (index 0 = F), back (1 = B)
        depth = (dF, dB)

        def need(g, k):
            return sum(max(sum(p.area for p in c.pieces) / depth[k], max(p.minw for p in c.pieces))
                       if c.fixed_w is None else c.fixed_w for c in g)

        load = [0.0, 0.0]
        if stair_col is not None:
            load[0 if stair_band == 0 else 1] += STAIR_W
        # Each group is aimed at the zone Vastu gives its main room (the kitchen at the
        # south-east corner, the master at the south-west...), then varied: the bands
        # come out about as full, so neither is all terrace.
        def want(g):
            """(band, place along it 0..1) the group's main room is best at, with how much it cares."""
            key = max((p for c in g for p in c.pieces if p.type in VASTU),
                      key=lambda p: VASTU[p.type][2], default=None)
            if key is None:
                return None
            w = VASTU[key.type][2]
            rule = _RULES.get(key.type)
            best = None
            for k in (0, 1):
                for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                    x, y = self._point_at(k, a0 + t * span, shape)
                    c = rule.compliance_for(self._direction(x, y, self._plate_box(shape))) if rule else 0.5
                    v = w * (2 * c - 1) + 0.05 * rng.random()
                    if best is None or v > best[0]:
                        best = (v, k, t)
            return best

        aims = {id(g): want(g) for g in groups}
        order = sorted(groups, key=lambda g: -((aims[id(g)] or (0,))[0] if aims[id(g)] else 0.0) - 0.3 * rng.random())
        place: dict[int, float] = {}
        for g in order:
            aim = aims[id(g)]
            if g is entry and not tr:
                k = 0
            elif aim is not None and aim[0] > 0 and rng.random() < 0.8 and load[aim[1]] + need(g, aim[1]) <= span:
                k = aim[1]
            else:
                k = 0 if load[0] <= load[1] else 1
                if rng.random() < 0.2:
                    k = 1 - k
            bands[k].append(g)
            load[k] += need(g, k)
            place[id(g)] = (aim[2] if aim is not None and aim[0] > 0 and rng.random() < 0.8 else rng.random())
        if max(load) > span + 1e-6:
            return None
        for b in bands:
            b.sort(key=lambda g: place[id(g)] + 0.15 * rng.gauss(0, 1))
            for g in b:
                if rng.random() < 0.5:
                    g.reverse()
        if entry is not None and tr:
            # The road is the a = 0 end of every band: the entrance group first in its band.
            for b in bands:
                if entry in b:
                    b.remove(entry)
                    b.insert(0, entry)
                    if entry[0].tag != "foyer":
                        entry.reverse()
        for gi, g in enumerate(groups):
            for c in g:
                c.grp = gi
        cols = [[c for g in b for c in g] for b in bands]
        if stair_col is not None:
            k = 0 if stair_band == 0 else 1
            if stair_end == 0 and not tr:
                cols[k].insert(0, stair_col)
            else:
                cols[k].append(stair_col)

        # Widths: each band filled end to end; a room added to fill one band is not added again.
        have: set[RoomType] = {p.type for p in pcs} | {p.type for p in hall}
        for k in (0, 1):
            if not self._widths(cols[k], depth[k], span, plate_area, li, rng, have):
                return None
        rooms = self._rooms(li, hall, cols, shape, a0, a1)
        if rooms is None:
            return None
        score = self._score(li, rooms, hall, cols, shape)
        if score is None:
            return None
        return rooms, score, up_span

    def _widths(self, cols: list[Column], d: float, L: float, plate: float, li: int, rng,
                have: set[RoomType]) -> bool:
        lo, hi, nat = [], [], []
        for c in cols:
            if c.fixed_w is not None:
                lo.append(c.fixed_w); hi.append(c.fixed_w); nat.append(c.fixed_w)
                continue
            if len(c.pieces) == 1:
                p = c.pieces[0]
                asp = ASPECT.get(p.type)
                mn = max(p.minw, p.mina / d, d / asp if asp else 0.0)
                if p.type in BATHS:
                    mn = max(mn, d / 2.9)
                mx = self._max_area(p, plate) / d if p.type in GROWS else max(mn, p.area * 1.15 / d)
                if asp:
                    mx = min(mx, d * asp)
                lo.append(mn); hi.append(max(mn, mx)); nat.append(min(max(mn, p.area / d), max(mn, mx)))
            else:
                a, b = c.pieces
                mn = max(a.minw, b.minw, 1.5)
                mx = max(mn, (a.area + b.area) * 1.35 / d, 2.6)
                if a.type is T.WARDROBE:
                    mx = max(mn, min(3.2, mx))
                lo.append(mn); hi.append(mx); nat.append(min(mx, max(mn, (a.area + b.area) / d)))
        need = sum(lo)
        if need > L + 1e-6:
            return False
        w = list(nat)
        tot = sum(w)
        if tot > L:
            # Shrink toward the least each can be.
            f = (L - need) / max(tot - need, 1e-6)
            w = [l_ + (n - l_) * f for l_, n in zip(lo, nat)]
        else:
            spare = L - tot
            for _ in range(6):
                room = [h - x for h, x in zip(hi, w)]
                free = sum(r for r in room if r > 1e-6)
                if spare <= 1e-6 or free <= 1e-6:
                    break
                for i, r in enumerate(room):
                    if r > 1e-6:
                        add = min(r, spare * r / free)
                        w[i] += add
                spare = L - sum(w)
            if spare > 0.3:
                # Rooms a house this size holds, then a terrace (upstairs) or a sit-out (on the ground).
                extras = list(UPPER_EXTRAS if li > 0 else GROUND_EXTRAS)
                have |= {p.type for c in cols for p in c.pieces}
                have |= {p.name for c in cols for p in c.pieces}        # names, shared by both bands of the floor
                names = have
                while spare > 0.3:
                    # Each added room once in the house; the upper floors share what is left.
                    nxt = next((e for e in extras if e[2] not in self._extras and e[2] not in names
                                and (li == 0 or self._quota.get(li, 9) > sum(1 for c in cols for q in c.pieces if q.extra))), None)
                    if nxt is not None and spare >= 3.0:
                        t, area, name = nxt
                        have.add(t)
                        names.add(name)
                        p = Piece(t, area, None, name, 0.0, extra=True)
                        asp = ASPECT.get(t, 2.2)
                        mn = max(p.minw, d / asp)
                        if spare < mn:
                            extras.remove(nxt)
                            continue
                        width = min(spare, d * asp, max(mn, 1.6 * area / d))
                        if spare - width < 1.5 and spare - width > 1e-6:
                            width = spare           # nothing too thin left over
                    else:
                        t = T.TERRACE if li > 0 else T.VERANDAH
                        p = Piece(t, 0.0, None, "Terrace" if li > 0 else "Verandah", 0.0)
                        width = spare
                    c = Column([p])
                    # Between groups only (never between a bedroom and its bath), and never
                    # past the stair, which keeps its end of the band on every floor.
                    stair_at = next((i for i, c in enumerate(cols) if c.tag == "stair"), None)
                    slots = [i for i in range(len(cols) + 1)
                             if (i == 0 or i == len(cols) or cols[i - 1].grp != cols[i].grp or cols[i].grp < 0)
                             and not (stair_at is not None and stair_at == 0 and i == 0)
                             and not (stair_at is not None and stair_at == len(cols) - 1 and i == len(cols))]
                    if not slots:
                        return False
                    pos = rng.choice(slots)
                    cols.insert(pos, c)
                    w.insert(pos, width)
                    spare -= width
                    if t in (T.TERRACE, T.VERANDAH):
                        break
        # Stair columns keep their place at the end of the band they were put at.
        for c, x in zip(cols, w):
            c.w = round(x, 3)
        # Snap so the band closes exactly.
        drift = L - sum(c.w for c in cols)
        flex = max((c for c in cols if c.fixed_w is None), key=lambda c: c.w, default=None)
        if flex is None:
            return abs(drift) < 0.05
        flex.w += drift
        return all(c.w >= 1.2 for c in cols)

    def _hall_lengths(self, hall: list[Piece], L: float, dM: float, plate: float) -> bool:
        if len(hall) == 1:
            hall[0].area = L * dM
            return True
        living = next((p for p in hall if p.type in (T.LIVING, T.FAMILY)), hall[0])
        share = 0.56 if living.type is T.LIVING else 0.5
        for p in hall:
            p.area = (share if p is living else 1 - share) * L * dM
        return True

    def _rooms(self, li: int, hall: list[Piece], cols: list[list[Column]], shape, a_lo: float, a_hi: float) -> list[Room] | None:
        L, dM, dF, dB, S = shape["L"], shape["dM"], shape["dF"], shape["dB"], shape["S"]
        tr = shape["tr"]
        rooms: list[Room] = []
        made: dict[int, Room] = {}

        def add(p: Piece, a0, b0, a1, b1):
            if a1 - a0 < 0.9 or b1 - b0 < 0.9:
                return None
            u0, v0, u1, v1 = self._uv(a0, b0, a1, b1, shape)
            area = round((a1 - a0) * (b1 - b0), 2)
            room = Room(name=p.name or p.type.label, type=p.type, polygon=self._poly(u0, v0, u1, v1), level=li,
                        ceiling_height=3.0,
                        metadata={"notes": getattr(p.req, "notes", "") or (FILLER if p.extra else ""), "extra": p.extra,
                                  "target_area": getattr(p.req, "target_area", None) or area,
                                  "brief_area": p.brief if (p.req is not None and p.brief) else area,
                                  "planner": "hall"})
            rooms.append(room)
            made[id(p)] = room
            return room

        # The hall: the middle band.
        a = a_lo
        for i, p in enumerate(hall):
            length = p.area / dM
            add(p, a, dF, a_hi if i == len(hall) - 1 else min(a_hi, a + length), dF + dM)
            a += length
        # The front band (b from 0 at its outer face to dF at the hall) and the back band.
        for k, (b_out, b_in) in enumerate(((0.0, dF), (S, dF + dM))):
            d = abs(b_in - b_out)
            a = a_lo
            for i, c in enumerate(cols[k]):
                a1 = a_hi if i == len(cols[k]) - 1 else min(a_hi, a + c.w)
                if len(c.pieces) == 1:
                    add(c.pieces[0], a, min(b_out, b_in), a1, max(b_out, b_in))
                else:
                    inner, outer = c.pieces
                    di = max(1.2, min(d - 1.2, d * c.split))
                    if inner.type is T.STAIRCASE:
                        di = min(d, STAIR_L)
                    if k == 0:
                        add(inner, a, b_in - di, a1, b_in)
                        add(outer, a, 0.0, a1, b_in - di)
                    else:
                        add(inner, a, b_in, a1, b_in + di)
                        add(outer, a, b_in + di, a1, S)
                a = a1
        # Who belongs to whom.
        for k in (0, 1):
            for c in cols[k]:
                for p in c.pieces:
                    room = made.get(id(p))
                    if room is None:
                        continue
                    if p.host is not None and id(p.host) in made:
                        room.metadata["suite_of"] = made[id(p.host)].id
                    elif p.type in BATHS:
                        room.metadata["common"] = True
        return rooms

    def _uv(self, a0, b0, a1, b1, shape):
        """Plate coordinates (a along the bands, b across them from the road side) to the
        planner's (u along the frontage, v back from the road... v = D at the road)."""
        u0, v1 = shape["u0"], shape["v1"]
        if not shape["tr"]:
            return u0 + a0, v1 - b1, u0 + a1, v1 - b0
        return u0 + b0, v1 - a1, u0 + b1, v1 - a0

    # --------------------------------------------------------------- score --

    def _direction(self, x: float, y: float, box) -> Direction:
        """The compass sector the Vastu engine reads a point in: from the plot's centre."""
        from aip.domain.geometry import Vec2, direction_of

        radius = 0.18 * ((box[2] - box[0]) + (box[3] - box[1])) / 4.0
        return direction_of(Vec2(x, y), Vec2(*self.centre), self.north, centre_radius=radius)

    def _zone_at(self, k: int, a: float, shape) -> str:
        """The Vastu zone at a place along the front (k = 0) or back (k = 1) band of the plate."""
        L, S, dF, dM = shape["L"], shape["S"], shape["dF"], shape["dM"]
        b = dF / 2 if k == 0 else S - (S - dF - dM) / 2
        u0, v0, u1, v1 = self._uv(max(0.0, a - 0.05), b - 0.05, min(L, a + 0.05), b + 0.05, shape)
        pt = self._poly(u0, v0, u1, v1)
        x = sum(q.x for q in pt) / len(pt)
        y = sum(q.y for q in pt) / len(pt)
        c0 = self._poly(*self._uv(0.0, 0.0, L, S, shape))
        box = (min(q.x for q in c0), min(q.y for q in c0), max(q.x for q in c0), max(q.y for q in c0))
        probe = Room(name="", type=T.OTHER, polygon=pt)
        return self._zone(probe, box)

    def _point_at(self, k: int, a: float, shape) -> tuple[float, float]:
        L, S, dF, dM = shape["L"], shape["S"], shape["dF"], shape["dM"]
        b = dF / 2 if k == 0 else S - (S - dF - dM) / 2
        pt = self._poly(*self._uv(max(0.0, a - 0.05), b - 0.05, min(L, a + 0.05), b + 0.05, shape))
        return sum(q.x for q in pt) / len(pt), sum(q.y for q in pt) / len(pt)

    def _plate_box(self, shape) -> tuple[float, float, float, float]:
        c0 = self._poly(*self._uv(0.0, 0.0, shape["L"], shape["S"], shape))
        return (min(q.x for q in c0), min(q.y for q in c0), max(q.x for q in c0), max(q.y for q in c0))


    def _zone(self, room: Room, box: tuple[float, float, float, float]) -> str:
        x0, y0, x1, y1 = box
        c = room.centre
        x, y = c.x, c.y
        if self.north:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            ang = math.radians(self.north)
            dx, dy = x - cx, y - cy
            x, y = cx + dx * math.cos(ang) - dy * math.sin(ang), cy + dx * math.sin(ang) + dy * math.cos(ang)
        col = min(2, max(0, int(3 * (x - x0) / max(x1 - x0, 1e-6))))
        row = min(2, max(0, int(3 * (y1 - y) / max(y1 - y0, 1e-6))))
        return [["NW", "N", "NE"], ["W", "CENTRE", "E"], ["SW", "S", "SE"]][row][col]

    def _score(self, li, rooms: list[Room], hall, cols, shape) -> float | None:
        xs = [p.x for r in rooms for p in r.polygon]
        ys = [p.y for r in rooms for p in r.polygon]
        box = self._box or (min(xs), min(ys), max(xs), max(ys))
        score = 0.0
        by_type: dict[RoomType, list[Room]] = {}
        for r in rooms:
            by_type.setdefault(r.type, []).append(r)
        for r in rooms:
            rule = _RULES.get(r.type)
            if rule is None or r.type not in VASTU:
                continue
            w = VASTU[r.type][2]
            if li > 0 and r.type in (T.KITCHEN, T.PUJA, T.LIVING, T.FOYER):
                w *= 0.3
            c = rule.compliance_for(self._direction(r.centre.x, r.centre.y, box))
            score += w * (2.0 * c - 1.0) * (2.0 if c <= 0.0 else 1.0)
        # The kitchen meets the dining room, and nothing is cut off.
        if li == 0:
            # Brahmasthan: the centre of the house open - the living room or the courtyard, never a heavy room.
            x0, y0, x1, y1 = box
            mid = ((x0 + x1) / 2, (y0 + y1) / 2)
            at = next((r for r in rooms if r.bbox.min_x <= mid[0] <= r.bbox.max_x and r.bbox.min_y <= mid[1] <= r.bbox.max_y), None)
            if at is not None:
                score += 1.2 if at.type in (T.COURTYARD, T.LIVING) else (-3.0 if at.type in BATHS | {T.STAIRCASE, T.STORE} else -0.6)
            kit, din = by_type.get(T.KITCHEN, []), by_type.get(T.DINING, [])
            foy, liv = by_type.get(T.FOYER, []), by_type.get(T.LIVING, [])
            if foy and liv and _shared(foy[0], liv[0]) < 1.0:
                score -= 2.0              # the front door opens into the living room
            for pj in by_type.get(T.PUJA, []):
                if any(_shared(pj, w) > 0.2 for t in BATHS for w in by_type.get(t, [])):
                    score -= 4.0          # never a shrine against a toilet wall
            stair = by_type.get(T.STAIRCASE, [])
            if stair and din and _shared(stair[0], din[0]) > 0.3:
                score -= 3.0              # the stair is not climbed from the dining table
            if kit and din and _shared(kit[0], din[0]) < 1.5:
                liv = by_type.get(T.LIVING, [])
                if not (liv and _shared(kit[0], liv[0]) >= 1.5):
                    return None
                score -= 1.0
        if not self._reachable(li, rooms):
            return None
        # Rooms of sensible proportion.
        for r in rooms:
            bb = r.bbox
            asp = max(bb.width, bb.height) / max(min(bb.width, bb.height), 0.1)
            lim = ASPECT.get(r.type, 3.0 if not r.type.is_outdoor else 6.0)
            if asp > lim + 0.05:
                score -= 1.5 * (asp - lim)
        # Open floor the rooms did not fill is a terrace or a sit-out: a little is welcome
        # (on the north-east, Vastu wants it), a plate of it is a house not built.
        for r in rooms:
            if r.type in (T.TERRACE, T.VERANDAH) and r.area > 24.0:
                score -= 0.06 * (r.area - 24.0)
        # The master is the largest bedroom on its floor.
        masters = by_type.get(T.MASTER_BEDROOM, [])
        others = [r for t in (T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM) for r in by_type.get(t, [])]
        if masters and others and masters[0].area < 1.12 * max(r.area for r in others):
            score -= 2.0
        return score

    def _reachable(self, li: int, rooms: list[Room]) -> bool:
        """Every room has a lawful door from a room the household walks through, and those chain to the way in."""
        n = len(rooms)
        touch = [[_shared(rooms[i], rooms[j]) >= 0.95 for j in range(n)] for i in range(n)]
        root = next((i for i, r in enumerate(rooms) if r.type is (T.FOYER if li == 0 else T.STAIRCASE)), None)
        if root is None:
            root = next((i for i, r in enumerate(rooms) if r.type in HALL), None)
        if root is None:
            return False
        seen = {root}
        stack = [root]
        while stack:
            i = stack.pop()
            if not (is_through(rooms[i].type) or i == root):
                continue
            for j in range(n):
                if j not in seen and touch[i][j] and may_enter(rooms[j].type, rooms[i].type):
                    seen.add(j)
                    stack.append(j)
        # A suite's bath and dressing room come from their bedroom.
        by_id = {r.id: k for k, r in enumerate(rooms)}
        for k, r in enumerate(rooms):
            host = r.metadata.get("suite_of")
            if host in by_id and touch[k][by_id[host]] and by_id[host] in seen:
                seen.add(k)
        # The kitchen's wash area, pantry and store come from the kitchen.
        for k, r in enumerate(rooms):
            if k in seen:
                continue
            if any(touch[k][j] and j in seen and rooms[j].type in (T.KITCHEN, T.UTILITY) for j in range(n)) and \
                    r.type in (T.UTILITY, T.PANTRY, T.STORE, T.LAUNDRY):
                seen.add(k)
        return len(seen) == n


def _shared(a: Room, b: Room) -> float:
    A, B = a.bbox, b.bbox
    tol = 0.02
    if abs(A.max_x - B.min_x) < tol or abs(A.min_x - B.max_x) < tol:
        return max(0.0, min(A.max_y, B.max_y) - max(A.min_y, B.min_y))
    if abs(A.max_y - B.min_y) < tol or abs(A.min_y - B.max_y) < tol:
        return max(0.0, min(A.max_x, B.max_x) - max(A.min_x, B.min_x))
    return 0.0


def _overlap(a: Room, b: Room) -> float:
    A, B = a.bbox, b.bbox
    w = min(A.max_x, B.max_x) - max(A.min_x, B.min_x)
    h = min(A.max_y, B.max_y) - max(A.min_y, B.min_y)
    return max(0.0, w) * max(0.0, h)
