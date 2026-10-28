"""The parti planner: the plan most good Indian houses are drawn on.

An architect does not partition a rectangle; they start from a parti and fit
the programme into it. The one most independent houses share has three bands
from the road to the back of the plot:

* **Front** - the living room (behind a sit-out), the car porch, a drawing room
  or a front bedroom. The house meets the street with the rooms it receives in.
* **Core** - the stair against a side wall, the dining room as the hub every
  room opens off, a short passage to the private rooms, and the wet core:
  bathrooms back to back on a side wall, one serving the room in front, one
  the room behind. Upstairs the dining room becomes the landing lobby.
* **Back** - the kitchen in a corner with the utility behind it, the bedrooms
  with their bathrooms, the study.

Every room touches the core, so nobody walks through one room to reach another
and passages stay a few square metres, not a 15 m corridor. The stair is one
rectangle stacked on every floor; the band lines are the same on every floor,
so walls stand on walls. Bathrooms upstairs sit over bathrooms, not over the
kitchen or the puja.

Within that parti there are many plans: which end the stair takes, where the
kitchen and the porch go, which bedrooms face the street, whether a bath is in
the core or behind its room. Compositions are drawn at random under these
rules, sized to the plot and scored the way an architect reviews a plan:
can every room be reached properly, does every room have a window, is it the
size and shape it should be, did we honour what the client asked for (a room
next to another, a room on a side, a direction), and then Vastu. The best few
distinct plans are returned.

Everything is computed in a canonical frame - the road at the front (high v),
u across the frontage - and turned to the real road at the end.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field

from aip.domain.geometry import BoundingBox, Direction, Vec2, rectangle
from aip.domain.plan import Room, RoomType
from aip.engines.architecture.feasibility import FURNISH_MIN, comfort_cap
from aip.engines.architecture.programme import PRIVATE_HOST, is_through, may_enter

T = RoomType
BEDS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM}
WET = {T.BATHROOM, T.TOILET, T.POWDER}
#: Rooms that live like a bedroom: a door off the passage, a window, a corner of their own.
ROOMISH = BEDS | {T.STUDY, T.HOME_OFFICE, T.LIBRARY, T.GYM, T.HOME_THEATRE, T.SERVANT, T.FAMILY}
SERVICE = {T.UTILITY, T.LAUNDRY, T.PANTRY, T.STORE}
OUTDOOR = {T.BALCONY, T.TERRACE, T.VERANDAH, T.COURTYARD}
#: Rooms that need no door onto the core: entered from outside, or the house's own entrance.
FREE = {T.GARAGE, T.TERRACE, T.BALCONY, T.VERANDAH, T.LIVING, T.DRAWING, T.FOYER, T.COURTYARD}
#: The circulation the planner draws itself; the programme's guesses at it are dropped.
DRAWN = {T.STAIRCASE, T.CORRIDOR, T.LOBBY, T.SHAFT, T.WARDROBE}

#: The shortest side a room can have and still be furnished and used.
MIN_S = {T.MASTER_BEDROOM: 3.3, T.BEDROOM: 3.0, T.GUEST_BEDROOM: 3.0, T.CHILDREN_BEDROOM: 3.0,
         T.LIVING: 3.6, T.DRAWING: 3.3, T.FAMILY: 3.0, T.DINING: 2.8, T.KITCHEN: 2.3,
         T.BATHROOM: 1.5, T.TOILET: 1.2, T.POWDER: 1.1, T.UTILITY: 1.2, T.LAUNDRY: 1.2,
         T.PANTRY: 1.2, T.STORE: 1.25, T.PUJA: 1.2, T.STUDY: 2.4, T.HOME_OFFICE: 2.4,
         T.LIBRARY: 2.6, T.GYM: 2.8, T.HOME_THEATRE: 3.4, T.SERVANT: 2.4, T.GARAGE: 2.9,
         T.VERANDAH: 1.5, T.BALCONY: 1.2, T.TERRACE: 1.5, T.CORRIDOR: 1.1, T.LOBBY: 1.2,
         T.STAIRCASE: 2.4, T.FOYER: 1.5, T.COURTYARD: 2.5}
#: The longest a room may be for its width.
ASPECT = {T.LIVING: 1.8, T.DRAWING: 1.8, T.FAMILY: 1.9, T.DINING: 1.8, T.MASTER_BEDROOM: 1.55,
          T.BEDROOM: 1.6, T.GUEST_BEDROOM: 1.6, T.CHILDREN_BEDROOM: 1.6, T.KITCHEN: 2.2,
          T.STUDY: 2.0, T.HOME_OFFICE: 2.0, T.LIBRARY: 2.0, T.GYM: 2.0, T.HOME_THEATRE: 1.8,
          T.SERVANT: 1.9, T.BATHROOM: 2.3, T.TOILET: 2.4, T.POWDER: 2.4, T.PUJA: 1.9,
          T.GARAGE: 2.3, T.FOYER: 2.4, T.STAIRCASE: 2.2, T.COURTYARD: 2.0}
#: The longest a room should run along its band before it is a corridor with furniture in it.
MAX_W = {T.LIVING: 6.8, T.DRAWING: 6.0, T.FAMILY: 6.0, T.DINING: 5.0, T.KITCHEN: 4.4, T.MASTER_BEDROOM: 5.4,
         T.BEDROOM: 4.8, T.GUEST_BEDROOM: 4.8, T.CHILDREN_BEDROOM: 4.8, T.STUDY: 4.2, T.HOME_OFFICE: 4.2,
         T.BATHROOM: 3.0, T.TOILET: 2.4, T.POWDER: 2.2, T.PUJA: 2.6, T.STORE: 3.0, T.UTILITY: 3.6,
         T.PANTRY: 2.6, T.LAUNDRY: 3.0, T.GARAGE: 3.8}
#: The deepest a room should be drawn in its bay; past it a small room leaves the depth to its neighbour.
MAX_D = {T.BATHROOM: 2.6, T.TOILET: 2.2, T.POWDER: 2.0, T.PUJA: 2.4, T.UTILITY: 2.6, T.PANTRY: 2.4,
         T.MASTER_BEDROOM: 4.8, T.BEDROOM: 4.4, T.GUEST_BEDROOM: 4.4, T.CHILDREN_BEDROOM: 4.4, T.STUDY: 4.0}
#: How much a room's size matters to the client, per square metre of error.
WEIGHT = {T.LIVING: 1.2, T.MASTER_BEDROOM: 1.2, T.BEDROOM: 1.0, T.KITCHEN: 1.0, T.DINING: 0.9}
#: The least a room can be when the plot leaves no choice.
MIN_AREA = {T.LIVING: 14.0, T.DINING: 8.0, T.KITCHEN: 6.5, T.MASTER_BEDROOM: 11.5, T.BEDROOM: 9.5,
            T.GUEST_BEDROOM: 9.5, T.CHILDREN_BEDROOM: 9.5, T.BATHROOM: 3.0, T.TOILET: 1.8,
            T.POWDER: 1.6, T.UTILITY: 2.0, T.PUJA: 1.8, T.STUDY: 6.5, T.GARAGE: 14.5, T.STORE: 1.6}
#: What a bath upstairs must not sit over.
UNDER = {T.KITCHEN: 1.0, T.PUJA: 1.5, T.DINING: 0.8}
#: Penalty per unit of Vastu miss (scaled by the client's tradition weight).
VASTU_PEN = 9.0
STAIR_W, STAIR_RUN = 2.6, 4.0          # a dog-leg for a 3.15 m storey: 2.6 wide, 4.0 long
STAIR_ROT_W, STAIR_ROT_D = 4.2, 2.6    # the same stair turned across the band
PASSAGE = 1.2
CAR_DEPTH = 5.2
#: The largest courtyard and verandah the parti draws, m².
OPEN_MAX = {T.COURTYARD: 64.0, T.VERANDAH: 48.0}


@dataclass(eq=False)
class P:
    """A room to draw."""
    type: RoomType
    area: float
    req: object | None = None
    host: P | None = None          # the room this one serves: a suite's bath, a balcony
    fixed_d: float | None = None   # a strip of fixed depth (balcony, sit-out)
    name: str | None = None
    filler: bool = False
    scale: float = 1.0             # a small plot draws rooms a little under the usual least side

    @property
    def min_s(self) -> float:
        return MIN_S.get(self.type, 1.4) * self.scale


@dataclass(eq=False)
class Cell:
    """One bay of a band: rooms stacked front to back, each slot rooms side by side."""
    slots: list[list[P]]
    fixed_w: float | None = None
    span: str = ""                 # a passage running on into the front ("F") or back ("B") band

    @property
    def area(self) -> float:
        return sum(p.area for s in self.slots for p in s)

    @property
    def min_w(self) -> float:
        return max(sum(p.min_s for p in s) for s in self.slots) if self.slots else 1.0

    @property
    def max_w(self) -> float:
        # A cell is as wide as its least stretchable room allows along the band.
        return min((sum(MAX_W.get(p.type, math.inf) for p in s) for s in self.slots), default=math.inf)

    @property
    def min_d(self) -> float:
        return sum((s[0].fixed_d or max(p.min_s for p in s)) for s in self.slots)

    def pieces(self):
        return [p for s in self.slots for p in s]


class Genes:
    """Every choice a composition makes, by name: a gene the search can change on its own."""

    def __init__(self, rng: random.Random, genes: dict | None = None) -> None:
        self.rng = rng
        self.g = dict(genes or {})
        self.used: set = set()

    def r(self, key) -> float:
        self.used.add(key)
        v = self.g.get(key)
        if v is None:
            v = self.g[key] = self.rng.random()
        return v

    def idx(self, key, n: int) -> int:
        return min(int(self.r(key) * n), max(n - 1, 0))

    def choice(self, key, seq):
        seq = list(seq)
        return seq[self.idx(key, len(seq))]


def _fit(total: float, natural: list[float], mins: list[float], maxs: list[float] | None = None) -> list[float] | None:
    """Share `total` in proportion to `natural`, never below `mins` nor above `maxs`
    (the caps give way, the largest first, when they cannot all hold)."""
    if sum(mins) > total + 1e-6:
        return None
    n = len(natural)
    maxs = list(maxs) if maxs else [math.inf] * n
    if sum(maxs) < total - 1e-6:
        # The big rooms give way first; a bathroom never grows into a hall.
        maxs = [m if m < 4.0 else math.inf for m in maxs]
        if sum(maxs) < total - 1e-6:
            maxs = [math.inf] * n
    fixed = [False] * n
    out = [0.0] * n
    for _ in range(2 * n + 2):
        free = total - sum(out[i] for i in range(n) if fixed[i])
        nat = sum(natural[i] for i in range(n) if not fixed[i]) or 1.0
        changed = False
        for i in range(n):
            if not fixed[i]:
                out[i] = free * natural[i] / nat
        for i in range(n):
            if not fixed[i] and out[i] < mins[i] - 1e-9:
                out[i] = mins[i]
                fixed[i] = True
                changed = True
        if not changed:
            for i in range(n):
                if not fixed[i] and out[i] > maxs[i] + 1e-9:
                    out[i] = maxs[i]
                    fixed[i] = True
                    changed = True
        if not changed:
            break
    return out


class PartiPlanner:
    def __init__(self, envelope: BoundingBox, road: Direction | None, stair_on: bool, *,
                 cover: float = 0.0, side: int = 0, north_angle: float = 0.0,
                 prefer=None, vastu_weight: float = 0.0, elders: bool = False, seed: int = 0,
                 compact_stair: bool = False, landing: str | None = None, boost: float = 1.0) -> None:
        self.env = envelope
        # How far the programme grew its rooms to fill a generous plot: a room
        # grown to its target is not "too big" against what was first asked.
        self.boost = boost
        # Upstairs: "none" - the rooms open off the stair's landing; "lobby" - a
        # small lobby at the head of the stair; None - either, as the search finds.
        self.landing = landing
        r = (road.cardinal if road is not None else Direction.N).value
        self.road = r if r in {"N", "S", "E", "W"} else (r[side] if len(r) == 2 and r[side] in "NSEW" else "N")
        across_x = self.road in {"N", "S"}
        self.W = envelope.width if across_x else envelope.height
        self.D = envelope.height if across_x else envelope.width
        self.stair_on = stair_on
        # A small plot takes a tighter dog-leg: two 0.9 m flights, 3.85 m long.
        self.min_scale = 0.86 if compact_stair else 1.0
        self.st_w, self.st_run, self.st_rot_w, self.st_rot_d = (2.0, 3.85, 3.85, 2.0) if compact_stair else (STAIR_W, STAIR_RUN, STAIR_ROT_W, STAIR_ROT_D)
        self.cover = cover or self.W * self.D
        self.north = north_angle
        self.prefer = prefer or (lambda t: None)
        self.vastu_w = vastu_weight
        self.elders = elders
        self.rng = random.Random(seed)
        self.beds = 3
        self.debug = False
        self.why: dict = {}

    # ------------------------------------------------------------ frames --

    def _poly(self, u0: float, v0: float, u1: float, v1: float):
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

    def _bearing(self, du: float, dv: float) -> float:
        """Compass bearing of a canonical offset (du across, dv toward the road)."""
        # Canonical to plan axes, as `_poly` turns them.
        dx, dy = {"N": (du, dv), "S": (-du, -dv), "E": (dv, -du), "W": (-dv, du)}[self.road]
        return (math.degrees(math.atan2(dx, dy)) - self.north) % 360

    # ------------------------------------------------------------ programme --

    def _pieces(self, reqs: list) -> list[P]:
        out = []
        for r in reqs:
            if r.type in DRAWN:
                continue
            if r.type is T.TERRACE and "fills the footprint" in (r.notes or ""):
                continue
            if r.type is T.FOYER and self.W < 9.0 and "Requested" not in (r.notes or ""):
                continue          # on a narrow plot the living room receives; the hall is not drawn
            area = float(r.target_area)
            if r.type in OPEN_MAX:
                # The courtyard or verandah a generous plot asks for is drawn at
                # the size a house has: at the plot's size it stretches every
                # room round it into a slot.
                area = min(area, OPEN_MAX[r.type])
            out.append(P(r.type, area, r, name=getattr(r, "label", None), scale=self.min_scale))
        return out

    @staticmethod
    def _suites(ps: list[P]) -> None:
        """Pair bathrooms with bedrooms, keeping one common when there are fewer."""
        beds = sorted([p for p in ps if p.type in BEDS], key=lambda p: (p.type is not T.MASTER_BEDROOM, -p.area))
        baths = sorted([p for p in ps if p.type is T.BATHROOM], key=lambda p: -p.area)
        attach = len(baths) - (1 if 0 < len(baths) <= len(beds) and len(beds) > 1 and len(baths) < len(beds) else 0)
        # Beds that asked for their own bath go first.
        beds.sort(key=lambda p: not getattr(p.req, "attached_bathroom", False))
        for bed in beds[:max(0, attach)]:
            b = baths.pop(0)
            b.host = bed
            if bed.req is not None and hasattr(bed.req, "attached_bathroom"):
                bed.req.attached_bathroom = True

    # ------------------------------------------------------------ composing --

    def _compose(self, li: int, ps: list[P], g: dict) -> list[list[Cell]]:
        rng = self.genes
        ix = {id(p): k for k, p in enumerate(ps)}

        def key(*parts) -> str:
            return ".".join(str(x) for x in (li,) + parts)
        ground = li == 0
        low = g["stair_end"] == "L"          # the stair against the low-u side wall
        F: list[Cell] = []
        B: list[Cell] = []
        left = list(ps)

        def take(pred):
            got = [p for p in left if pred(p)]
            for p in got:
                left.remove(p)
            return got

        suite_bath = {id(p.host): p for p in ps if p.type is T.BATHROOM and p.host is not None}
        take(lambda p: p.type is T.BATHROOM and p.host is not None)
        balconies = take(lambda p: p.type is T.BALCONY)
        if ground:
            # A balcony on the ground floor is a sit-out on the garden.
            for b in balconies:
                b.type = T.VERANDAH
        verandah = take(lambda p: p.type is T.VERANDAH) + (balconies if ground else [])
        if ground:
            balconies = []
        garage = take(lambda p: p.type is T.GARAGE)
        living = take(lambda p: p.type in (T.LIVING, T.DRAWING))
        dining = take(lambda p: p.type is T.DINING)
        kitchen = take(lambda p: p.type is T.KITCHEN)
        services = take(lambda p: p.type in SERVICE)
        wets = take(lambda p: p.type in WET)
        puja = take(lambda p: p.type is T.PUJA)
        foyer = take(lambda p: p.type is T.FOYER)
        terraces = take(lambda p: p.type is T.TERRACE)
        courts = take(lambda p: p.type is T.COURTYARD)
        rooms = take(lambda p: True)
        living.sort(key=lambda p: p.type is not T.LIVING)

        def put(band: list, cell: Cell, end: str | None = None) -> None:
            k = key("at", ix.get(id(cell.pieces()[0]), "x") if cell.pieces() else "x")
            """Into a band: at the stair end ("s"), the far end ("f"), or anywhere."""
            if end == "s":
                band.insert(0, cell) if low else band.append(cell)
            elif end == "f":
                band.append(cell) if low else band.insert(0, cell)
            else:
                band.insert(rng.idx(k, len(band) + 1), cell)

        # --- 1 The hub: the dining room downstairs, a landing lobby above.
        hub = None
        dine_back = None
        if ground and dining and kitchen and (g.get("thin") or rng.r(key("dinback")) < 0.1):
            # The row-house order: living in front, the stair and the shrine in
            # the middle off a passage, dining and kitchen together at the back.
            dine_back = Cell([[dining[0]]])
            rooms.extend(dining[1:])
        elif ground and courts and not self.stair_on and rng.r(key("courthub")) < 0.7:
            # A house on one floor round its courtyard: the rooms open onto it,
            # the dining room among them, as the old courtyard houses do.
            hub = Cell([[courts.pop(0)]])
            rooms.extend(dining)
        elif ground and dining:
            hub = Cell([[dining[0]]])
            rooms.extend(dining[1:])
        elif not ground:
            fam = next((r for r in rooms if r.type is T.FAMILY), None)
            if fam is not None and rng.r(key("fam")) < 0.85:
                rooms.remove(fam)
                hub = Cell([[fam]])
            elif self.landing == "lobby" or (self.landing is None and rng.r(key("landing")) < 0.5):
                hub = Cell([[P(T.LOBBY, 0.0, name="Landing")]], fixed_w=g["lobby_w"])
            # Otherwise no lobby at all: the rooms open off the stair's landing.
        private_here = any(r.type in BEDS | {T.SERVANT} for r in rooms) or \
            any(w.type in {T.TOILET, T.BATHROOM} for w in wets)
        passage = None
        # Downstairs the dining hall is the hub every room opens off; a passage
        # is drawn only where there is no hall to open off.
        if ground and (dine_back is not None or (private_here and hub is None)):
            passage = Cell([[P(T.CORRIDOR, 0.0, name="Passage")]], fixed_w=PASSAGE)

        # --- 2 Front or back: the bands balanced by area, the master's side chosen.
        fa = sum(p.area for p in living + garage + foyer)
        ba = sum(p.area for p in kitchen + services)
        where: dict[int, str] = {}
        order = sorted(rooms, key=lambda p: (p.type is not T.MASTER_BEDROOM, -p.area))
        for r in order:
            ra = r.area + (suite_bath[id(r)].area if id(r) in suite_bath else 0.0)
            u = rng.r(key("where", ix[id(r)]))
            if g.get("light") and u < 0.75:
                side = "B"
            elif r.type is T.MASTER_BEDROOM and not ground:
                side = "F" if u < 0.5 else "B"
            elif ground and r.type in BEDS:
                side = "B" if u < 0.8 else "F"
            else:
                lesser = "F" if fa < ba else "B"
                side = lesser if u < 0.8 else ("B" if lesser == "F" else "F")
            where[id(r)] = side
            if side == "F":
                fa += ra
            else:
                ba += ra

        # --- 3 Suites: the bath in the wet core at the far wall, or behind its room.
        core_f = core_b = None
        for r in order:
            if id(r) not in suite_bath:
                continue
            u = rng.r(key("suite", ix[id(r)]))
            if ground and hub is not None and u < 0.8:
                continue            # downstairs the far wall is the dining room's window
            if where[id(r)] == "F" and core_f is None and rng.r(key("suitef", ix[id(r)])) < 0.75:
                core_f = r
            elif where[id(r)] == "B" and core_b is None and rng.r(key("suiteb", ix[id(r)])) < 0.55:
                core_b = r
        commons = list(wets)
        commons.sort(key=lambda w: rng.r(key("wet", ix[id(w)])))
        far = None
        far_kind = None
        side_bath = None
        # On a floor of many rooms one takes the far end of the core, against the side wall.
        spare = [r for r in order if r.type in ROOMISH - {T.MASTER_BEDROOM, T.FAMILY} and r is not core_f and r is not core_b]
        if spare and not (ground and hub is not None) and rng.r(key("farroom")) < (0.6 if len(order) >= 4 else 0.25):
            r = rng.choice(key("farwho"), spare)
            where[id(r)] = "C"
            far, far_kind = Cell([[r]]), "room"
            core_f = core_b = None          # the far wall is taken: suites keep their baths beside them
            if id(r) in suite_bath:
                side_bath = Cell([[suite_bath[id(r)]]])
        elif core_f is not None or core_b is not None:
            fb = suite_bath[id(core_f)] if core_f is not None else (commons.pop(0) if commons else None)
            bb = suite_bath[id(core_b)] if core_b is not None else (commons.pop(0) if commons else None)
            far = Cell([[x] for x in (fb, bb) if x is not None])
            far_kind = "wet"
            if len(far.slots) == 1:
                # One bath alone at the side wall would be a hall: that suite keeps its bath behind it.
                far, far_kind = None, None
                if fb is not None and core_f is None or bb is not None and core_b is None:
                    commons.insert(0, fb or bb)
                core_f = core_b = None
        elif ground and hub is not None and self.stair_on and rng.r(key("farhub")) < 0.85:
            far, far_kind = hub, "hub"

        # --- 4 The core, from the stair outward.
        mid: list[Cell] = []
        if hub is not None and far is not hub:
            mid.append(hub)
        if side_bath is not None:
            mid.append(side_bath)          # the far room's bath beside it
        if passage is not None:
            mid.insert(rng.choice(key("pass"), [0, len(mid)]), passage)
        # The small rooms of the core - common baths, the shrine, a store - in
        # pairs, one behind the other, so none of them is a slot the depth of
        # the band. A shrine never pairs with a toilet. Baths sit beside the
        # passage or the lobby, never off the dining table.
        anchor = passage if passage is not None else hub
        smalls_left: list[P] = []
        foyer_puja = None
        if foyer and puja and rng.r(key("foyerpuja")) < 0.5:
            foyer_puja = puja.pop(0)          # the shrine behind the entrance hall
        shrine_first = []
        for pj in puja:
            if passage is not None and len(passage.slots) == 1 and not passage.span and rng.r(key("puja", ix[id(pj)])) < 0.4:
                passage.slots.insert(0, [pj])          # at the head of the passage, facing the living room
                passage.fixed_w = 1.5
            else:
                shrine_first.append(pj)
        loose = [x for x in services if x.type in (T.STORE, T.PANTRY)] if not kitchen else []
        for x in loose:
            services.remove(x)
        smalls = commons + shrine_first + loose
        commons = []
        smalls.sort(key=lambda x: rng.r(key("small", ix[id(x)])))
        cells = []
        while smalls:
            f = smalls.pop(0)
            mate = next((x for x in smalls if not (T.PUJA in (x.type, f.type) and {x.type, f.type} & WET)), None)
            if mate is not None and rng.r(key("pair", ix[id(f)])) < 0.85:
                smalls.remove(mate)
                cells.append(Cell([[f], [mate]]))
            elif f.type is T.PUJA and not kitchen:
                cells.append(Cell([[f]]))
            elif f.type is T.PUJA or f.type in WET:
                # A shrine or a toilet on its own shares the depth of the band with a small store.
                pair = [[f], [P(T.STORE, 2.5, None, name="Store")]]
                cells.append(Cell(pair if rng.r(key("storeat", ix[id(f)])) < 0.5 or f.type is T.PUJA else pair[::-1]))
            elif anchor is not None and len(anchor.slots) == 1 and anchor.span in ("", "B", "F") \
                    and f.type is not T.PUJA and rng.r(key("solo", ix[id(f)])) < 0.7:
                # A lone toilet or store at the end of the passage or lobby.
                if anchor.span == "F":
                    anchor.slots.append([f])
                else:
                    anchor.slots.insert(0, [f])
                anchor.fixed_w = max(anchor.fixed_w or 0.0, f.min_s + (0.3 if f.type in WET else 0.0))
            else:
                cells.append(Cell([[f]]))
        for cell in cells:
            wet = any(p.type in WET for p in cell.pieces())
            if wet and anchor is not None and anchor in mid:
                k = mid.index(anchor)
                # The same side of the passage or lobby on every floor, so bathrooms stack.
                mid.insert(k + 1 if rng.r("wetat") < 0.5 else k, cell)
            elif wet and far is None and anchor is None:
                far, far_kind = cell, "wet"
            else:
                # Beside the passage, which can serve its store, or the hub.
                at = anchor if (anchor is not None and anchor in mid) else hub
                k = mid.index(at) if at in mid else len(mid)
                mid.insert(min(len(mid), k + rng.choice(key("smallat", ix.get(id(cell.pieces()[0]), "x")), [0, 1])), cell)
        # The kitchen: a back corner under the dining room, or the far end of the core.
        if kitchen:
            k = kitchen[0]
            serv = [x for x in services if x.type in (T.UTILITY, T.LAUNDRY, T.PANTRY, T.STORE)][:2]
            for x in serv:
                services.remove(x)
            if serv and rng.r(key("klay")) < 0.35:
                kc = Cell([[k] + serv[:1]] + ([serv[1:]] if serv[1:] else []))   # the wash area beside the kitchen
            else:
                kc = Cell([[k]] + ([serv] if serv else []))                       # the wash area behind it
            if ground and far is None and rng.r(key("kfar")) < (0.2 if self.stair_on else 0.8):
                far, far_kind = kc, "kitchen"
            else:
                u = rng.r(key("kend"))
                end = "f" if (far_kind == "hub" and u < 0.9) else ("s" if u < 0.5 else "f")
                put(B, kc, end)
                if dine_back is not None:
                    k = B.index(kc)
                    B.insert(k + 1 if k == 0 else k, dine_back)      # beside the kitchen, on its inner side
            for extra in kitchen[1:]:
                put(B, Cell([[extra]]))
        if dine_back is not None and not any(dine_back is c for c in B):
            put(B, dine_back)
        for x in services:
            put(B, Cell([[x]]))
        # --- 5 The rooms into their bands.
        for r in order:
            if where[id(r)] == "C":
                continue
            band = F if where[id(r)] == "F" else B
            bath = suite_bath.get(id(r))
            if bath is not None and r is not core_f and r is not core_b:
                if rng.r(key("side", ix[id(r)])) < (0.9 if self.D < 11.5 else 0.6):
                    # The bath beside the bedroom, the depth of the band: the room
                    # keeps its window and its door on the passage.
                    put(band, Cell([[r]]))
                    put(band, Cell([[bath]]))
                    continue
                cell = Cell([[r], [bath]] if band is B else [[bath], [r]])
            else:
                cell = Cell([[r]])
            put(band, cell, "f" if r is core_f or r is core_b else None)
        # --- 6 The front: the living room (behind its sit-out), the porch at an end.
        if living:
            main = living[0]
            if verandah:
                verandah[0].fixed_d = max(1.8, min(2.4, verandah[0].area / 4.5))
            sit = [[verandah[0]]] if verandah else []
            for extra in verandah[1:]:
                put(F, Cell([[extra]]))
            put(F, Cell(sit + [[main]]), "f" if far_kind == "hub" and rng.r(key("livfar")) < 0.7 else None)
            for extra in living[1:]:
                put(F, Cell([[extra]]))
        elif verandah:
            put(F, Cell([[verandah[0]]]))
        for fy in foyer:
            # The entrance hall, with the shrine, a powder room or a shoe store
            # behind it, so it is a hall and not a corridor the depth of the band.
            behind, foyer_puja = foyer_puja, None
            if behind is None:
                behind = next((x for x in smalls_left if x.type in (T.POWDER, T.TOILET)), None)
                if behind is not None:
                    smalls_left.remove(behind)
            if behind is None:
                behind = P(T.STORE, 2.0, None, name="Store")
            put(F, Cell([[fy], [behind]]))
        for gp in garage:
            # The porch at the stair end, so the living room sits over the dining room.
            u = rng.r(key("porch", ix[id(gp)]))
            put(F, Cell([[gp]]), "s" if (far_kind == "hub" and u < 0.8) or (far_kind != "hub" and u < 0.5) else "f")
        for c in courts:
            put(B, Cell([[c]]))
        for t in terraces:
            put(B if rng.r(key("ter", ix[id(t)])) < 0.6 else F, Cell([[t]]), rng.choice(key("terend", ix[id(t)]), "sf"))
        # Balconies off a front room: a strip across its street face.
        for bal in balconies:
            note = (getattr(bal.req, "notes", "") or "").lower()
            host_name = note.split("opens off the", 1)[1].strip(" .") if "opens off the" in note else ""
            hosts = [c for c in F if len(c.slots) == 1
                     and c.slots[0][0].type in (BEDS | {T.LIVING, T.FAMILY, T.STUDY, T.DRAWING})]
            if host_name:
                hosts = [c for c in hosts if c.slots[0][0].type.value.replace("_", " ") == host_name] or hosts
            if hosts:
                hosts.sort(key=lambda c: c.slots[0][0].type is not T.MASTER_BEDROOM)
                h = hosts[0] if host_name or rng.r(key("bal", ix[id(bal)])) < 0.6 else rng.choice(key("balwho", ix[id(bal)]), hosts)
                bal.host = h.slots[0][0]
                bal.fixed_d = 1.5
                h.slots.insert(0, [bal])
            else:
                put(F, Cell([[bal]]), rng.choice(key("balend", ix[id(bal)]), "sf"))
        # A passage that serves two rooms behind runs on between them; a landing
        # lobby may run on into either band to reach the rooms at its corners.
        def needy(band):
            return sum(1 for c in band if (c.slots[-1] if band is F else c.slots[0])[0].type in ROOMISH)
        if passage is not None:
            nf, nb = needy(F), needy(B)
            front_ok = passage.slots[0][0].type is T.CORRIDOR
            back_ok = passage.slots[-1][0].type is T.CORRIDOR
            want = ("F" if front_ok and nf and rng.r(key("spanf")) < (0.85 if nf >= 2 else 0.5) else "") + ("B" if back_ok and nb and rng.r(key("spanb")) < (0.85 if nb >= 2 else 0.3) else "")
            passage.span = want
        if not ground and hub is not None and hub.fixed_w is not None:
            # A band with two rooms that need the landing: the lobby runs on
            # between them, or is wide enough for both doors side by side.
            nf, nb = needy(F), needy(B)
            front_ok = hub.slots[0][0].type is T.LOBBY
            back_ok = hub.slots[-1][0].type is T.LOBBY
            span = ""
            if front_ok and nf and rng.r(key("lobf")) < (0.85 if nf >= 2 else 0.35):
                span += "F"
            if back_ok and nb and rng.r(key("lobb")) < (0.85 if nb >= 2 else 0.35):
                span += "B"
            hub.span = span
            if ("F" not in span and nf >= 2) or ("B" not in span and nb >= 2):
                hub.fixed_w = max(hub.fixed_w, 2.2)
        # --- 7 The stair, the same on every floor; the far end against the other wall.
        # The stair lands on the passage, the lobby or the dining room, not beside a toilet.
        through = next((c for c in mid if c.pieces() and c.pieces()[-1].type in (T.CORRIDOR, T.LOBBY, T.DINING, T.FAMILY)
                        or any(p.type in (T.CORRIDOR, T.LOBBY) for p in c.pieces())), None)
        if self.stair_on and through is not None and mid and mid[0] is not through:
            mid.remove(through)
            mid.insert(0, through)
        core = list(mid)
        if far is not None:
            core.append(far) if low else core.insert(0, far)
        if not low:
            core = [c for c in core if c is far] + [c for c in reversed(mid)] if far is not None else list(reversed(mid))
        st = Cell([[P(T.STAIRCASE, 0.0, name="Staircase")]],
                  fixed_w=self.st_rot_w if g["stair_rot"] else self.st_w) if self.stair_on else None
        if g.get("thin"):
            # One passage across the house, rooms in front of it and behind it:
            # the plan for a shallow plot. The stair stands at the back, at its end.
            hall = next((c for c in core if c.slots[0][0].type in (T.CORRIDOR, T.LOBBY)
                         or c.slots[-1][0].type in (T.CORRIDOR, T.LOBBY)), None)
            if hall is None:
                hall = Cell([[P(T.CORRIDOR if ground else T.LOBBY, 0.0, name="Passage" if ground else "Lobby", scale=self.min_scale)]])
            keep = [x for x in hall.slots if x[0].type in (T.CORRIDOR, T.LOBBY)][:1]
            for x in hall.slots:
                if x not in keep:
                    core.append(Cell([x]))
            hall.slots, hall.span, hall.fixed_w = keep, "", 1.2
            for c in core:
                if c is hall:
                    continue
                to_front = any(p.type in (T.PUJA, T.FAMILY) for p in c.pieces()) \
                    and rng.r(key("thinf", ix.get(id(c.pieces()[0]), "x"))) < 0.6
                put(F if to_front else B, c)
            core = [hall]
            day = [c for c in B if any(p.type in (T.DINING, T.KITCHEN) for p in c.pieces())]
            if ground and len(B) > len(day) and rng.r(key("thinfront")) < 0.8:
                # Dining beside the living room, the kitchen beside it: the day
                # rooms along the street, the bedrooms behind the passage.
                for c in day:
                    B.remove(c)
                    put(F, c)
            if st is not None:
                put(B, st, "s")
            return [F, core, B]
        if st is not None:
            core.insert(0, st) if low else core.append(st)
        return [F, core, B]

    # ------------------------------------------------------------ ordering --

    def _depths(self, house, Wh: float, g: dict) -> list[list[float]] | None:
        self._stair_d = None
        """Band depths for every floor. The front band is the same on every
        floor, so the line the stair starts from stacks; behind it each floor
        shares the same total between its core and back bands as its own rooms
        want - a ground floor with a light back band does not draw a 26 m2
        bedroom because the floor above needed a deep one."""
        caps = (5.6, 5.0, 5.6)
        # A house that has to fill a deep plot (everything but the lawn is house)
        # has deeper bands: up to 40% deeper, and never deeper than the plot.
        k = getattr(self, "_area_need", 0.0) / max(1.0, Wh * sum(caps))
        k = max(1.0, min(1.4, k, self.D / sum(caps)))
        caps = tuple(c * k for c in caps)
        need = [[0.0] * 3 for _ in house]
        mins = [[0.0] * 3 for _ in house]
        for li, fl in enumerate(house):
            for r in range(3):
                row = fl[r]
                if not row:
                    continue
                fx = sum(c.fixed_w or 0.0 for c in row)
                flex = sum(c.area for c in row if c.fixed_w is None)
                if Wh - fx < 0.9:
                    return None
                if flex:
                    # Upstairs, a light band leaves a terrace rather than set the depth.
                    need[li][r] = min(caps[r], flex / (Wh - fx) * (1.0 if li == 0 else 0.9))
                mins[li][r] = max(c.min_d for c in row)
            if self.stair_on:
                sr = 2 if g.get("thin") else 1
                mins[li][sr] = max(mins[li][sr], self.st_rot_d if g["stair_rot"] else self.st_run)
        front = max(max(need[li][0], mins[li][0]) for li in range(len(house)))
        rest = max(max(need[li][1], mins[li][1]) + max(need[li][2], mins[li][2]) for li in range(len(house)))

        out = []
        for li in range(len(house)):
            c = max(need[li][1], mins[li][1])
            b = max(need[li][2], mins[li][2])
            spare = rest - c - b
            if spare > 1e-6:
                # The floor's own surplus goes to its bands in proportion to what they hold.
                wc, wb = need[li][1] or 0.5, need[li][2] or 0.5
                c += spare * wc / (wc + wb)
                b = rest - c
            out.append([front, c, b])
        if self.stair_on and not g.get("thin"):
            # The stair stands at the top of the core on every floor; a floor whose
            # core is deeper has a store under it, never a sliver.
            low_c = min(o[1] for o in out)
            for o in out:
                if o[1] - low_c < 1.0:
                    o[2] += o[1] - low_c
                    o[1] = low_c
            run = self.st_rot_d if g["stair_rot"] else self.st_run
            self._stair_d = run + 0.4 if low_c > run + 1.0 else low_c
        if g.get("thin"):
            # One passage across the house and the stair behind it: every floor
            # keeps the same lines.
            same = [max(o[r] for o in out) for r in range(3)]
            out = [list(same) for _ in out]
        return out

    @staticmethod
    def _spans(row: list[Cell], d: float, a: float, b: float):
        """Approximate x-intervals of a band's cells laid across [a, b]."""
        if not row:
            return []
        nat = [c.fixed_w if c.fixed_w is not None else min(max(c.area / max(d, 0.5), c.min_w), c.max_w) for c in row]
        flex = [i for i, c in enumerate(row) if c.fixed_w is None]
        fixed = sum(nat[i] for i in range(len(row)) if i not in flex)
        tot = sum(nat[i] for i in flex) or 1.0
        k = max(0.1, (b - a - fixed) / tot) if flex else 1.0
        out, x = [], a
        for i, _c in enumerate(row):
            w = nat[i] * (k if i in flex else 1.0)
            out.append((x, x + w))
            x += w
        return out

    def _arrange(self, house, Wh: float, floors_d: list[list[float]], g: dict) -> None:
        """Order the cells of every band, floor by floor, so each room gets its
        door onto the hub or the passage, the kitchen meets the dining room, the
        shrine keeps clear of the toilets and the bathrooms stack - checked on
        rough widths, every order of a band's movable cells tried."""
        low = g["stair_end"] == "L"
        below: dict[int, list] = {}
        self._below_bands = None
        for li, fl in enumerate(house):
            depths = floors_d[li]
            F, C, B = fl
            stair = next((c for c in C if c.slots[0][0].type is T.STAIRCASE), None)
            free = [c for c in C if c is not stair]
            # The far end, against the other side wall, keeps what the composer put there.
            far = None
            if len(free) > 1:
                cand = free[-1] if low else free[0]
                if cand.slots[0][0].type not in (T.CORRIDOR, T.LOBBY, T.TERRACE):
                    far = cand
                    free.remove(far)
            best = None
            for perm in itertools.islice(itertools.permutations(free), 120):
                core = list(perm)
                if far is not None:
                    core = core + [far] if low else [far] + core
                if stair is not None:
                    core = [stair] + core if low else core + [stair]
                cs = self._spans(core, depths[1], 0.0, Wh)
                pen = self._core_pen(core, cs, below.get(li - 1))
                if best is not None and pen - 400 >= best[0]:
                    continue
                faces: tuple[list, list] = ([], [])
                hole = {}
                for c, (x0, x1) in zip(core, cs):
                    for k, slot in ((0, c.slots[0]), (1, c.slots[-1])):
                        faces[k].append((x0, x1, slot[0].type))
                    if c.span:
                        if "F" in c.span:
                            hole[0] = (x0, x1)
                        if "B" in c.span:
                            hole[2] = (x0, x1)
                fb = []
                for r, band in ((0, F), (2, B)):
                    bb = None
                    for order in itertools.islice(itertools.permutations(band), 240):
                        if any(c.slots[0][0].type is T.GARAGE for c in order[1:-1]):
                            continue           # the porch keeps to an end, on the drive
                        if r == 2 and order and any(c.slots[0][0].type is T.STAIRCASE for c in order) and \
                                order[0 if low else -1].slots[0][0].type is not T.STAIRCASE:
                            continue           # the stair keeps its end, the same on every floor
                        p2 = self._band_pen(list(order), r, depths[r], Wh, faces[0 if r == 0 else 1],
                                            hole.get(r), core, cs, li)
                        if bb is None or p2 < bb[0]:
                            bb = (p2, list(order))
                    fb.append(bb or (0.0, list(band)))
                total = pen + fb[0][0] + fb[1][0]
                if best is None or total < best[0]:
                    best = (total, core, fb[0][1], fb[1][1])
            if best is not None:
                fl[0][:], fl[1][:], fl[2][:] = best[2], best[1], best[3]
            cs = self._spans(fl[1], depths[1], 0.0, Wh)
            below[li] = [(c, x0, x1) for c, (x0, x1) in zip(fl[1], cs)]
            self._below_bands = {r: list(zip(fl[r], self._spans(fl[r], depths[r], 0.0, Wh))) for r in (0, 2)}

    @staticmethod
    def _core_pen(core, cs, below) -> float:
        pen = 0.0
        n = len(core)
        for i, c in enumerate(core):
            types = [p.type for p in c.pieces()]
            nb = [core[j] for j in (i - 1, i + 1) if 0 <= j < n]
            nb_types = {p.type for x in nb for p in x.pieces()}
            if T.STAIRCASE in types and not nb_types & {T.CORRIDOR, T.LOBBY, T.DINING, T.FAMILY} \
                    and any(p.type in (T.CORRIDOR, T.LOBBY, T.DINING, T.FAMILY) for x in core for p in x.pieces()):
                pen += 30
            if any(t in WET for t in types) and not any(p.host is not None for p in c.pieces()) \
                    and not nb_types & {T.CORRIDOR, T.LOBBY, T.DINING, T.FAMILY}:
                pen += 60                     # a common bath needs a hall to open off
            if T.PUJA in types and nb_types & WET:
                pen += 50
            if T.DINING in types and 0 < i < n - 1:
                pen += 25                     # a dining room in the middle has no window
            if T.KITCHEN in types and T.DINING in nb_types:
                pen -= 20
            if below is not None and any(t in WET for t in types):
                x0, x1 = cs[i]
                for bc, b0, b1 in below:
                    if min(x1, b1) - max(x0, b0) > 0.4:
                        bt = {p.type for p in bc.pieces()}
                        if bt & {T.KITCHEN, T.DINING, T.PUJA}:
                            pen += 45
                        elif bt & WET:
                            pen -= 6
        return pen

    def _band_pen(self, order, r, d, Wh, faces, hole, core, cs, li) -> float:
        if hole is not None:
            h0, h1 = hole
            best = None
            for k in range(len(order) + 1):
                miss = abs(sum(c.area for c in order[:k]) / max(d, 0.5) - h0) + \
                    abs(sum(c.area for c in order[k:]) / max(d, 0.5) - (Wh - h1))
                if best is None or miss < best[0]:
                    best = (miss, k)
            k = best[1]
            spans = self._spans(order[:k], d, 0.0, h0) + self._spans(order[k:], d, h1, Wh)
        else:
            spans = self._spans(order, d, 0.0, Wh)
        pen = 0.0
        n = len(order)
        for i, c in enumerate(order):
            # A room behind another in its bay sees daylight only at the house's side walls.
            if len(c.slots) > 1 and 0 < i < n - 1:
                inner = c.slots[1:] if r == 0 else c.slots[:-1]
                if any(p.type.is_habitable for s_ in inner for p in s_):
                    pen += 110
            mates = [q for q in c.pieces() if q.type in WET and q.host is not None and len(c.slots) == 1]
            for q in mates:
                nb = [order[j] for j in (i - 1, i + 1) if 0 <= j < n]
                if not any(q.host in x.pieces() for x in nb):
                    pen += 60                 # a suite's bath stays beside its room
            types_i = {p.type for p in c.pieces()}
            if T.FOYER in types_i and not any(T.LIVING in {p.type for p in order[j].pieces()}
                                              for j in (i - 1, i + 1) if 0 <= j < n):
                pen += 60                     # the entrance hall opens into the living room
            if T.KITCHEN in types_i and any(T.DINING in {p.type for p in order[j].pieces()}
                                            for j in (i - 1, i + 1) if 0 <= j < n):
                pen -= 40
        under = (self._below_bands or {}).get(r) if li > 0 else None
        if under:
            for c, (x0, x1) in zip(order, spans):
                if any(p.type in WET for p in c.pieces()):
                    for bc, (b0, b1) in under:
                        if min(x1, b1) - max(x0, b0) > 0.4:
                            bt = {p.type for p in bc.pieces()}
                            if bt & {T.KITCHEN, T.DINING, T.PUJA}:
                                pen += 45
                            elif bt & WET:
                                pen -= 6
        for c, (x0, x1) in zip(order, spans):
            slot = c.slots[-1] if r == 0 else c.slots[0]
            t = slot[0].type
            if t not in FREE and not slot[0].filler:
                ok = any(min(x1, f1) - max(x0, f0) >= 1.05 and is_through(ft) and may_enter(t, ft)
                         for f0, f1, ft in faces)
                if not ok and hole is not None and (abs(x1 - hole[0]) < 0.05 or abs(x0 - hole[1]) < 0.05) \
                        and may_enter(t, T.CORRIDOR if li == 0 else T.LOBBY):
                    ok = True
                if not ok:
                    pen += 100
            types = {p.type for p in c.pieces()}
            for cc, (c0, c1) in zip(core, cs):
                ov = min(x1, c1) - max(x0, c0)
                if ov <= 0.05:
                    continue
                ct = {p.type for p in cc.pieces()}
                if T.KITCHEN in types and T.DINING in ct and ov >= 1.0:
                    pen -= 40
                if T.LIVING in types and T.DINING in ct and ov >= 1.9:
                    pen -= 45
                if T.PUJA in types and ct & WET:
                    pen += 50
                if ov >= 1.0:
                    for p in c.pieces():
                        if p.type in BEDS and any(q.host is p for q in cc.pieces()):
                            pen -= 35         # its bathroom in the core, beside it
        # A bedroom whose bathroom is in the core but not beside it has lost it.
        for c, (x0, x1) in zip(order, spans):
            for p in c.pieces():
                if p.type not in BEDS:
                    continue
                for cc, (c0, c1) in zip(core, cs):
                    if any(q.host is p for q in cc.pieces()) and min(x1, c1) - max(x0, c0) < 1.0:
                        pen += 90
        return pen

    # ------------------------------------------------------------ sizing --

    def _size(self, house: list[list[list[Cell]]], Wh: float, g: dict):
        floors_d = self._depths(house, Wh, g)
        if floors_d is None:
            return None
        if any(d < -1e-6 for o in floors_d for d in o):
            return None
        Dh = max(sum(o) for o in floors_d)
        if Dh > self.D + 1e-6:
            self.why["deeper_than_plot"] = self.why.get("deeper_than_plot", 0) + 1
            return None
        if Wh * Dh > self.cover * 1.02 + 1e-6:
            self.why["over_coverage"] = self.why.get("over_coverage", 0) + 1
            return None
        gap = self.D - Dh
        v_top = self.D - min(gap * 0.2, 3.0)       # the house at the front, a lawn on a deep plot
        u0 = (self.W - Wh) * g["u_shift"]
        out = []
        self._wh = Wh
        self._stair_top = g.get("stair_top", True)
        for li, fl in enumerate(house):
            depths = floors_d[li]
            # Whether this floor has its lounge already, for `_lay`'s fillers.
            self._has_lounge = any(p.type is T.FAMILY for row in fl for c in row for p in c.pieces())
            core = self._lay(list(fl[1]), depths[1], 0.0, Wh, li, 1, g)
            if core is None:
                self.why[468] = self.why.get(468, 0) + 1
                return None
            holes: dict[int, tuple[float, float]] = {}
            for c, x0, x1 in core:
                if c.span:
                    if "F" in c.span:
                        holes[0] = (x0, x1)
                    if "B" in c.span:
                        holes[2] = (x0, x1)
            # The front and back rooms take their walls from the core's lines
            # wherever they nearly meet: walls in line, and every room's door
            # on the hub rather than a few centimetres short of it.
            lines = []
            faces: tuple[list, list] = ([], [])        # what the core shows the front band, and the back
            for c, x0, x1 in core:
                lines.append(x0)
                for k, slot in ((0, c.slots[0]), (1, c.slots[-1])):
                    sx = x0
                    pw = [x1 - x0] if len(slot) == 1 else (
                        _fit(x1 - x0, [p.area or 1.0 for p in slot], [p.min_s for p in slot])
                        or [(x1 - x0) / len(slot)] * len(slot))
                    for p, ww in zip(slot, pw):
                        faces[k].append((sx, sx + ww, p.type))
                        sx += ww
                if any(p.type in (T.CORRIDOR, T.LOBBY, T.DINING, T.FAMILY) for p in c.pieces()):
                    lines.append((x0 + x1) / 2)
            lines.append(Wh)
            rows = {1: core}
            for r in (0, 2):
                row = list(fl[r])
                if r in holes:
                    rows[r] = self._split(row, depths[r], holes[r], Wh, li, r, g)
                else:
                    laid = self._lay(row, depths[r], 0.0, Wh, li, r, g)
                    rows[r] = None if laid is None else self._snap(laid, lines, faces[0 if r == 0 else 1], Wh, r == 0)
                if rows[r] is None:
                    self.why[503] = self.why.get(503, 0) + 1
                    return None
            placed: list = []
            v = v_top
            spans = []
            for r in range(3):
                d = depths[r]
                for c, x0, x1 in rows[r]:
                    k = len(placed)
                    if not self._cell(c, u0 + x0, v - d, u0 + x1, v, placed, li=li, band=r):
                        self.why[512] = self.why.get(512, 0) + 1
                        return None
                    if c.span:
                        spans.append((c, k, len(placed)))
                v -= d
            # A passage or lobby that runs on between the rooms of the next band.
            for c, k0, k1 in spans:
                for k in range(k0, k1):
                    p, a0, b0, a1, b1 = placed[k]
                    if p.type in (T.CORRIDOR, T.LOBBY):
                        if "B" in c.span:
                            b0 -= depths[2]
                        if "F" in c.span:
                            b1 += depths[0]
                        placed[k] = (p, a0, b0, a1, b1)
            out.append(placed)
        return out, floors_d, (u0, v_top - Dh, u0 + Wh, v_top)

    def _lay(self, row: list[Cell], d: float, a: float, b: float, li: int, r: int, g: dict):
        """Cells of one band, or one stretch of it, across [a, b]: (cell, x0, x1).
        What the rooms leave at their natural size is open: terrace upstairs, a
        sit-out under the floor above at the front or back of the ground floor."""
        if d <= 0 or b - a < 0.05:
            return [] if not row else None
        width = b - a
        fixed = {id(c): c.fixed_w for c in row if c.fixed_w is not None}
        flex = [c for c in row if c.fixed_w is None]
        nat = [c.area / d for c in flex]
        caps = [c.max_w for c in flex]
        avail = width - sum(fixed.values())
        # Upstairs the rooms take the floor before any of it is left as roof:
        # a bedroom a third bigger than asked is a better room; a strip of
        # terrace beside it no one uses is not.
        grow_k = 1.35 if li > 0 else 1.12
        roomy = sum(min(grow_k * n_, m) for n_, m in zip(nat, caps))
        spare = avail - roomy
        row = list(row)
        open_kind = T.TERRACE if li > 0 else (T.VERANDAH if r == 0 else None)
        if row and all(c.slots[0][0].type in (T.CORRIDOR, T.LOBBY) for c in row):
            open_kind = None                 # a passage across the house is all hall
        if li > 0 and r == 1 and spare > 0.3:
            # Upstairs the core's spare width widens the landing into a sitting
            # lobby before it becomes a terrace no door can reach.
            lob = next((c for c in row if c.slots[0][0].type is T.LOBBY), None)
            if lob is not None:
                add = min(spare, max(0.0, (2.4 if d <= 4.5 and not lob.span else 1.6) - fixed[id(lob)]))   # a long landing stays narrow
                fixed[id(lob)] += add
                spare -= add
                avail -= add
        if li > 0 and open_kind is not None and spare >= 3.0 and flex and \
                any(p.type in (T.MASTER_BEDROOM, T.BEDROOM, T.FAMILY, T.CHILDREN_BEDROOM, T.GUEST_BEDROOM, T.STAIRCASE, T.LOBBY)
                    for c in row for p in c.pieces()):
            # Upstairs, width the rooms cannot use is a room before it is roof:
            # a lounge if the floor has none yet, else a study.
            lounge = getattr(self, "_has_lounge", False)
            kind, label = (T.STUDY, "Study") if lounge else (T.FAMILY, "Upper lounge")
            self._has_lounge = True
            w = min(spare, 4.2 if kind is T.FAMILY else 3.2)
            t = Cell([[P(kind, 0.0, name=label, filler=True)]], fixed_w=w)
            fixed[id(t)] = w
            # At the end of the band, on the house's side wall, so it has a window;
            # the end away from the stair, which stays where it is on every floor.
            stair_i = next((i for i, c in enumerate(row) if c.slots[0][0].type is T.STAIRCASE), None)
            row.insert(0 if stair_i is not None and stair_i >= len(row) / 2 else len(row), t)
            spare -= w
            avail -= w
        if open_kind is not None and spare >= (2.6 if li > 0 else 1.6) and (li > 0 or spare > avail - sum(caps) - 1e-6 or not flex):
            name = "Terrace" if li > 0 else "Sit-out"
            if li == 0 or flex:
                spare = min(spare, 3.2)   # one balcony-deep strip; the rooms take the rest
            t = Cell([[P(open_kind, 0.0, name=name, filler=True)]], fixed_w=spare)
            fixed[id(t)] = spare
            at_low = a < 0.05
            at_high = b > self._wh - 0.05
            liv = next((k for k, c in enumerate(row) if any(p.type is T.LIVING for p in c.pieces())), None)
            if li == 0 and liv is not None:
                # The sit-out is the porch to the living room: beside it, on the street.
                row.insert(liv + (1 if g["ter_end"] == "R" else 0), t)
            elif at_low != at_high:
                # A stretch beside a passage: open at the house's side wall.
                row.insert(0 if at_low else len(row), t)
            elif any(c.slots[0][0].type is T.STAIRCASE for c in row):
                # Never between the stair and its wall: the stair stays where it is on every floor.
                st_i = next(i for i, c in enumerate(row) if c.slots[0][0].type is T.STAIRCASE)
                row.insert(len(row) if st_i == 0 else 0, t)
            else:
                row.insert(0 if g["ter_end"] == "L" else len(row), t)
            avail -= spare
        elif li == 0 and r == 2 and flex and avail - sum(caps) >= 1.4:
            # Downstairs the rooms cannot stretch to fill the band: behind the
            # kitchen goes its wash yard, in the core a family lounge at the side
            # wall or a store by the stair, and the rest is shared out.
            excess = avail - sum(caps)
            kit = next((i for i, c in enumerate(row) if any(p.type is T.KITCHEN for p in c.pieces())), None)
            stair = next((i for i, c in enumerate(row) if c.slots[0][0].type is T.STAIRCASE), None)
            if r == 2 and kit is not None:
                w, t = min(excess, 3.0), Cell([[P(T.UTILITY, 0.0, name="Wash area", filler=True)]])
                at = kit + 1 if kit == 0 else kit
            elif excess >= 3.0:
                w, t = min(excess, 4.6), Cell([[P(T.FAMILY, 0.0, name="Family lounge", filler=True)]])
                at = len(row) if g["stair_end"] == "L" else 0
            elif stair is not None:
                w, t = min(excess, 2.4), Cell([[P(T.STORE, 0.0, name="Store", filler=True)]])
                at = stair + 1 if stair == 0 else stair
            else:
                w, t = 0.0, None
            if t is not None:
                t.fixed_w = w
                fixed[id(t)] = w
                row.insert(at, t)
                avail -= w
        elif not flex and avail > 0.05:
            if not row:
                return None          # a ground-floor band with nothing in it
            grow = next((c for c in row if c.slots[0][0].type in (T.LOBBY, T.CORRIDOR)), None)
            if grow is None:
                return None          # a stair alone in its band is not stretched across the house
            if li > 0 and r == 1 and grow.slots[0][0].type is T.LOBBY and (d > 4.5 or grow.span)                     and fixed[id(grow)] + avail >= 1.6 + 1.8:
                # A long landing stays a landing; the width it cannot use is a sitting
                # lounge beside it, so the floor has no hall as big as a room.
                lounge_w = fixed[id(grow)] + avail - 1.6
                fixed[id(grow)] = 1.6
                t = Cell([[P(T.FAMILY, 0.0, name="Upper lounge", filler=True)]], fixed_w=lounge_w)
                fixed[id(t)] = lounge_w
                st_i = next((i for i, c in enumerate(row) if c.slots[0][0].type is T.STAIRCASE), None)
                row.insert(len(row) if st_i == 0 or st_i is None else 0, t)
            else:
                fixed[id(grow)] += avail
            avail = 0.0
        widths = _fit(avail, nat, [c.min_w for c in flex], caps) if flex else []
        if widths is None:
            return None
        it = iter(widths)
        out = []
        x = a
        for c in row:
            w = fixed[id(c)] if id(c) in fixed else next(it)
            out.append((c, x, x + w))
            x += w
        return out

    def _split(self, row: list[Cell], d: float, hole: tuple[float, float], Wh: float, li: int, r: int, g: dict):
        """A band the passage runs through: rooms either side of it, split where they fit best."""
        h0, h1 = hole
        if d <= 0:
            return [] if not row else None
        best = None
        for k in range(len(row) + 1):
            left, right = row[:k], row[k:]
            la = self._lay(left, d, 0.0, h0, li, r, g)
            ra = self._lay(right, d, h1, Wh, li, r, g)
            if la is None or ra is None:
                continue
            miss = abs(sum(c.area for c in left) / d - h0) + abs(sum(c.area for c in right) / d - (Wh - h1))
            if best is None or miss < best[0]:
                best = (miss, la + ra)
        return None if best is None else best[1]

    @staticmethod
    def _snap(laid, lines, faces, Wh, front: bool):
        """Move the walls between rooms onto the core's lines: walls in line, and
        every room that needs a door onto the hub or the passage given one."""
        if len(laid) < 2:
            return laid

        def served(c: Cell, a: float, b: float) -> bool:
            slot = c.slots[-1] if front else c.slots[0]
            t = slot[0].type
            if t in FREE or slot[0].filler:
                return True
            return any(min(b, f1) - max(a, f0) >= 1.05 and is_through(ft) and may_enter(t, ft)
                       for f0, f1, ft in faces)

        nat = [x1 for _c, _x0, x1 in laid]
        mins = [c.min_w if c.fixed_w is None else c.fixed_w for c, _a, _b in laid]
        cuts = []
        prev = 0.0
        n = len(laid)
        for i in range(n - 1):
            lo = prev + mins[i]
            hi = Wh - sum(mins[i + 1:])
            if lo > hi + 1e-6:
                return laid
            cands = {min(max(nat[i], lo), hi)}
            cands.update(ln for ln in lines if lo - 1e-6 <= ln <= hi + 1e-6 and abs(ln - nat[i]) <= 1.9)
            nxt = nat[i + 1] if i + 1 < n - 1 else Wh

            def cost(x: float, i=i, prev=prev, nxt=nxt) -> float:
                c = abs(x - nat[i])
                if not served(laid[i][0], prev, x):
                    c += 50
                if not served(laid[i + 1][0], x, max(nxt, x + mins[i + 1])):
                    c += 25
                if not any(abs(x - ln) < 1e-6 for ln in lines):
                    c += 0.4          # a wall off the grid
                return c
            best = min(cands, key=cost)
            cuts.append(best)
            prev = best
        edges = [0.0] + cuts + [Wh]
        if any(b - a < 0.5 for a, b in zip(edges, edges[1:])):
            return laid
        return [(c, a, b) for (c, _a, _b), a, b in zip(laid, edges, edges[1:])]

    def _cell(self, c: Cell, u0, v0, u1, v1, placed, li: int = 0, band: int = 1) -> bool:
        d = v1 - v0
        if len(c.slots) == 1 and c.slots[0][0].type is T.STAIRCASE:
            sd = getattr(self, "_stair_d", None) or d
            if d > sd + 0.05:
                # The stair takes its run and a landing; the rest of the bay is the store under it.
                st = d - sd
                placed.append((c.slots[0][0], u0, v0 + st, u1, v1) if self._stair_top else (c.slots[0][0], u0, v0, u1, v1 - st))
                store = P(T.STORE, 0.0, name="Store", filler=True)
                placed.append((store, u0, v0, u1, v0 + st) if self._stair_top else (store, u0, v1 - st, u1, v1))
                return True
        fixed = [s[0].fixed_d for s in c.slots]
        free = d - sum(f or 0.0 for f in fixed)
        idx = [i for i, f in enumerate(fixed) if not f]
        nat = [sum(p.area for p in c.slots[i]) or 1.0 for i in idx]
        mins = [max(p.min_s for p in c.slots[i]) for i in idx]
        # Small rooms keep to their depth; the room they share the bay with takes the rest.
        maxs = [min(MAX_D.get(p.type, math.inf) for p in c.slots[i]) for i in idx]
        ds = _fit(free, nat, mins, maxs) if idx else []
        if ds is None:
            return False
        dd = dict(zip(idx, ds))
        v = v1
        for i, s in enumerate(c.slots):
            sd = fixed[i] if fixed[i] else dd[i]
            ws = _fit(u1 - u0, [p.area or 1.0 for p in s], [p.min_s for p in s]) if len(s) > 1 else [u1 - u0]
            if ws is None:
                return False
            u = u0
            deep = self._spare_depth(s, sd)
            if deep is not None:
                # A bath in a deep bay keeps its depth; what is left is its dressing room.
                keep_d, filler = deep
                p = s[0]
                if band == 2:
                    placed.append((filler, u0, v - (sd - keep_d), u1, v))
                    placed.append((p, u0, v - sd, u1, v - (sd - keep_d)))
                else:
                    placed.append((p, u0, v - keep_d, u1, v))
                    placed.append((filler, u0, v - sd, u1, v - keep_d))
                v -= sd
                continue
            for p, w in zip(s, ws):
                # A room is never stretched past what a room of its kind is: the
                # width it cannot use becomes the dressing room (or wardrobe)
                # beside it, opening from the bedroom, and the room keeps its shape.
                extra = self._spare_strip(c, s, p, w, sd)
                if extra is not None:
                    keep, filler = extra
                    placed.append((p, u, v - sd, u + keep, v))
                    placed.append((filler, u + keep, v - sd, u + w, v))
                else:
                    placed.append((p, u, v - sd, u + w, v))
                u += w
            v -= sd
        return True

    @staticmethod
    def _spare_depth(slot: list[P], sd: float):
        """(depth the bath keeps, the dressing room that takes the rest) or None."""
        if len(slot) != 1:
            return None
        p = slot[0]
        if p.filler or p.type is not T.BATHROOM or p.host is None:
            return None
        cap = MAX_D[T.BATHROOM]
        if sd > cap + 0.9 and sd - cap >= 1.3:
            return cap, P(T.STORE, 0.0, None, host=p.host,
                          name="Dressing" if p.host.type is T.MASTER_BEDROOM else "Wardrobe", filler=True)
        return None

    @staticmethod
    def _spare_strip(c: Cell, slot: list[P], p: P, w: float, sd: float):
        """(width the room keeps, the filler that takes the rest) or None."""
        if len(slot) != 1 or p.filler:
            return None
        if p.type is T.BATHROOM and p.host is not None:
            cap = MAX_W[T.BATHROOM]
            if w > cap + 0.9:
                keep = max(p.min_s, min(cap, max(2.3, 1.1 * p.area / max(sd, 1.0))))
                if w - keep >= 1.3:
                    return keep, P(T.STORE, 0.0, None, host=p.host, name="Dressing", filler=True)
        elif p.type in BEDS and sd >= 3.2 and w >= 4.6:
            suite = any(q.type is T.BATHROOM and q.host is p for s2 in c.slots for q in s2)
            actual = w * sd
            if actual > 1.5 * max(p.area, 1.0) and not suite:
                strip = min(2.2, max(1.3, (actual - 1.25 * p.area) / sd))
                if w - strip >= max(3.0, p.min_s):
                    return w - strip, P(T.STORE, 0.0, None, host=p, name="Dressing" if p.type is T.MASTER_BEDROOM else "Wardrobe", filler=True)
        return None

    # ------------------------------------------------------------ judging --

    def _score(self, plan, box) -> tuple[float, list[str]]:
        from aip.engines.architecture.layout import aspect_limit

        floors, depths, (hu0, hv0, hu1, hv1) = plan
        pen = 0.0
        notes = []
        tally = self.tally = {}

        def hit(x: float, why: str) -> None:
            nonlocal pen
            pen += x
            if self.debug:
                tally[why] = tally.get(why, 0.0) + x
        cu, cv = (hu0 + hu1) / 2, (hv0 + hv1) / 2
        eps = 0.02

        def shared(a, b) -> float:
            _, a0, b0, a1, b1 = a
            _, c0, d0, c1, d1 = b
            if abs(a1 - c0) < eps or abs(c1 - a0) < eps:
                return max(0.0, min(b1, d1) - max(b0, d0))
            if abs(b1 - d0) < eps or abs(d1 - b0) < eps:
                return max(0.0, min(a1, c1) - max(a0, c0))
            return 0.0

        def exterior(a) -> float:
            _, u0, v0, u1, v1 = a
            e = 0.0
            if abs(u0 - hu0) < eps or abs(u1 - hu1) < eps:
                e += v1 - v0
            if abs(v0 - hv0) < eps or abs(v1 - hv1) < eps:
                e += u1 - u0
            return e

        below = []
        wet_below = []
        # A grandparent in the house sleeps on the ground floor, not up a flight of stairs.
        if self.elders and len(floors) > 1 and not any(x[0].type in BEDS for x in floors[0]):
            hit(90, "elder_upstairs")
            notes.append("no bedroom downstairs for the elder")
        # The flight from one floor arrives where the next one starts: the stair
        # is one rectangle on every floor, or it is not a stair.
        stairs = [next(((u0, v0, u1, v1) for p, u0, v0, u1, v1 in placed if p.type is T.STAIRCASE), None)
                  for placed in floors]
        stairs = [s_ for s_ in stairs if s_ is not None]
        if any(max(abs(a - b) for a, b in zip(s_, stairs[0])) > 0.3 for s_ in stairs[1:]):
            hit(150, "stair_stack")
            notes.append("stair does not stack")
        ground_area = sum((u1 - u0) * (v1 - v0) for _, u0, v0, u1, v1 in floors[0]) if floors else 0.0
        for li, placed in enumerate(floors):
            if li > 0 and ground_area > 0:
                # An upper floor is rooms, with a balcony or a terrace: not a
                # floor of open roof, nor a plate smaller than the house below.
                built = sum((u1 - u0) * (v1 - v0) for p, u0, v0, u1, v1 in placed if p.type not in OUTDOOR)
                open_ = sum((u1 - u0) * (v1 - v0) for p, u0, v0, u1, v1 in placed if p.type in OUTDOOR)
                spare = max(0.0, open_ - 0.15 * ground_area) + max(0.0, 0.85 * ground_area - built - open_)
                if spare > 0:
                    hit(4.0 * spare, "upper_open")
                    if spare > 8:
                        notes.append(f"L{li} {spare:.0f}m2 of the floor is open roof")
            n = len(placed)
            adj = [[0.0] * n for _ in range(n)]
            for i in range(n):
                for j in range(i + 1, n):
                    s = shared(placed[i], placed[j])
                    adj[i][j] = adj[j][i] = s
            types = [x[0].type for x in placed]
            # 1 Reach: every room entered the right way from where you arrive.
            if li == 0:
                start = {i for i, t in enumerate(types) if t in (T.VERANDAH, T.FOYER) and abs(placed[i][4] - hv1) < eps} or \
                        {i for i, t in enumerate(types) if t in (T.LIVING, T.DRAWING)}
                if not any(abs(placed[i][4] - hv1) < eps for i in start):
                    hit(60, "entrance")
                    notes.append("entrance not on the road")
            else:
                start = {i for i, t in enumerate(types) if t is T.STAIRCASE} or \
                        {i for i, t in enumerate(types) if t is T.LOBBY}
            reached, _parent = self._reach(placed, types, adj, start)
            for i in range(n):
                if i not in reached and types[i] not in (T.GARAGE,) and not placed[i][0].filler:
                    hit(100, "unreachable")
                    notes.append(f"L{li} {types[i].value} unreachable")
                if types[i] is T.GARAGE and abs(placed[i][4] - hv1) > eps:
                    hit(80, "porch")
                    notes.append("porch off the road")
                if types[i] in (T.TERRACE, T.BALCONY) and exterior(placed[i]) < 1.0:
                    hit(80, "terrace_closed")
                    notes.append("enclosed terrace")
            # 2 Daylight and proportion.
            for i, (p, u0, v0, u1, v1) in enumerate(placed):
                w, d = u1 - u0, v1 - v0
                s, l = min(w, d), max(w, d)
                lit = exterior(placed[i]) + sum(adj[i][j] for j in range(n) if types[j] in OUTDOOR)
                if p.type.is_habitable and lit < 0.9:
                    hit(60, "daylight")
                    notes.append(f"L{li} {p.type.value} no window")
                if p.type in (T.KITCHEN, T.UTILITY, T.BATHROOM, T.TOILET) and exterior(placed[i]) < 0.5:
                    hit(6 if p.type in WET else 15, "service_wall")
                if s < p.min_s - 0.02:
                    hit(45 * (p.min_s - s) + 10, "narrow")
                    notes.append(f"L{li} {p.type.value} narrow {s:.1f}")
                ar = l / max(s, 0.1)
                cap = ASPECT.get(p.type)
                hard = aspect_limit(p.type)
                if hard is not None:
                    cap = min(cap or hard, hard)
                if cap and ar > cap:
                    hit(22 * (ar - cap), "aspect")
                if hard is not None and ar > hard + 0.05:
                    hit(40 + 30 * (ar - hard), "slot")
                    notes.append(f"L{li} {p.type.value} slot {w:.1f}x{d:.1f}")
                need = FURNISH_MIN.get(p.type)
                if need and (s < need[0] - 0.05 or l < need[1] - 0.05):
                    hit(25, "furnish")
                if p.type is T.COURTYARD and ar > 2.2:
                    # A courtyard is a square of sky, not a corridor open to it.
                    hit(80 + 40 * (ar - 2.2), "court_strip")
                    notes.append(f"L{li} courtyard a strip {w:.1f}x{d:.1f}")
                if p.type in (T.DINING, T.FAMILY) and ar > 2.2:
                    # The hall the rooms open off is a room with a table in it;
                    # stretched across the house it is the corridor renamed.
                    hit(80 + 40 * (ar - 2.2), "hall_strip")
                    notes.append(f"L{li} {p.type.value} a strip {w:.1f}x{d:.1f}")
                if p.type is T.STAIRCASE and w * d > 14.5:
                    hit(2 * (w * d - 14.5), "stair_big")
                if p.type in (T.LOBBY, T.CORRIDOR) and s > 2.4:
                    hit(6 * (s - 2.4), "passage_wide")
                # 3 Size against what was asked.
                if p.area > 0 and not p.filler:
                    a = w * d
                    asked = getattr(p.req, "asked_area", None) or p.area
                    if self.boost > 1.0 or li > 0:
                        # Upstairs rooms are grown on purpose to fill the floor (see
                        # `_fill_floors`): judged against that, not the first ask.
                        asked = max(asked, p.area)
                    dev = (a - p.area) / p.area
                    if li > 0 and dev > 0:
                        dev = max(0.0, dev - 0.2)         # and a little larger still is no fault
                    wt = WEIGHT.get(p.type, 0.6) * (2.0 if "Requested" in (getattr(p.req, "notes", "") or "") else 1.0)
                    if a < MIN_AREA.get(p.type, 0.0) - 0.2:
                        hit(30, "too_small")
                    hit(wt * (14 * max(0.0, -dev) + 7 * max(0.0, dev - 0.15)), "area")
                    if a > 1.55 * asked and p.type not in OUTDOOR:
                        hit(40, "too_big")
                        notes.append(f"L{li} {p.type.value} {a:.0f}m2 vs {asked:.0f}")
                    cap_a = comfort_cap(p.type, self.beds)
                    if cap_a is not None:
                        cap_a *= self.boost
                    if cap_a is not None and a > 1.08 * cap_a:
                        hit(4 + 2 * (a - 1.08 * cap_a), "over_cap")
            # 4 Relationships the household expects.
            def idx(t):
                return [i for i, x in enumerate(types) if x is t]
            K, Dn, L = idx(T.KITCHEN), idx(T.DINING), idx(T.LIVING)
            liv_area = max(((placed[a][3] - placed[a][1]) * (placed[a][4] - placed[a][2]) for a in L), default=0.0)
            # A long passage is dead floor and a long walk: the shorter the better.
            # A hall the width of the house is the corridor plan again, turned.
            for i, t in enumerate(types):
                if t in (T.CORRIDOR, T.LOBBY):
                    run = max(placed[i][3] - placed[i][1], placed[i][4] - placed[i][2])
                    if run > 4.0:
                        hit(16.0 * (run - 4.0), "long_passage")
                        notes.append(f"L{li} passage {run:.1f} m long")
            if K and Dn and max(adj[k][d] for k in K for d in Dn) < 1.0:
                hit(60, "kitchen_dining")
                notes.append("kitchen off dining")
            if L and Dn and max(adj[a][d] for a in L for d in Dn) < 1.9:
                hit(55, "living_dining")
                notes.append("living off dining")
            # A toilet shares no wall with the kitchen or the dining room: the
            # cooking, the table and the drain are kept apart.
            for i in K + Dn:
                if any(adj[i][w] > 0.3 for w in range(n) if types[w] in WET):
                    hit(40, "food_wet")
                    notes.append(f"{types[i].value} beside a toilet")
            for pj in idx(T.PUJA):
                if any(adj[pj][w] > 0.05 for w in range(n) if types[w] in WET):
                    hit(50, "puja_wet")
                    notes.append("puja beside a toilet")
                if any(adj[pj][s] > 0.05 for s in idx(T.STAIRCASE)) and li == 0:
                    hit(4, "puja_stair")
            for i, (p, *_r) in enumerate(placed):
                host = p.host
                if host is not None and p.type in WET:
                    hi = next((j for j in range(n) if placed[j][0] is host), None)
                    if hi is None or adj[i][hi] < 1.0:
                        hit(120, "suite")
                        notes.append("suite bath away from its room")
                if p.type in BEDS:
                    # A bedroom off the passage or lobby, not off the living room.
                    via = [types[j] for j in range(n) if adj[i][j] >= 1.0]
                    if not any(t in (T.CORRIDOR, T.LOBBY, T.FAMILY, T.DINING, T.STAIRCASE) for t in via):
                        hit(40, "bed_off_public")
                    if p.type is T.MASTER_BEDROOM:
                        others = [(x[3] - x[1]) * (x[4] - x[2]) for x in placed if x[0].type in BEDS - {T.MASTER_BEDROOM}]
                        mine = (placed[i][3] - placed[i][1]) * (placed[i][4] - placed[i][2])
                        if others and mine < 1.1 * max(others):
                            hit(25, "master_small")
                # The client's own words: next to, opens off, on a side.
                req = p.req
                if req is not None:
                    want = list(getattr(req, "must_be_adjacent_to", []) or [])
                    note = (getattr(req, "notes", "") or "").lower()
                    if "opens off the" in note:
                        name = note.split("opens off the", 1)[1].split(".")[0].strip()
                        want += [t for t in RoomType if t.value.replace("_", " ") == name]
                    asked = "requested" in note
                    for t in want:
                        if t in types and not any(types[j] is t and adj[i][j] > 0.9 for j in range(n)):
                            # The client's own "next to" is law; the programme's defaults are advice.
                            hit(45 if asked else 3, "next_to")
                            if asked:
                                notes.append(f"{p.type.value} not next to {t.value}")
                    for t in getattr(req, "must_not_be_adjacent_to", []) or []:
                        if any(types[j] is t and adj[i][j] > 0.05 for j in range(n)):
                            hit(40 if asked else 4, "not_next_to")
                    pref = getattr(req, "preferred_direction", None)
                    if pref is not None:
                        hit(35 * self._miss(placed[i], pref, cu, cv), "direction")
                if self.vastu_w and (p.req is not None or p.type is T.STAIRCASE):
                    ideal = self.prefer(p.type)
                    if ideal is not None:
                        # A strict or orthodox client asked for Vastu first: it pulls three times as hard.
                        pull = VASTU_PEN * (3.0 if self.vastu_w >= 0.8 else 1.0)
                        hit(pull * self.vastu_w * self._miss(placed[i], ideal, cu, cv), "vastu")
            for i, t in enumerate(types):
                if t is T.CORRIDOR and sum(1 for j in range(n) if adj[i][j] >= 1.0) < 3:
                    hit(20, "stub_passage")
                if t is T.DINING and liv_area and (placed[i][3] - placed[i][1]) * (placed[i][4] - placed[i][2]) > 0.85 * liv_area:
                    hit(25, "dining_big")
            # 5 Circulation share: passages are a few square metres.
            tot = sum((x[3] - x[1]) * (x[4] - x[2]) for x in placed if x[0].type not in OUTDOOR) or 1.0
            circ = sum((x[3] - x[1]) * (x[4] - x[2]) for x in placed if x[0].type in (T.CORRIDOR, T.LOBBY))
            if circ / tot > 0.08:
                hit(300 * (circ / tot - 0.08) + 600 * max(0.0, circ / tot - 0.12), "circulation")
            ter = sum((x[3] - x[1]) * (x[4] - x[2]) for x in placed if x[0].filler)
            # A house shows the street a proper front: on a wide plot it is not a 7 m sliver.
            if li == 0:
                hit(10 * max(0.0, 0.9 * getattr(self, "want_w", 0.0) - (hu1 - hu0)), "frontage")
            # Upstairs a terrace is welcome; half the floor open is a house drawn too wide.
            plate = (hu1 - hu0) * (hv1 - hv0)
            hit(0.1 * ter + 0.9 * max(0.0, ter - 0.15 * plate), "terrace")
            pieces = sum(1 for x in placed if x[0].type is T.TERRACE)
            hit(12 * max(0, pieces - 1), "terrace_bits")
            # 6 Wet over wet, never over the kitchen, puja or dining table.
            if li > 0:
                for p, u0, v0, u1, v1 in placed:
                    if p.type in WET:
                        a = (u1 - u0) * (v1 - v0)
                        bad = sum(wt * max(0.0, min(u1, b[2]) - max(u0, b[0])) * max(0.0, min(v1, b[3]) - max(v0, b[1]))
                                  for wt, b in below)
                        good = sum(max(0.0, min(u1, b[2]) - max(u0, b[0])) * max(0.0, min(v1, b[3]) - max(v0, b[1]))
                                   for b in wet_below)
                        if bad > 0.3 * a:
                            hit(70, "wet_over")
                            notes.append(f"L{li} bath over kitchen/puja/dining")
                        hit(-(4 * min(1.0, good / max(a, 0.1))), "wet_stack")
            if li == 0:
                below = [(UNDER[p.type], (u0, v0, u1, v1)) for p, u0, v0, u1, v1 in placed if p.type in UNDER]
            wet_below = [(u0, v0, u1, v1) for p, u0, v0, u1, v1 in placed if p.type in WET]
        return pen, notes

    #: Which neighbour a room is best entered from, most preferred first.
    _PREFER = {T.CORRIDOR: 0, T.LOBBY: 0, T.FOYER: 1, T.DINING: 2, T.FAMILY: 2, T.LIVING: 3, T.DRAWING: 3}

    def _reach(self, placed, types, adj, start):
        """Which rooms a legal door can reach from where you arrive, and from which
        neighbour each is best entered - the passage before the living room, a
        bath's own bedroom before anything."""
        n = len(placed)
        reached = set(start)
        parent: dict[int, int] = {}
        changed = True
        while changed:
            changed = False
            for i in range(n):
                if i in reached:
                    continue
                ti = types[i]
                host = placed[i][0].host
                best = None
                for j in reached:
                    if adj[i][j] < 1.0 - 1e-6:
                        continue
                    tj = types[j]
                    if host is not None and placed[j][0] is host:
                        rank = -1
                    elif ti is T.GARAGE or (ti is T.STAIRCASE and is_through(tj)):
                        rank = self._PREFER.get(tj, 5)
                    elif may_enter(ti, tj) and (is_through(tj) or tj in PRIVATE_HOST.get(ti, ()) or (ti in WET and tj in BEDS)):
                        rank = self._PREFER.get(tj, 4 if is_through(tj) else 6)
                    else:
                        continue
                    if best is None or rank < best[0]:
                        best = (rank, j)
                if best is not None:
                    reached.add(i)
                    parent[i] = best[1]
                    changed = True
        return reached, parent

    def _miss(self, rect, want: Direction, cu: float, cv: float) -> float:
        """0 when the room sits toward `want` from the middle of the house, 1 when opposite."""
        _, u0, v0, u1, v1 = rect
        du, dv = (u0 + u1) / 2 - cu, (v0 + v1) / 2 - cv
        if math.hypot(du, dv) < 0.8:
            return 0.0 if want is Direction.CENTRE else 0.5
        if want is Direction.CENTRE:
            return min(1.0, math.hypot(du, dv) / 4.0)
        b = self._bearing(du, dv)
        diff = abs((b - want.bearing + 180) % 360 - 180)
        return max(0.0, (diff - 22.5) / 157.5)

    # ------------------------------------------------------------ search --

    def plans(self, levels: list[list], count: int = 3, samples: int = 110, climbs: int = 10,
              steps: int = 30) -> list[list[list[Room]]]:
        """The best distinct plans: random compositions, each of the most promising
        then improved one decision at a time while that makes it better."""
        levels = [list(l) for l in levels]
        self.beds = sum(1 for l in levels for r in l if r.type in BEDS)
        # Courtyards, verandahs and car porches are ground-floor rooms.
        for l in levels[1:]:
            for r in [r for r in l if r.type in {T.COURTYARD, T.VERANDAH, T.GARAGE}]:
                l.remove(r)
                levels[0].append(r)
        found: dict[tuple, tuple] = {}
        inf = float("inf")
        area_need = max(sum(min(r.target_area, OPEN_MAX.get(r.type, r.target_area)) for r in l if r.type not in DRAWN
                            and "fills the footprint" not in (r.notes or "")) for l in levels)
        self._area_need = area_need

        def evaluate(genes: dict, scale: float) -> tuple[float, dict]:
            G = self.genes = Genes(self.rng, genes)
            g = {"stair_end": "L" if G.r("stair_end") < 0.5 else "R", "stair_rot": G.r("stair_rot") < (0.5 if self.cover < 85.0 else 0.2),
                 "lobby_w": G.choice("lobby_w", [1.5, 1.8, 2.1, 2.7, 3.3]), "ter_end": "L" if G.r("ter_end") < 0.5 else "R",
                 "u_shift": 0.5, "bed_down": G.r("bed_down"),
                 "thin": G.r("thin") < (0.55 if self.D < 12.5 else 0.15),
                 "stair_top": G.r("stair_top") < 0.5}
            house = self._house(levels, g, scale)
            if house is None:
                self.why["compose"] = self.why.get("compose", 0) + 1
                return inf, G.g
            # The width the house takes: from snug to as wide as the plot and
            # its coverage allow once the bands are as shallow as they can be.
            lo = max(max(sum(c.min_w if c.fixed_w is None else c.fixed_w for c in row) for row in fl) for fl in house)
            dmin = sum(max((c.min_d for fl in house for c in fl[r]), default=0.0) for r in range(3))
            if self.stair_on:
                dmin = max(dmin, self.st_rot_d if g["stair_rot"] else self.st_run)
            hi = min(self.W, self.cover / max(dmin, 1.0))
            if hi < lo - 1e-6:
                self.why["too_wide" if lo > self.W + 1e-6 else "too_deep"] = self.why.get("too_wide" if lo > self.W + 1e-6 else "too_deep", 0) + 1
                return inf, G.g
            # A house in proportion to its plot: the width an architect would
            # start from, give or take, never a sliver on a wide site.
            want = min(self.W, math.sqrt(area_need * scale * 1.2 * self.W / max(self.D, 1.0)))
            # The house takes most of a narrow frontage; on a large plot it keeps
            # the plot's own proportions.
            # On a town plot the house spans the frontage between its side
            # setbacks (90% of it) and the depth takes up the rest; a wide plot
            # keeps the plot's own proportions, or a shallow house that wide
            # needs a hall across it.
            if self.W <= 14:
                want = max(want, 0.9 * self.W)
            a, b = max(lo, min(hi, 0.85 * want)), min(hi, max(lo, 1.2 * want))
            # On a shallow plot a narrow house would have to be deeper than the
            # plot: the house is at least as wide as its area needs the depth for.
            a = max(a, min(b, area_need * scale / max(self.D, 1.0)))
            self.want_w = want
            Wh = a + (b - a) * G.r("width")
            depths = self._depths(house, Wh, g)
            if depths is None:
                self.why["depths"] = self.why.get("depths", 0) + 1
                return inf, G.g
            self._arrange(house, Wh, depths, g)
            sized = self._size(house, Wh, g)
            if sized is None:
                self.why["size"] = self.why.get("size", 0) + 1
                return inf, G.g
            pen, notes = self._score(sized, None)
            sig = tuple(tuple(tuple(tuple(p.type.value for p in s) for s in c.slots) for c in row)
                        for fl in house for row in fl)
            if sig not in found or pen < found[sig][0]:
                found[sig] = (pen, sized, notes, dict(self.tally))
            return pen, {k: v for k, v in G.g.items() if k in G.used}

        for scale in (1.0, 0.9, 0.8, 0.72):
            pool = [x for x in (evaluate({}, scale) for _ in range(samples)) if x[0] < inf]
            pool.sort(key=lambda x: x[0])
            for pen, genes in pool[:climbs]:
                for _ in range(steps):
                    trial = dict(genes)
                    for k in self.rng.sample(sorted(trial, key=str), min(len(trial), 1 + (self.rng.random() < 0.35))):
                        if k == "width" and self.rng.random() < 0.6:
                            trial[k] = min(0.999, max(0.0, trial[k] + self.rng.gauss(0, 0.12)))
                        else:
                            trial[k] = self.rng.random()
                    p2, g2 = evaluate(trial, scale)
                    if p2 <= pen:
                        pen, genes = p2, g2
            # Smaller rooms only when the plot leaves no choice.
            if found and min(v[0] for v in found.values()) < 400:
                break
        best = sorted(found.values(), key=lambda v: v[0])
        out = []
        self.notes = []
        for pen, sized, notes, tally in best[:count]:
            out.append(self._rooms(sized))
            self.notes.append((round(pen, 1), notes, {k: round(v, 1) for k, v in tally.items() if abs(v) > 0.5}))
        return out

    def _house(self, levels, g, scale):
        lv = []
        for li, reqs in enumerate(levels):
            ps = self._pieces(reqs)
            for p in ps:
                if scale < 1.0:
                    p.area = max(p.area * scale, min(p.area, MIN_AREA.get(p.type, p.area * 0.8)))
            lv.append(ps)
        if len(lv) > 1 and not any(p.type in BEDS for p in lv[0]):
            # A bedroom on the ground floor, for parents who should not climb -
            # or because the floor above has more rooms than it can hold well.
            up = next((l for l in lv[1:] if sum(1 for p in l if p.type in BEDS) >= 2), None)
            crowded = up is not None and sum(1 for p in up if p.type in BEDS) >= 4
            if g["bed_down"] >= (0.3 if self.elders else 0.65 if crowded else 1.1):
                up = None
            if self.cover < 85.0 and not self.elders and not crowded:
                up = None            # a small plate keeps its ground floor for the day rooms
            if up is not None:
                bed = min((p for p in up if p.type in BEDS and p.type is not T.MASTER_BEDROOM),
                          key=lambda p: p.area, default=None)
                if bed is not None:
                    up.remove(bed)
                    lv[0].append(bed)
                    bath = next((p for p in up if p.type is T.BATHROOM), None)
                    if bath is not None and sum(1 for p in up if p.type is T.BATHROOM) > sum(1 for p in up if p.type in BEDS):
                        up.remove(bath)
                        lv[0].append(bath)
        # Every floor with a bedroom has a bathroom on it: a spare one moves
        # from a floor that has more than its bedrooms need, or one is added.
        for li, ps in enumerate(lv):
            beds = sum(1 for p in ps if p.type in BEDS)
            if beds and not any(p.type in WET for p in ps):
                donor = next((d for d in lv if d is not ps and
                              sum(1 for p in d if p.type is T.BATHROOM) > max(1, sum(1 for p in d if p.type in BEDS))), None)
                if donor is not None:
                    b = next(p for p in donor if p.type is T.BATHROOM)
                    donor.remove(b)
                    ps.append(b)
                else:
                    ps.append(P(T.BATHROOM, 4.5, None, name="Bathroom"))
        house = []
        ground_area = sum(p.area for p in lv[0]) or 1.0
        for li, ps in enumerate(lv):
            self._suites(ps)
            # A floor with much less on it than the ground keeps its rooms
            # together at the back and leaves the front as one terrace.
            g["light"] = li > 0 and sum(p.area for p in ps) < 0.35 * ground_area
            fl = self._compose(li, ps, g)
            if not any(fl):
                return None
            drawn = {id(p) for row in fl for c in row for p in c.pieces()}
            if any(id(p) not in drawn for p in ps):
                return None                  # never a plan that drops a room it was given
            house.append(fl)
        return house

    @staticmethod
    def _row_w(row: list[Cell]) -> float:
        return sum(c.fixed_w if c.fixed_w is not None else c.min_w for c in row)

    def _balance(self, fl: list[list[Cell]]) -> None:
        """A band that cannot fit across the plot gives a room to another band:
        a narrow plot has the same rooms, arranged to its width."""
        keep = {T.STAIRCASE, T.CORRIDOR, T.LOBBY, T.FOYER, T.LIVING, T.DRAWING}
        for _ in range(10):
            w = [self._row_w(r) for r in fl]
            r = max(range(3), key=lambda i: w[i])
            if w[r] <= self.W + 1e-6:
                return
            best = None
            for c in fl[r]:
                if c.fixed_w is not None or c.span or any(p.type in keep for p in c.pieces()):
                    continue
                for o in range(3):
                    if o == r or w[o] + c.min_w > self.W + 1e-6:
                        continue
                    # Prefer the emptiest band, and the cell that eases the wide one most.
                    key = (w[o] + c.min_w, -c.min_w)
                    if best is None or key < best[0]:
                        best = (key, c, o)
            if best is None:
                return
            _, c, o = best
            fl[r].remove(c)
            fl[o].append(c)

    def _rooms(self, sized) -> list[list[Room]]:
        floors, _depths, _box = sized
        out = []
        for li, placed in enumerate(floors):
            rooms = []
            made: dict[int, Room] = {}
            for p, u0, v0, u1, v1 in placed:
                if u1 - u0 < 0.5 or v1 - v0 < 0.5:
                    continue
                area = round((u1 - u0) * (v1 - v0), 2)
                req = p.req
                # The dressing room or wardrobe a spare strip beside a bedroom
                # becomes opens off that bedroom: a wardrobe, not a store, which
                # may only be reached from the kitchen or a hall.
                kind = T.WARDROBE if p.filler and p.host is not None and p.host.type in BEDS else p.type
                rooms.append(Room(
                    name=p.name or p.type.label, type=kind, polygon=self._poly(u0, v0, u1, v1), level=li,
                    ceiling_height=3.0,
                    metadata={"_c": (u0, v0, u1, v1), "notes": getattr(req, "notes", "") or "",
                              "target_area": getattr(req, "target_area", None) or area,
                              "brief_area": getattr(req, "asked_area", None) or getattr(req, "target_area", None) or area,
                              "planner": "parti"}))
                made[id(p)] = rooms[-1]
            # A suite's bath, and a balcony off its room, name the room they belong to,
            # so the doors go where the plan meant them.
            # The door each room is meant to have: the door placer follows it where it is legal.
            types = [x[0].type for x in placed]
            n = len(placed)
            eps = 0.02

            def touch(a, b):
                _, a0, b0, a1, b1 = a
                _, c0, d0, c1, d1 = b
                if abs(a1 - c0) < eps or abs(c1 - a0) < eps:
                    return max(0.0, min(b1, d1) - max(b0, d0))
                if abs(b1 - d0) < eps or abs(d1 - b0) < eps:
                    return max(0.0, min(a1, c1) - max(a0, c0))
                return 0.0
            adj = [[touch(placed[i], placed[j]) if i != j else 0.0 for j in range(n)] for i in range(n)]
            top = max(x[4] for x in placed)
            start = ({i for i, t in enumerate(types) if t in (T.VERANDAH, T.FOYER) and abs(placed[i][4] - top) < eps}
                     or {i for i, t in enumerate(types) if t in (T.LIVING, T.DRAWING)}) if li == 0 else \
                ({i for i, t in enumerate(types) if t is T.STAIRCASE} or {i for i, t in enumerate(types) if t is T.LOBBY})
            _reached, parent = self._reach(placed, types, adj, start)
            for i, j in parent.items():
                a, b = placed[i][0], placed[j][0]
                if id(a) in made and id(b) in made:
                    made[id(a)].metadata["enter_from"] = made[id(b)].id
            for p, *_r in placed:
                if p.host is not None and id(p) in made and id(p.host) in made:
                    made[id(p)].metadata["suite_of"] = made[id(p.host)].id
                elif p.type in WET and id(p) in made:
                    made[id(p)].metadata["common"] = True      # opens off the passage, for everyone
            out.append(rooms)
        return out
