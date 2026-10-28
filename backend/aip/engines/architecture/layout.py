"""Constraint-guided generative floorplan synthesis.

Why not a diffusion model? Because pixel-space generation of floorplans produces
images, not buildings: walls that do not close, rooms without doors, areas that
cannot be dimensioned, and nothing a quantity surveyor or a structural engineer
can consume. It also needs a GPU, which breaks the zero-cost promise.

Instead the generator works in the representation the problem actually has. A
plan is encoded as a **slicing tree** - the classical floorplanning formulation
from VLSI placement - where internal nodes are horizontal or vertical cuts with a
split ratio, and leaves are rooms. This guarantees, by construction, that:

* rooms tile the envelope with no gaps and no overlaps;
* every wall is straight, closed and dimensioned;
* the plan is buildable and can be priced.

The tree is then optimised by an evolutionary search whose fitness function is
the *analytical* metric suite - daylight, ventilation, privacy, circulation,
accessibility, code compliance and Vastu. Because those metrics are exact and
run in microseconds, the optimiser can evaluate thousands of candidates per
second on a laptop CPU, for free.

The language models enter afterwards, where they add real value: interpreting an
ambiguous brief into a room programme, judging aesthetic coherence, and
explaining the result. Geometry is left to geometry.
"""

from __future__ import annotations

import itertools
import math
import random
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from aip.core.logging import get_logger, log_event
from aip.domain.brief import NBC_MIN_AREAS, ClientBrief, RoomRequirement
from aip.domain.geometry import (
    BoundingBox,
    Direction,
    Vec2,
    bearing_to_direction,
    direction_of,
    distance_point_to_segment,
    rectangle,
    shared_edge,
    shrink_polygon,
)
from aip.domain.plan import (
    ColumnGrid,
    FloorPlan,
    Level,
    Opening,
    OpeningKind,
    Room,
    RoomType,
    Staircase,
    StructuralSystem,
    Wall,
    WallKind,
)
from aip.engines.architecture.feasibility import (
    CAP_HEADROOM,
    comfort_cap,
    COMFORT_FRACTION,
    COMFORT_PACKING,
    EXTRA_ROOMS,
    FILL_TARGET,
    FURNISH_MIN,
    OPTIONAL_ORDER,
    PACKING_EFFICIENCY,
    FeasibilityReport,
    InfeasibleBriefError,
    allowed_bathrooms,
    bedrooms_in,
    comfortable_area,
    luxury_max,
    max_levels,
    minimum_area,
    storey_word,
)
from aip.engines.architecture.programme import passage_area

__all__ = ["InfeasibleBriefError", "LayoutGenerator", "GeneratorConfig"]

logger = get_logger("aip.layout")

#: The staircase footprint every floor shares: a dog-leg of two 1.0 m flights
#: side by side with a half-landing, 2.4 m across and 4.5 m long (10.8 m2). Fixed once so
#: the sizing of the programme, the envelope and the carve all agree.
STAIR_WIDTH = 2.4
STAIR_LENGTH = 4.5
STAIR_AREA = STAIR_WIDTH * STAIR_LENGTH
#: A small plot takes a tighter dog-leg: two 0.9 m flights and a landing.
STAIR_WIDTH_COMPACT, STAIR_LENGTH_COMPACT = 2.0, 3.5
#: A floor plate under this (m2) is a small plot.
COMPACT_PLATE = 85.0
# Bedrooms keep their statutory 9.5 m2: the code officer disqualifies a scheme under it.
_COMPACT_ROOMS = {RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN, RoomType.FAMILY, RoomType.STUDY}

#: Marks the terrace the generator adds to fill a light upper floor, so the
#: feasibility arithmetic can tell it from a room the client asked for.
FILL_NOTE = "Terrace over the floor below; fills the footprint."
#: Upstairs rooms that grow to fill a light floor before any of it is left as terrace.
_UPSTAIRS_GROW = {RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM,
                  RoomType.FAMILY, RoomType.STUDY, RoomType.HOME_OFFICE, RoomType.LIBRARY}

MIN_ROOM_DIMENSION = 1.5          # m - below this nothing is buildable


def _min_clear_widths() -> dict[RoomType, float]:
    """The narrowest each kind of room may be and still be that room.

    NBC 2016 gives the habitable rooms; the rest are what a practice holds
    to: a passage a person walks along, a bathroom a door can open in, a
    stair with two flights side by side, a foyer that is not a slot. A
    bathroom is 1.5 m because a door, a WC and a person standing between them
    need it; the 1.0 m of the code is a shower cubicle, not a bathroom.
    """
    from aip.domain.brief import NBC_MIN_WIDTH

    widths = dict(NBC_MIN_WIDTH)
    widths.update({
        RoomType.CORRIDOR: 1.0, RoomType.LOBBY: 1.2,
        RoomType.BATHROOM: 1.5, RoomType.TOILET: 1.0, RoomType.POWDER: 0.9,
        RoomType.PUJA: 1.2, RoomType.STORE: 1.2, RoomType.UTILITY: 1.2, RoomType.WARDROBE: 1.2,
        RoomType.PANTRY: 1.2, RoomType.LAUNDRY: 1.2,
        RoomType.FOYER: 1.5, RoomType.STAIRCASE: 2.0,
        RoomType.VERANDAH: 1.0, RoomType.BALCONY: 1.0, RoomType.TERRACE: 1.0,
        RoomType.GARAGE: 2.4,
    })
    return widths


MIN_CLEAR_WIDTH: dict[RoomType, float] = _min_clear_widths()
WALL_THICKNESS_EXTERIOR = 0.23
WALL_THICKNESS_INTERIOR = 0.115

#: The longest a room of each kind may be, as length over width, before it is
#: a slot and not a room. A bedroom stops being furnishable around 1.7:1 - past
#: that the bed goes on the long wall and leaves a corridor beside it; a dining
#: room takes a table and chairs to 2:1; a living room carries a seating group
#: and tolerates 2.2:1; a kitchen is allowed to be a galley at 2.4:1. Wet rooms
#: and stores are 3:1 at most.
ASPECT_LIMIT: dict[RoomType, float] = {
    RoomType.MASTER_BEDROOM: 1.7, RoomType.BEDROOM: 1.7, RoomType.GUEST_BEDROOM: 1.7,
    RoomType.CHILDREN_BEDROOM: 1.7, RoomType.DINING: 2.0,
    RoomType.LIVING: 2.2, RoomType.DRAWING: 2.2, RoomType.FAMILY: 2.2,
    RoomType.KITCHEN: 2.4,
}
#: Habitable rooms start to cost from here.
COMFORTABLE_ASPECT = 1.6
#: A passage wider than this is a room. The audit tolerates 1.9; the search aims lower.
PASSAGE_STRIP_MAX = 1.5
WET_ASPECT_LIMIT = 3.0


def aspect_limit(room_type: RoomType) -> float | None:
    """Hard cap on a room's aspect ratio; None for rooms that may be long."""
    if room_type.is_circulation or room_type.is_outdoor:
        return None
    if room_type in ASPECT_LIMIT:
        return ASPECT_LIMIT[room_type]
    return 2.5 if room_type.is_habitable else WET_ASPECT_LIMIT


def proportion_penalty(room_type: RoomType, aspect: float) -> float:
    """What a badly proportioned room costs: gently past 1.6:1, steeply past its cap.

    Two terms. The soft one, `0.10 x (aspect - 1.6)` for habitable rooms,
    always prefers the squarer of two partitions. The hard one adds a jump
    the moment the room crosses its cap, plus a steep slope beyond it, so a
    slot never wins just because everything else about its partition scored
    well - the old shape term saturated at 3:1, which made an 8:1 room cost
    exactly what a 3:1 one did and gave the search no reason to stop.
    """
    limit = aspect_limit(room_type)
    if limit is None:
        return 0.0
    if room_type.is_habitable:
        cost = 0.10 * max(0.0, aspect - COMFORTABLE_ASPECT)
    else:
        cost = 0.12 * max(0.0, aspect - 1.8)
    if aspect > limit:
        cost += 0.8 + 1.0 * (aspect - limit)
    return cost


#: Corridor and lobby together above this share of a floor is overhead.
CORRIDOR_SHARE_TARGET = 0.10


def corridor_penalty(share: float) -> float:
    """Smooth cost of circulation above 10% of the floor, steep above 12%."""
    return 1.0 * max(0.0, share - CORRIDOR_SHARE_TARGET) + 3.0 * max(0.0, share - 0.12)


# ---------------------------------------------------------------------------
# Slicing tree
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Leaf:
    """A room slot."""

    slot: int

    def leaves(self) -> Iterator[Leaf]:
        yield self

    def depth(self) -> int:
        return 1

    def copy(self) -> Leaf:
        return Leaf(self.slot)


@dataclass(slots=True)
class Split:
    """A cut. `vertical` splits left/right; otherwise bottom/top.

    A `locked` cut is part of a fixed skeleton - the carve that gives the
    staircase the same rectangle on every floor - and neither mutation nor
    crossover may move, flip or swap it. The search is free inside the
    regions a locked cut leaves, never over the cut itself.
    """

    vertical: bool
    ratio: float
    left: Node
    right: Node
    locked: bool = False

    def leaves(self) -> Iterator[Leaf]:
        yield from self.left.leaves()
        yield from self.right.leaves()

    def depth(self) -> int:
        return 1 + max(self.left.depth(), self.right.depth())

    def copy(self) -> Split:
        return Split(self.vertical, self.ratio, self.left.copy(), self.right.copy(), self.locked)


Node = Leaf | Split


def realise(node: Node, box: BoundingBox) -> dict[int, BoundingBox]:
    """Turn a slicing tree into concrete rectangles."""
    out: dict[int, BoundingBox] = {}
    _realise_into(node, box, out)
    return out


def _realise_into(node: Node, box: BoundingBox, out: dict[int, BoundingBox]) -> None:
    if isinstance(node, Leaf):
        out[node.slot] = box
        return
    # A locked cut sits exactly where the skeleton put it; the clamp exists to
    # stop the search drawing slivers, and a fixed stair is not a sliver.
    ratio = node.ratio if node.locked else min(0.92, max(0.08, node.ratio))
    if node.vertical:
        cut = box.min_x + box.width * ratio
        left = BoundingBox(box.min_x, box.min_y, cut, box.max_y)
        right = BoundingBox(cut, box.min_y, box.max_x, box.max_y)
    else:
        cut = box.min_y + box.height * ratio
        left = BoundingBox(box.min_x, box.min_y, box.max_x, cut)
        right = BoundingBox(box.min_x, cut, box.max_x, box.max_y)
    _realise_into(node.left, left, out)
    _realise_into(node.right, right, out)


def build_balanced_tree(
    slots: Sequence[int],
    rng: random.Random,
    areas: Sequence[float],
    box: BoundingBox | None = None,
    shape_bias: float = 0.0,
) -> Node:
    """Area-proportional recursive bisection.

    Splitting each group so the two halves carry roughly equal *area* - rather
    than an equal *count* - gives the optimiser a far better starting point,
    because room sizes in a real brief differ by an order of magnitude.

    With a `box`, the orientation of each cut follows the shape of the region
    it divides: cut across the longer side, which is how a squarified treemap
    keeps its cells near square. A coin-flip orientation hands the search a
    population of slots - a room 1.9 m by 10 m is what a random cut across the
    short side of a long region makes - and the search then has to spend its
    generations undoing them.
    """
    if len(slots) == 1:
        return Leaf(slots[0])

    order = list(slots)
    total = sum(areas[s] for s in order) or 1.0
    target = total / 2
    running = 0.0
    cut_index = 1
    for i, slot in enumerate(order):
        running += areas[slot]
        if running >= target:
            cut_index = max(1, min(len(order) - 1, i + 1))
            break

    left_slots = order[:cut_index]
    right_slots = order[cut_index:]
    left_area = sum(areas[s] for s in left_slots) or 1.0
    right_area = sum(areas[s] for s in right_slots) or 1.0
    ratio = min(0.88, max(0.12, left_area / (left_area + right_area)))

    if box is not None and rng.random() < shape_bias:
        vertical = box.width >= box.height
    else:
        vertical = rng.random() < 0.5
    left_box = right_box = None
    if box is not None:
        if vertical:
            cut = box.min_x + box.width * ratio
            left_box = BoundingBox(box.min_x, box.min_y, cut, box.max_y)
            right_box = BoundingBox(cut, box.min_y, box.max_x, box.max_y)
        else:
            cut = box.min_y + box.height * ratio
            left_box = BoundingBox(box.min_x, box.min_y, box.max_x, cut)
            right_box = BoundingBox(box.min_x, cut, box.max_x, box.max_y)

    return Split(
        vertical=vertical,
        ratio=ratio,
        left=build_balanced_tree(left_slots, rng, areas, left_box, shape_bias),
        right=build_balanced_tree(right_slots, rng, areas, right_box, shape_bias),
    )


def build_zoned_tree(
    slots: Sequence[int],
    requirements: Sequence[RoomRequirement],
    areas: Sequence[float],
    rng: random.Random,
    **kwargs,
) -> Node:
    """`_zoned_tree`, checked: every slot exactly once, or a balanced tree.

    A slicing tree that names a slot twice draws one of them and leaves a
    hole where the other was; one that omits a slot loses the room. Either
    is a bug in the template, and the failsafe is to fall back to the plain
    partition and say so, never to hand a plan with a hole to the search.
    """
    tree = _zoned_tree(slots, requirements, areas, rng, **kwargs)
    leaves = sorted(leaf.slot for leaf in tree.leaves())
    if leaves != sorted(slots):
        log_event(
            logger, "layout.zoned_tree_invalid", level=40,
            expected=len(slots), got=len(leaves),
            kinds=[requirements[s].type.value for s in slots],
        )
        return build_balanced_tree(list(slots), rng, areas)
    return tree


def _zoned_tree(
    slots: Sequence[int],
    requirements: Sequence[RoomRequirement],
    areas: Sequence[float],
    rng: random.Random,
    *,
    road_along_y: bool,
    road_at_high_end: bool,
    bands: int = 3,
    brief_kind=None,
    frontage: float | None = None,
) -> Node:
    """A tree organised the way a real plan is: in bands from the road inward.

    A random tree can place any room anywhere and relies on evolution to find
    the front-to-back gradient every house has. It rarely does in the time
    available, and the plans that come out have bedrooms on the street and
    dining rooms at the back fence. This starts from the gradient instead.

    Rooms are sorted by where they belong along the plot depth, cut into bands
    across the road axis, and each band is then divided along its length. What
    evolution then refines is the ratios and the order within a band - the
    kind of local adjustment it is actually good at - rather than the whole
    organising idea, which it is not.
    """

    if len(slots) == 1:
        return Leaf(slots[0])

    def needs_light(slot: int) -> bool:
        """Does this room need one of a band's two windowed end positions?

        Only the rooms the code calls habitable. A utility, a store or a puja
        niche wants a ventilator, not a window, and counting them as lit
        split the kitchen band and put the utility across the whole plan as
        a strip between the dining room and the passage.
        """
        req = requirements[slot]
        return req.needs_daylight and req.type.is_habitable

    # The residential template, stated by role rather than discovered by
    # packing. This is how a practice lays out a plot: arrival and the
    # public rooms at the frontage; the dining-kitchen-utility group behind
    # them; a passage across the seam; the bedrooms beyond it, each with a
    # bathroom beside it. Packing rooms into bands by area alone put the
    # dining room in front of the living room and the kitchen behind the
    # bedrooms, because area does not know what a room is for.
    # The garage is at the road, with the arrival; it is entered from outside
    # and from the foyer, never from the house's interior. A balcony belongs
    # to a bedroom or to the living room and is reached only through it, so
    # it rides with the private bands as an attached room rather than taking
    # a slot of its own at the frontage, where it became a thoroughfare.
    front_types = {RoomType.FOYER, RoomType.VERANDAH, RoomType.LIVING,
                   RoomType.DRAWING, RoomType.PUJA, RoomType.HOME_OFFICE,
                   RoomType.GARAGE}
    service_types = {RoomType.DINING, RoomType.KITCHEN, RoomType.UTILITY, RoomType.PANTRY,
                     RoomType.STORE, RoomType.LAUNDRY, RoomType.FAMILY}
    wet_types = {RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER,
                 RoomType.BALCONY, RoomType.TERRACE}
    private_types = {RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
                     RoomType.CHILDREN_BEDROOM, RoomType.STUDY, RoomType.SERVANT}
    passage_types = {RoomType.CORRIDOR, RoomType.LOBBY}

    def of(kinds: set) -> list[int]:
        return [s for s in slots if requirements[s].type in kinds]

    passage = of(passage_types)
    front = of(front_types)
    service = of(service_types)
    wet = of(wet_types)
    private = of(private_types)
    # The staircase is a core cell against the passage - the landing upstairs,
    # the stair hall downstairs - never a band of its own. As a band it came
    # out as a strip the width of the house and a metre deep.
    stairs = [s for s in slots if requirements[s].type is RoomType.STAIRCASE]
    other = [s for s in slots if s not in front + service + wet + private + passage + stairs]

    # Four-band variant: an open living-dining, with the dining room joining
    # the frontage and the kitchen directly behind it. Both are common; the
    # search chooses between them on merit.
    if bands >= 4:
        dining = [s for s in service if requirements[s].type is RoomType.DINING]
        front += dining
        service = [s for s in service if s not in dining]

    # Bathrooms: one beside the master bedroom if it asked for one, the rest
    # shared out among the bedroom bands.
    attached: list[int] = []
    common: list[int] = []
    wants_attached = any(requirements[m].attached_bathroom for m in private)
    for w in wet:
        if requirements[w].type is RoomType.BATHROOM and not attached and wants_attached:
            attached.append(w)
        else:
            common.append(w)
    # Outdoor rooms go last in the distribution so they land at the far end
    # of a rear band, where a balcony actually sits.
    common.sort(key=lambda w: requirements[w].type.is_outdoor)

    # Private rooms in bands of at most two daylit rooms, bathrooms as core.
    private_sorted = sorted(
        private, key=lambda s: 0 if requirements[s].type is RoomType.MASTER_BEDROOM else 1
    )
    private_bands: list[list[int]] = []
    band: list[int] = []
    lit_count = 0
    for slot in private_sorted:
        if lit_count >= 2:
            private_bands.append(band)
            band, lit_count = [], 0
        band.append(slot)
        lit_count += needs_light(slot)
    if band:
        private_bands.append(band)
    # Wet rooms with no bedroom to serve: off the hall when there is one
    # (the ground floor of a two-storey house), else in the service band.
    hall_core: list[int] = list(stairs)
    if private_bands:
        if attached:
            private_bands[0] += attached
        for index, w in enumerate(common):
            private_bands[index % len(private_bands)].append(w)
    elif passage:
        hall_core += common + attached
    else:
        service += common + attached

    def split_lit(group: list[int]) -> list[list[int]]:
        """Bands hold at most two daylit rooms; overflow starts a new band."""
        out: list[list[int]] = []
        current: list[int] = []
        lit = 0
        for slot in group:
            if lit >= 2 and needs_light(slot):
                out.append(current)
                current, lit = [], 0
            current.append(slot)
            lit += needs_light(slot)
        if current:
            out.append(current)
        return out

    groups: list[list[int]] = []
    if front or other:
        groups.extend(split_lit(front + other))
    if service:
        groups.extend(split_lit(service))
    groups.extend(private_bands)
    groups = [g for g in groups if g]
    # Mild variation so seeded genomes are not clones: shuffle within a band.
    for g in groups:
        rng.shuffle(g)

    # Daylit rooms to the two ends of each band; the core between them. And
    # crucially, a room lands on the *same side* as the room it most wants
    # to touch in the band in front of it. Bands stack front-to-back, so two
    # rooms in consecutive bands only meet if they share a side: dining at
    # the right end of the living band and the kitchen at the left end of
    # the next one never touch, however well each is placed on its own.
    from aip.engines.architecture.programme import programme_for

    wanted: dict[RoomType, dict[RoomType, float]] = {}
    for rel in programme_for(brief_kind):
        if rel.required and rel.governs_wall():
            wanted.setdefault(rel.a, {})[rel.b] = rel.weight
            wanted.setdefault(rel.b, {})[rel.a] = rel.weight

    def arrange(group: list[int], previous: list[int]) -> list[int]:
        lit = [g for g in group if needs_light(g)]
        core = [g for g in group if not needs_light(g)]
        if len(lit) <= 1:
            return lit[:1] + core + lit[1:]

        def side_of(slot: int) -> float:
            """-1 wants the left end, +1 the right, 0 no preference."""
            if not previous:
                return 0.0
            best, score = 0.0, 0.0
            n = len(previous)
            for position, prev_slot in enumerate(previous):
                w = wanted.get(requirements[slot].type, {}).get(requirements[prev_slot].type, 0.0)
                if w > score:
                    score = w
                    best = -1.0 if position < n / 2 else 1.0
            return best

        lit.sort(key=side_of)

        # A core room with a host in this band goes beside that host, not
        # wherever the middle happens to be. Utility belongs against the
        # kitchen wall; an attached bathroom against its bedroom. Wedged
        # between the wrong pair it becomes the only way into one of them.
        from aip.engines.architecture.programme import PRIVATE_HOST

        left_end, right_end = lit[0], lit[-1]
        near_left: list[int] = []
        near_right: list[int] = []
        middle: list[int] = []
        for c in core:
            hosts = PRIVATE_HOST.get(requirements[c].type, ())
            ctype = requirements[c].type
            bath_host = ctype is RoomType.BATHROOM
            if requirements[left_end].type in hosts or (
                bath_host and requirements[left_end].attached_bathroom
            ):
                near_left.append(c)
            elif requirements[right_end].type in hosts or (
                bath_host and requirements[right_end].attached_bathroom
            ):
                near_right.append(c)
            else:
                middle.append(c)
        return [left_end] + near_left + middle + near_right + lit[1:]

    arranged: list[list[int]] = []
    for group in groups:
        arranged.append(arrange(group, arranged[-1] if arranged else []))
    groups = arranged

    # The passage is not a room in a band; it is a band. A hall is a thin
    # strip across the whole width of the house with rooms opening off both
    # sides, and that is the only shape in which it can serve every bedroom
    # behind it. Packed as one cell among the bathrooms it touches two
    # neighbours and serves neither.
    passages = list(passage)
    # A single bedroom band deeper than a room should be is not a band but
    # a row of slots eight metres long; it is planned as a spine instead.
    deep_band = bool(frontage) and any(
        sum(areas[g] for g in band) / frontage > 5.0 for band in private_bands
    )
    use_spine = bool(passages) and (
        len(private_bands) > 1 or (not private_bands and bool(service)) or deep_band
    )
    if passages and not use_spine:
        # Insert at the seam: immediately before the first band that holds a
        # bedroom. Everything the household shares - living, dining, kitchen,
        # puja, utility - sits on the near side of the passage; everything
        # private sits beyond it. Placing the seam after the last *public*
        # room instead would push the kitchen behind the passage with the
        # bedrooms, which is where it kept ending up.
        private = {RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
                   RoomType.CHILDREN_BEDROOM}
        seam = len(groups)
        for index, group in enumerate(groups):
            if any(requirements[g].type in private for g in group):
                seam = index
                break
        groups.insert(seam, list(passages))
        # The stair and any toilet the floor keeps go into the band beyond
        # the passage as core cells, between its lit ends. Put beside the
        # passage in its own band they shortened it, and the bedroom under
        # the stair cell had to be entered through the stair.
        if hall_core:
            if seam + 1 < len(groups):
                band = groups[seam + 1]
                groups[seam + 1] = band[:1] + hall_core + band[1:]
            else:
                groups.append(list(hall_core))
    elif not passages and hall_core:
        groups[0] = groups[0][:1] + hall_core + groups[0][1:] if groups else [list(hall_core)]

    # Within a band, cut along the frontage; between bands, cut across it.
    # Band order runs from the road inward, so the first group must land on the
    # road side of the envelope.
    def band_tree(group: list[int]) -> Node:
        """One band: cells side by side along the frontage.

        A small core room in a deep band comes out as a slot - a bathroom
        0.8 m wide and 4.6 m long, a foyer a metre across - because a band
        cell is as deep as the band. Two such rooms next to each other are
        stacked instead, one behind the other in the band's depth, which is
        how a practice draws two bathrooms between two bedrooms.
        """
        if len(group) == 1:
            return Leaf(group[0])
        order = list(group)
        depth_est = (sum(areas[g] for g in order) / frontage) if frontage else None

        def too_narrow(g: int) -> bool:
            if depth_est is None or depth_est <= 0:
                return False
            width = areas[g] / depth_est
            floor = MIN_CLEAR_WIDTH.get(requirements[g].type, MIN_ROOM_DIMENSION)
            return width < floor or depth_est / max(width, 1e-6) > 2.8

        from aip.engines.architecture.programme import is_through, may_enter

        bedroom_types = {RoomType.MASTER_BEDROOM, RoomType.BEDROOM,
                         RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM}

        def can_pair(i: int) -> bool:
            """May order[i+1] sit behind order[i], away from the passage?

            Only if its door can come from the room in front of it, or it is
            a bathroom with a bedroom beside the pair to be attached to. A
            bathroom stacked behind the staircase is a bathroom nobody can
            reach except through the stair.
            """
            a, b = order[i], order[i + 1]
            if needs_light(a) or needs_light(b):
                return False
            if requirements[b].type is RoomType.STAIRCASE:
                return False        # the stair meets the passage, always
            if not (too_narrow(a) or too_narrow(b)):
                return False
            if is_through(requirements[a].type) and may_enter(requirements[b].type, requirements[a].type):
                return True
            if requirements[b].type is RoomType.BATHROOM:
                beside = [order[j] for j in (i - 1, i + 2) if 0 <= j < len(order)]
                return any(requirements[x].type in bedroom_types for x in beside)
            return False

        units: list[list[int]] = []
        i = 0
        while i < len(order):
            # Two small rooms that can pair with each other do, rather than
            # one of them pairing with the stair and the other standing
            # alone as a slot.
            leave_stair = (
                requirements[order[i]].type is RoomType.STAIRCASE
                and i + 2 < len(order) and can_pair(i + 1)
            )
            if i + 1 < len(order) and can_pair(i) and not leave_stair:
                units.append([order[i], order[i + 1]])
                i += 2
            else:
                units.append([order[i]])
                i += 1

        def unit_area(u: list[int]) -> float:
            return sum(areas[g] for g in u)

        def unit_tree(u: list[int]) -> Node:
            if len(u) == 1:
                return Leaf(u[0])
            a, b = u
            ratio = min(0.85, max(0.15, areas[a] / (areas[a] + areas[b])))
            # The first of the pair takes the road side: the foyer in front
            # of the puja, the stair in front of the store.
            if road_at_high_end:
                return Split(vertical=not road_along_y, ratio=1 - ratio, left=Leaf(b), right=Leaf(a))
            return Split(vertical=not road_along_y, ratio=ratio, left=Leaf(a), right=Leaf(b))

        def along(us: list[list[int]]) -> Node:
            if len(us) == 1:
                return unit_tree(us[0])
            total = sum(unit_area(u) for u in us) or 1.0
            cut_index = 1
            acc = 0.0
            for i, u in enumerate(us):
                acc += unit_area(u)
                if acc >= total / 2:
                    cut_index = max(1, min(len(us) - 1, i + 1))
                    break
            left, right = us[:cut_index], us[cut_index:]
            la = sum(unit_area(u) for u in left) or 1.0
            ra = sum(unit_area(u) for u in right) or 1.0
            return Split(
                vertical=road_along_y,     # cuts along the frontage
                ratio=min(0.88, max(0.12, la / (la + ra))),
                left=along(left),
                right=along(right),
            )

        return along(units)

    def stack(bands_list: list[list[int]]) -> Node:
        if len(bands_list) == 1:
            return band_tree(bands_list[0])
        first, rest = bands_list[0], bands_list[1:]
        fa = sum(areas[g] for g in first) or 1.0
        ra = sum(areas[g] for band in rest for g in band) or 1.0
        ratio = min(0.88, max(0.12, fa / (fa + ra)))
        first_tree, rest_tree = band_tree(first), stack(rest)
        # `left` is the low-coordinate side. When the road is at the high end
        # the front band must go on the right/top, so the halves swap.
        if road_at_high_end:
            return Split(vertical=not road_along_y, ratio=1 - ratio,
                         left=rest_tree, right=first_tree)
        return Split(vertical=not road_along_y, ratio=ratio,
                     left=first_tree, right=rest_tree)

    # Two rear bands cannot both open off a horizontal hall: the second sits
    # behind the first with no contact. Every real plan with three or more
    # bedrooms solves this the same way - the passage turns to run
    # front-to-back through the private zone with rooms on both sides, a
    # central spine rather than a cross-strip. So when the bedrooms need more
    # than one band, the passage becomes a column, the private rooms are
    # dealt into a left and a right column beside it, and the spine's near
    # end meets the dining band, which is its legal way in.
    if use_spine:
        # The spine plan. The passage runs straight back from the living room
        # with rooms on both sides. Dining, kitchen and utility stack at the
        # head of one column - dining against the living room and the spine,
        # kitchen behind it, utility behind that - and the bedrooms fill the
        # rest of both columns with their bathrooms between them. The spine's
        # near end therefore meets the living room, which is its legal way in;
        # a spine that ends against the kitchen or the utility has none.
        def is_private_band(group: list[int]) -> bool:
            return any(requirements[g].type in private_types for g in group)

        # Pull the service rooms out of whatever band they sit in and keep
        # the remainder of that band. Dropping a band because it contained
        # one service room is how the living room, the foyer and the puja
        # vanished from the plan whenever the open-plan variant put the
        # dining room at the front with them.
        front_groups: list[list[int]] = []
        service_rooms: list[int] = []
        for g in groups:
            if g is passages or is_private_band(g) or (
                g and all(x in hall_core or x in passages for x in g)
            ):
                continue
            keep = [x for x in g if requirements[x].type not in service_types]
            service_rooms += [x for x in g if requirements[x].type in service_types]
            if keep:
                front_groups.append(keep)
        rear = [g for g in groups if g is not passages and is_private_band(g)]

        # Service block in its natural order: dining at the head.
        order = {RoomType.DINING: 0, RoomType.FAMILY: 0, RoomType.KITCHEN: 1,
                 RoomType.PANTRY: 2, RoomType.UTILITY: 3, RoomType.LAUNDRY: 3,
                 RoomType.STORE: 4}
        service_rooms.sort(key=lambda x: order.get(requirements[x].type, 5))

        # The stair heads the second column, against the living band and the
        # spine, where it stacks over the floor below. A downstairs toilet
        # sits behind it, off the hall.
        columns: list[list[int]] = [list(service_rooms), list(hall_core)]
        totals = [sum(areas[x] for x in service_rooms), sum(areas[x] for x in hall_core)]
        # Two columns and a passage need about 7 m of frontage: two rooms
        # at the statutory 2.4 m, a metre of passage, and walls. Narrower
        # than that the passage runs down one side with every room off it,
        # which is how a row house is planned.
        single_loaded = frontage is not None and frontage < 7.0
        if single_loaded:
            # Only the private zone sits beside the passage. The service
            # rooms stay a band across the house in front of it, with the
            # dining room at the passage's end so the passage has its legal
            # way in; nine rooms in one column made every one a strip.
            if service_rooms:
                band = [x for x in service_rooms if requirements[x].type is not RoomType.DINING]
                band += [x for x in service_rooms if requirements[x].type is RoomType.DINING]
                front_groups.append(band)
            columns = [list(hall_core), []]
            totals = [sum(areas[x] for x in hall_core), 0.0]

        anchors = [g for band in rear for g in band if requirements[g].type in private_types]
        served = [g for band in rear for g in band if requirements[g].type not in private_types]
        # Master first, to the lighter column; then the rest, balancing area.
        anchors.sort(key=lambda g: (requirements[g].type is not RoomType.MASTER_BEDROOM, -areas[g]))
        for g in anchors:
            side = 0 if single_loaded or totals[0] <= totals[1] else 1
            columns[side].append(g)
            totals[side] += areas[g]

        from aip.engines.architecture.programme import PRIVATE_HOST as _HOSTS

        bath_count = [0, 0]
        inserted = [0, 0]
        for g in served:
            kind = requirements[g].type
            hosts = _HOSTS.get(kind, ())
            side = None
            # An attached bathroom goes beside the room that asked for it.
            if kind is RoomType.BATHROOM:
                for candidate in (0, 1):
                    if any(requirements[a].attached_bathroom and requirements[a].type in private_types
                           and a in columns[candidate] for a in columns[candidate]) and bath_count[candidate] == 0:
                        side = candidate
                        break
            if side is None:
                for candidate in (0, 1):
                    if any(requirements[a].type in hosts for a in columns[candidate]):
                        side = candidate
                        break
            if side is None:
                # Spread the common bathrooms so each column has one.
                side = 0 if bath_count[0] <= bath_count[1] else 1
            if single_loaded:
                side = 0
            if kind is RoomType.BATHROOM:
                bath_count[side] += 1
            # Insert after the first private room in that column, so the
            # bathroom sits between bedrooms rather than at the far end.
            # Later insertions go after earlier ones, so the en-suite stays
            # against its bedroom instead of being pushed off by the balcony.
            col = columns[side]
            first_private = next((i for i, x in enumerate(col) if requirements[x].type in private_types), None)
            at = first_private + 1 if first_private is not None else len(col)
            at += inserted[side]
            col.insert(min(at, len(col)), g)
            inserted[side] += 1
            totals[side] += areas[g]

        from aip.engines.architecture.programme import is_through as _is_through
        from aip.engines.architecture.programme import may_enter as _may_enter

        def column(rooms_in: list[int], width_est: float | None, spine_on_low_side: bool) -> Node:
            """One column beside the spine, its rooms stacked front to back.

            A small room the full width of the column is a slot: a bathroom
            5 m wide and a metre deep. Two such rooms in a row share it
            instead, side by side, the one that meets the spine on the
            inside. The stair always takes the spine side; a bathroom on the
            outside is then the bathroom of the bedroom in the next row.
            """
            if len(rooms_in) == 1:
                return Leaf(rooms_in[0])

            def shallow(g: int) -> bool:
                if not width_est or width_est <= 0:
                    return False
                floor = MIN_CLEAR_WIDTH.get(requirements[g].type, MIN_ROOM_DIMENSION)
                return areas[g] / width_est < floor

            def row_pair(i: int) -> tuple[int, int] | None:
                """(inner, outer) when rooms i and i+1 may share a row."""
                a, b = rooms_in[i], rooms_in[i + 1]
                ta, tb = requirements[a].type, requirements[b].type
                if needs_light(a) or needs_light(b):
                    return None
                if not (shallow(a) or shallow(b)):
                    return None
                if ta is RoomType.STAIRCASE and tb is RoomType.STAIRCASE:
                    return None
                inner, outer = (a, b) if ta is RoomType.STAIRCASE or (
                    tb is not RoomType.STAIRCASE and areas[a] >= areas[b]) else (b, a)
                ti, to = requirements[inner].type, requirements[outer].type
                if not _may_enter(ti, RoomType.CORRIDOR):
                    return None
                if _is_through(ti) and _may_enter(to, ti):
                    return (inner, outer)
                if to is RoomType.BATHROOM:
                    beside = [rooms_in[j] for j in (i - 1, i + 2) if 0 <= j < len(rooms_in)]
                    if any(requirements[x].type in _BEDROOMS for x in beside):
                        return (inner, outer)
                return None

            # A shallow bathroom with the stair in the column but not beside
            # it moves next to the stair, so the two share a row: the stair
            # on the spine, the bathroom outside it against the bedroom in
            # the next row. That is the classic stair-and-bath core.
            rooms_in = list(rooms_in)
            shallow_baths = [g for g in rooms_in
                             if requirements[g].type is RoomType.BATHROOM and shallow(g)]
            stair_at = next((i for i, g in enumerate(rooms_in)
                             if requirements[g].type is RoomType.STAIRCASE), None)
            if len(shallow_baths) >= 2:
                # Two shallow bathrooms share a row with each other: the
                # inner one off the passage, the outer one attached to the
                # bedroom in the next row.
                first, second = shallow_baths[0], shallow_baths[1]
                rooms_in.remove(second)
                rooms_in.insert(rooms_in.index(first) + 1, second)
            elif shallow_baths and stair_at is not None:
                g = shallow_baths[0]
                if abs(rooms_in.index(g) - stair_at) > 1:
                    rooms_in.remove(g)
                    stair_at = next(i for i, x in enumerate(rooms_in)
                                    if requirements[x].type is RoomType.STAIRCASE)
                    rooms_in.insert(stair_at + 1, g)

            rows: list[Node] = []
            row_areas: list[float] = []
            i = 0
            while i < len(rooms_in):
                pair = row_pair(i) if i + 1 < len(rooms_in) else None
                if pair is None:
                    g = rooms_in[i]
                    rows.append(Leaf(g))
                    # A room alone in a row is as deep as its area allows
                    # at the column's width - and no shallower than its
                    # clear width. A 9 m2 study in a 4.6 m column is drawn
                    # 2.4 m deep and a little larger, not 2.0 m and a slot.
                    floor = MIN_CLEAR_WIDTH.get(requirements[g].type, MIN_ROOM_DIMENSION)
                    row_areas.append(max(areas[g], floor * width_est) if width_est else areas[g])
                    i += 1
                    continue
                inner, outer = pair
                ratio = min(0.85, max(0.15, areas[inner] / (areas[inner] + areas[outer])))
                # `left` is the low-coordinate side; the inner cell goes
                # wherever the spine is.
                if spine_on_low_side:
                    rows.append(Split(vertical=road_along_y, ratio=ratio,
                                      left=Leaf(inner), right=Leaf(outer)))
                else:
                    rows.append(Split(vertical=road_along_y, ratio=1 - ratio,
                                      left=Leaf(outer), right=Leaf(inner)))
                row_areas.append(areas[inner] + areas[outer])
                i += 2

            def pile(nodes: list[Node], sizes: list[float]) -> Node:
                if len(nodes) == 1:
                    return nodes[0]
                fa = sizes[0] or 1.0
                ra = sum(sizes[1:]) or 1.0
                ratio = min(0.88, max(0.12, fa / (fa + ra)))
                rest = pile(nodes[1:], sizes[1:])
                if road_at_high_end:
                    return Split(vertical=not road_along_y, ratio=1 - ratio, left=rest, right=nodes[0])
                return Split(vertical=not road_along_y, ratio=ratio, left=nodes[0], right=rest)

            return pile(rows, row_areas)

        spine_area = sum(areas[g] for g in passages)
        body_area = totals[0] + totals[1] + spine_area
        w_spine = min(0.22, max(0.09, spine_area / body_area))
        if frontage:
            w_spine = max(w_spine, min(0.3, 1.15 / frontage))
        w_left = (1 - w_spine) * (totals[0] / (totals[0] + totals[1]) if (totals[0] + totals[1]) else 0.5)
        w_right = 1 - w_spine - w_left
        col_w = [(w_left * frontage) if frontage else None, (w_right * frontage) if frontage else None]

        if columns[1]:
            inner = Split(vertical=road_along_y,
                          ratio=min(0.9, max(0.1, w_spine / (w_spine + w_right))),
                          left=band_tree(passages), right=column(columns[1], col_w[1], True))
        else:
            inner = band_tree(passages)
        if columns[0]:
            body = Split(vertical=road_along_y, ratio=min(0.9, max(0.1, w_left)),
                         left=column(columns[0], col_w[0], False), right=inner)
        else:
            body = inner

        if not front_groups:
            return body
        fa = sum(areas[x] for g in front_groups for x in g) or 1.0
        ratio = min(0.88, max(0.12, fa / (fa + body_area)))
        front_tree = stack(front_groups)
        if road_at_high_end:
            return Split(vertical=not road_along_y, ratio=1 - ratio, left=body, right=front_tree)
        return Split(vertical=not road_along_y, ratio=ratio, left=front_tree, right=body)

    return stack(groups)


# ---------------------------------------------------------------------------
# Genome
# ---------------------------------------------------------------------------


#: Fitness of a genome nobody has scored yet. Scores themselves may be negative -
#: a plan with a slot-shaped bedroom costs more than the plan earns - so "not
#: yet scored" cannot be any small negative number.
UNSCORED = -1e9


@dataclass(slots=True)
class Genome:
    """A candidate layout: a tree plus the slot-to-requirement assignment.

    `pinned` names slots whose room never changes - the staircase's - so that
    swapping assignments cannot trade the fixed stair for a bedroom.
    """

    tree: Node
    assignment: list[int]         # assignment[slot] -> requirement index
    fitness: float = UNSCORED
    breakdown: dict[str, float] = field(default_factory=dict)
    pinned: frozenset[int] = frozenset()

    def copy(self) -> Genome:
        return Genome(self.tree.copy(), list(self.assignment), pinned=self.pinned)


def mutate(genome: Genome, rng: random.Random, strength: float = 1.0) -> Genome:
    """Apply one random structural or parametric mutation."""
    child = genome.copy()
    splits = _collect_splits(child.tree)

    choice = rng.random()
    movable = [i for i in range(len(child.assignment)) if i not in child.pinned]
    if choice < 0.34 and len(movable) > 1:
        # Swap which rooms occupy two slots - changes orientation and adjacency
        # without disturbing the geometry, so it explores the assignment space.
        i, j = rng.sample(movable, 2)
        child.assignment[i], child.assignment[j] = child.assignment[j], child.assignment[i]
    elif choice < 0.68 and splits:
        # Nudge a cut position - fine-grained area tuning.
        node = rng.choice(splits)
        delta = rng.gauss(0.0, 0.09 * strength)
        node.ratio = min(0.90, max(0.10, node.ratio + delta))
    elif choice < 0.86 and splits:
        # Flip a cut orientation - reshapes rooms dramatically.
        rng.choice(splits).vertical ^= True
    elif splits:
        # Rotate a subtree, reordering the rooms beneath it.
        node = rng.choice(splits)
        node.left, node.right = node.right, node.left
        node.ratio = 1.0 - node.ratio
    return child


def crossover(a: Genome, b: Genome, rng: random.Random) -> Genome:
    """Take geometry from one parent and assignment from the other.

    Recombining subtrees directly would break the invariant that every slot
    appears exactly once, so the crossover operates on the two independent axes
    of the genome instead. It is cheap and preserves validity by construction.
    """
    child = Genome(a.tree.copy(), list(b.assignment), pinned=a.pinned)
    if rng.random() < 0.5:
        splits_a = _collect_splits(child.tree)
        splits_b = _collect_splits(b.tree)
        for node_a, node_b in zip(splits_a, splits_b, strict=False):
            if rng.random() < 0.4:
                node_a.ratio = node_b.ratio
                node_a.vertical = node_b.vertical
    return child


def _splits_above(node: Node, slot: int) -> list[Split]:
    """The free cuts on the path from the root to one room's cell."""
    if isinstance(node, Leaf):
        return []
    for child in (node.left, node.right):
        if slot in {leaf.slot for leaf in child.leaves()}:
            below = _splits_above(child, slot)
            return below if node.locked else [node, *below]
    return []


def _snap_tree(
    node: Node, box: BoundingBox, xs: Sequence[float], ys: Sequence[float],
    rng: random.Random, tol: float = 0.7, p: float = 0.8,
) -> None:
    """Move each free cut onto the nearest wall line of the floor below.

    A wall that does not stand on a wall must be carried by a beam, and the
    audit counts how much of an upper floor's wall length lands on the floor
    beneath. A cut within `tol` metres of a lower wall costs nothing to move and
    puts the wall where the structure already is.
    """
    if isinstance(node, Leaf):
        return
    if node.locked:
        ratio = node.ratio
    else:
        lo, hi = (box.min_x, box.max_x) if node.vertical else (box.min_y, box.max_y)
        lines = xs if node.vertical else ys
        cut = lo + (hi - lo) * node.ratio
        best = min(lines, key=lambda v: abs(v - cut), default=None)
        if best is not None and abs(best - cut) < tol and lo + 0.8 < best < hi - 0.8 and rng.random() < p:
            node.ratio = (best - lo) / (hi - lo)
        ratio = min(0.92, max(0.08, node.ratio))
    if node.vertical:
        cut_at = box.min_x + box.width * ratio
        left = BoundingBox(box.min_x, box.min_y, cut_at, box.max_y)
        right = BoundingBox(cut_at, box.min_y, box.max_x, box.max_y)
    else:
        cut_at = box.min_y + box.height * ratio
        left = BoundingBox(box.min_x, box.min_y, box.max_x, cut_at)
        right = BoundingBox(box.min_x, cut_at, box.max_x, box.max_y)
    _snap_tree(node.left, left, xs, ys, rng, tol, p)
    _snap_tree(node.right, right, xs, ys, rng, tol, p)


def _collect_splits(node: Node, *, include_locked: bool = False) -> list[Split]:
    """The cuts the search may change: every one that is not part of the skeleton."""
    out: list[Split] = []
    stack: list[Node] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Split):
            if include_locked or not current.locked:
                out.append(current)
            stack.append(current.left)
            stack.append(current.right)
    return out


# ---------------------------------------------------------------------------
# The staircase carve
# ---------------------------------------------------------------------------

#: Leaf placeholders in a skeleton. The stair is `_STAIR_MARK`; the free
#: regions the carve leaves are `-1`, `-2`, `-3`, and are replaced by the
#: subtrees the search grows inside them.
_STAIR_MARK = -100

#: Narrowest strip worth leaving beside the stair. Narrower than a room is
#: wide, it cannot hold one, so the stair is pushed to the end instead.
_MIN_STRIP = 2.2


@dataclass(slots=True)
class StairPlan:
    """Where the staircase goes, decided once for every floor.

    `skeleton` is a tree of *locked* cuts that carves the stair's rectangle
    out of the envelope; its leaves are the stair and up to three free regions
    (`regions`, in placeholder order: the body first, then the strips before
    and after the stair along the wall). Each floor's search grows its rooms
    inside those regions, so the stair is the same rectangle on every floor
    by construction rather than by persuasion.
    """

    rect: BoundingBox
    skeleton: Node
    regions: list[BoundingBox]
    label: str = ""
    #: True for a stair against a side wall, with the body of the plan beside
    #: it and room for a passage to run across from its flank.
    side: bool = True

    def build(self, subtrees: dict[int, Node], stair_slot: int) -> Node:
        """The skeleton with each region's subtree and the stair slot plugged in."""
        return _plug(self.skeleton.copy(), subtrees, stair_slot)


def _plug(node: Node, subtrees: dict[int, Node], stair_slot: int) -> Node:
    if isinstance(node, Leaf):
        if node.slot == _STAIR_MARK:
            return Leaf(stair_slot)
        return subtrees.get(node.slot, node)
    node.left = _plug(node.left, subtrees, stair_slot)
    node.right = _plug(node.right, subtrees, stair_slot)
    return node


def _band_tree(
    along_x: bool, length: float, pre: float, stair: float, post: float
) -> tuple[Node, list[int]]:
    """Locked cuts along a band: [strip before] [stair] [strip after].

    Returns the tree and the placeholder ids it uses, `-2` for the strip
    before the stair and `-3` for the one after.
    """
    used: list[int] = []
    if pre > 1e-6 and post > 1e-6:
        used = [-2, -3]
        inner = Split(along_x, stair / (stair + post), Leaf(_STAIR_MARK), Leaf(-3), locked=True)
        return Split(along_x, pre / length, Leaf(-2), inner, locked=True), used
    if pre > 1e-6:
        return Split(along_x, pre / length, Leaf(-2), Leaf(_STAIR_MARK), locked=True), [-2]
    if post > 1e-6:
        return Split(along_x, stair / length, Leaf(_STAIR_MARK), Leaf(-3), locked=True), [-3]
    return Leaf(_STAIR_MARK), used


def carve_stair(
    env: BoundingBox, edge: str, thickness: float, length: float, offset: float,
    label: str = "", side: bool = True,
) -> StairPlan | None:
    """Carve a `thickness` x `length` stair against one wall of the envelope.

    `edge` names the wall it hugs: ``low_x``, ``high_x``, ``low_y`` or
    ``high_y``. The stair is `thickness` deep into the plan and `length` along
    the wall, starting `offset` metres from the wall's low end. Everything
    else - the strips beside it along the wall, and the body of the plan - is
    left as free regions. Returns None when the stair does not fit.
    """
    along_x = edge in ("low_y", "high_y")          # the wall runs along x
    wall_len = env.width if along_x else env.height
    depth = env.height if along_x else env.width
    if thickness > depth - 1e-6 or length > wall_len + 1e-6 or offset < -1e-6:
        return None
    pre, post = offset, wall_len - offset - length
    if post < -1e-6:
        return None
    post = max(0.0, post)
    # Strips are either absent or big enough to be a room.
    for strip in (pre, post):
        if 1e-6 < strip < _MIN_STRIP - 1e-6:
            return None
    body_depth = depth - thickness
    if body_depth < _MIN_STRIP:
        return None

    if edge == "low_x":
        rect = BoundingBox(env.min_x, env.min_y + offset, env.min_x + thickness, env.min_y + offset + length)
        body = BoundingBox(env.min_x + thickness, env.min_y, env.max_x, env.max_y)
        band_first, pieces_along_x = True, False
        strips = [BoundingBox(env.min_x, env.min_y, env.min_x + thickness, env.min_y + pre),
                  BoundingBox(env.min_x, rect.max_y, env.min_x + thickness, env.max_y)]
        cut = thickness / env.width
        vertical = True
    elif edge == "high_x":
        rect = BoundingBox(env.max_x - thickness, env.min_y + offset, env.max_x, env.min_y + offset + length)
        body = BoundingBox(env.min_x, env.min_y, env.max_x - thickness, env.max_y)
        band_first, pieces_along_x = False, False
        strips = [BoundingBox(env.max_x - thickness, env.min_y, env.max_x, env.min_y + pre),
                  BoundingBox(env.max_x - thickness, rect.max_y, env.max_x, env.max_y)]
        cut = (env.width - thickness) / env.width
        vertical = True
    elif edge == "low_y":
        rect = BoundingBox(env.min_x + offset, env.min_y, env.min_x + offset + length, env.min_y + thickness)
        body = BoundingBox(env.min_x, env.min_y + thickness, env.max_x, env.max_y)
        band_first, pieces_along_x = True, True
        strips = [BoundingBox(env.min_x, env.min_y, env.min_x + pre, env.min_y + thickness),
                  BoundingBox(rect.max_x, env.min_y, env.max_x, env.min_y + thickness)]
        cut = thickness / env.height
        vertical = False
    else:  # high_y
        rect = BoundingBox(env.min_x + offset, env.max_y - thickness, env.min_x + offset + length, env.max_y)
        body = BoundingBox(env.min_x, env.min_y, env.max_x, env.max_y - thickness)
        band_first, pieces_along_x = False, True
        strips = [BoundingBox(env.min_x, env.max_y - thickness, env.min_x + pre, env.max_y),
                  BoundingBox(rect.max_x, env.max_y - thickness, env.max_x, env.max_y)]
        cut = (env.height - thickness) / env.height
        vertical = False

    band, used = _band_tree(pieces_along_x, wall_len, pre, length, post)
    body_leaf = Leaf(-1)
    if band_first:
        root: Node = Split(vertical, cut, band, body_leaf, locked=True)
    else:
        root = Split(vertical, cut, body_leaf, band, locked=True)
    regions = [body]
    if -2 in used:
        regions.append(strips[0])
    if -3 in used:
        # Placeholder ids follow the order in `regions`: body is -1, then the
        # strips that exist take -2 and -3. Renumber so the ids are dense.
        regions.append(strips[1])
    if used == [-3]:
        _renumber(root, {-3: -2})
    return StairPlan(rect=rect, skeleton=root, regions=regions, label=label, side=side)


def _renumber(node: Node, mapping: dict[int, int]) -> None:
    if isinstance(node, Leaf):
        node.slot = mapping.get(node.slot, node.slot)
        return
    _renumber(node.left, mapping)
    _renumber(node.right, mapping)


def _row_tree(seq: list[int], areas: Sequence[float], vertical: bool) -> Node:
    """Rooms in a single row, every cut parallel, each cell as wide as its area asks."""
    if len(seq) == 1:
        return Leaf(seq[0])
    head = areas[seq[0]]
    rest = sum(areas[x] for x in seq[1:]) or 1.0
    return Split(vertical, min(0.88, max(0.12, head / (head + rest))), Leaf(seq[0]),
                 _row_tree(seq[1:], areas, vertical))


def _depth_sorted(slots: Sequence[int], requirements: Sequence[RoomRequirement], rng: random.Random) -> list[int]:
    """Slots ordered front of the plot to back, with enough jitter to vary."""
    from aip.engines.architecture.programme import DEPTH_BAND

    def key(slot: int) -> float:
        low, high = DEPTH_BAND.get(requirements[slot].type, (0.4, 0.7))
        return (low + high) / 2 + rng.gauss(0.0, 0.10)

    return sorted(slots, key=key)


def build_banded_tree(
    ordered: Sequence[int],
    areas: Sequence[float],
    box: BoundingBox,
    rng: random.Random,
    *,
    depth_along_y: bool,
    road_at_high_end: bool,
    band_levels: int = 2,
) -> Node:
    """A tree whose first cuts run across the depth axis, front to back.

    `ordered` runs from the road inward. The first `band_levels` cuts divide
    the region into bands across the depth axis, the front rooms on the road
    side; below that every cut goes across the region's longer side. The
    result has the gradient a house has and rooms that are not slots.
    """
    if len(ordered) == 1:
        return Leaf(ordered[0])
    total = sum(areas[s] for s in ordered) or 1.0
    running = 0.0
    cut_index = 1
    for i, slot in enumerate(ordered):
        running += areas[slot]
        if running >= total / 2:
            cut_index = max(1, min(len(ordered) - 1, i + 1))
            break
    front, rear = list(ordered[:cut_index]), list(ordered[cut_index:])
    fa = sum(areas[s] for s in front) or 1.0
    ra = sum(areas[s] for s in rear) or 1.0
    share = min(0.88, max(0.12, fa / (fa + ra)))

    across_depth = band_levels > 0
    vertical = (not depth_along_y) if across_depth else box.width >= box.height
    # `vertical` cuts divide x. With depth along y, a cut across the depth axis
    # is horizontal (not vertical); with depth along x it is vertical.
    if across_depth:
        vertical = not depth_along_y
    ratio = (1.0 - share) if (across_depth and road_at_high_end) else share
    if vertical:
        cut = box.min_x + box.width * ratio
        low_box = BoundingBox(box.min_x, box.min_y, cut, box.max_y)
        high_box = BoundingBox(cut, box.min_y, box.max_x, box.max_y)
    else:
        cut = box.min_y + box.height * ratio
        low_box = BoundingBox(box.min_x, box.min_y, box.max_x, cut)
        high_box = BoundingBox(box.min_x, cut, box.max_x, box.max_y)
    if across_depth and road_at_high_end:
        left_slots, right_slots, left_box, right_box = rear, front, low_box, high_box
    else:
        left_slots, right_slots, left_box, right_box = front, rear, low_box, high_box
    nxt = band_levels - 1
    return Split(
        vertical=vertical, ratio=ratio,
        left=build_banded_tree(left_slots, areas, left_box, rng, depth_along_y=depth_along_y,
                               road_at_high_end=road_at_high_end, band_levels=nxt),
        right=build_banded_tree(right_slots, areas, right_box, rng, depth_along_y=depth_along_y,
                                road_at_high_end=road_at_high_end, band_levels=nxt),
    )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GeneratorConfig:
    population: int = 32
    generations: int = 50
    elite: int = 6
    tournament: int = 3
    mutation_rate: float = 0.75
    seed: int | None = None
    corridor_share: float = 0.10
    max_stagnation: int = 10
    #: Run the feasibility gate. Off only for callers that lay out a plan they
    #: were handed - an uploaded drawing - and must not be second-guessed.
    check_feasibility: bool = True
    #: Try the spine planner (an architect's parti) before the search.
    spine: bool = True
    #: Runs beyond the first three are made only while no clean plan has been
    #: found, and only while they fit the time budget (seconds, whole call).
    max_runs: int = 16
    time_budget: float = 10.5


#: Rooms that can receive the main entrance, in order of preference.
_ENTRY_ROOMS = (RoomType.FOYER, RoomType.LOBBY, RoomType.VERANDAH)
_BEDROOMS = frozenset({RoomType.MASTER_BEDROOM, RoomType.BEDROOM,
                       RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM})
_WET_TYPES = frozenset({RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER})
#: What an upstairs bathroom must not sit over: a leak above a kitchen, a dining
#: table or a shrine is a defect nobody accepts.
_NO_WET_ABOVE = frozenset({RoomType.KITCHEN, RoomType.DINING, RoomType.PUJA})


@dataclass(slots=True)
class _Assessment:
    """A programme prepared for some number of floors, and what each floor needs."""

    levels: int
    reqs: list[RoomRequirement]
    buckets: list[list[int]]
    minimum: list[float]
    comfort: list[float]
    target: list[float]


def _deal_rooms(
    reqs: Sequence[RoomRequirement],
    slots: list[int],
    regions: list[BoundingBox],
    rng: random.Random,
    below: Sequence[tuple[RoomType, BoundingBox]] = (),
) -> list[list[int]]:
    """Share the rooms out among the free regions the stair carve left.

    Region 0 is the body of the plan and takes whatever is left. Each strip
    beside the stair takes the one to three rooms whose areas best fill it,
    among the rooms that can be furnished in a strip that narrow: wet rooms,
    stores, the utility, a study, the terrace. A bedroom is 3 m across at the
    least, and a strip is 2.5; the passage is a strip of its own, not a cell
    in somebody else's.
    """
    # Never in a strip: the passage, the stair and the shrine. The big rooms -
    # living, dining, kitchen - only in a bay broad enough to be one of them.
    never = {RoomType.CORRIDOR, RoomType.LOBBY, RoomType.STAIRCASE, RoomType.PUJA,
             RoomType.FOYER, RoomType.VERANDAH, RoomType.GARAGE, RoomType.STUDY, RoomType.HOME_OFFICE}
    bulky = {RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN, RoomType.DRAWING, RoomType.FAMILY}
    groups: list[list[int]] = [[] for _ in regions]
    pool = list(slots)
    order = list(range(1, len(regions)))
    rng.shuffle(order)

    def contribution(slot: int, area: float) -> float:
        r = reqs[slot]
        return min(r.target_area, area) if r.notes == FILL_NOTE else r.target_area

    for position, ri in enumerate(order):
        box = regions[ri]
        area = box.area
        still_to_fill = len(order) - position - 1
        narrow = min(box.width, box.height) + 0.05
        biggest_fill = max((s for s in pool if reqs[s].notes == FILL_NOTE),
                           key=lambda s: reqs[s].target_area, default=None)
        cands = [
            s for s in pool
            if reqs[s].type not in never
            and (reqs[s].type not in bulky or narrow >= 3.6)
            and s != biggest_fill
            and FURNISH_MIN.get(reqs[s].type, (0.0, 0.0))[0] <= narrow
        ]
        rng.shuffle(cands)
        # What is under this strip on the floor below: a bathroom over the
        # kitchen is the defect a leak turns into.
        over_dry = 0.0
        for kind, under in below:
            dx = min(box.max_x, under.max_x) - max(box.min_x, under.min_x)
            dy = min(box.max_y, under.max_y) - max(box.min_y, under.min_y)
            if dx > 0 and dy > 0 and kind in _NO_WET_ABOVE:
                over_dry += dx * dy
        over_dry /= area
        best: tuple[float, tuple[int, ...]] | None = None
        # Leave at least one candidate for every strip still to be filled.
        for n in range(1, min(3, max(1, len(cands) - still_to_fill)) + 1):
            for combo in itertools.combinations(cands[:12], n):
                total = sum(contribution(s, area) for s in combo)
                cost = abs(total - area) / area + 0.05 * n + 0.12 * rng.random()
                if over_dry > 0.2 and any(reqs[s].type in _WET_TYPES for s in combo):
                    cost += 1.5
                lit = sum(1 for s in combo if reqs[s].type.is_habitable)
                cost += 0.25 * max(0, lit - 1)
                if best is None or cost < best[0]:
                    best = (cost, combo)
        if best is not None:
            groups[ri] = list(best[1])
            pool = [s for s in pool if s not in best[1]]
    groups[0] = pool
    # A region with no room would be a hole in the plan: borrow from the
    # fullest group, never the passage. `_plan_stairs` only offers carves the
    # floors can fill, so there is something to lend.
    for ri in range(len(groups)):
        while not groups[ri]:
            donors = [i for i in range(len(groups)) if len(groups[i]) > 1]
            donor = max(donors, key=lambda i: len(groups[i]))
            keep = (RoomType.CORRIDOR, RoomType.LOBBY, RoomType.KITCHEN, RoomType.DINING, RoomType.PUJA,
                    RoomType.LIVING, RoomType.FOYER)
            movable = [x for x in groups[donor] if reqs[x].type not in keep]
            movable = movable or [x for x in groups[donor] if reqs[x].type not in (RoomType.CORRIDOR, RoomType.LOBBY)]
            pick = min(movable or groups[donor], key=lambda x: reqs[x].target_area)
            groups[ri].append(pick)
            groups[donor].remove(pick)
    return groups


@dataclass(slots=True)
class _Facts:
    """What the surrogate needs to know about one requirement, worked out once."""

    type: RoomType
    target: float
    floor: float
    habitable: bool
    needs_light: bool
    needs_daylight: bool
    bearing: float | None
    orient_weight: float
    entry: bool
    circulation: bool
    passage: bool
    corridor: bool
    stair: bool
    fill: bool
    through: bool
    cap: float | None
    furnish: tuple[float, float] | None
    bedroom: bool
    wet: bool
    outdoor: bool
    ensuite: bool
    utility: bool
    asked: float
    sized: bool


#: Bearing of each of the sixteen compass sectors, indexed as `bearing_to_direction` does.
_SECTOR_BEARING: tuple[float, ...] = tuple(
    bearing_to_direction(i * 22.5).bearing for i in range(16)
)

#: The rooms a passage may open from. On an upper floor the stair is the one.
_PUBLIC_FOR_PASSAGE = frozenset({
    RoomType.LIVING, RoomType.DINING, RoomType.FOYER,
    RoomType.FAMILY, RoomType.LOBBY, RoomType.STAIRCASE,
})


#: How much a point of quality severity costs a plan in the ranking.
_PARTI_LEAD = 1.0
_QUALITY_WEIGHT = 0.02


def _doors_to_hosts(plan: FloorPlan) -> None:
    """A balcony asked for off a particular room opens from that room, not the hall."""
    from aip.domain.plan import Opening, OpeningKind

    for level in plan.levels:
        by_id = {r.id: r for r in level.rooms}
        for bal in level.rooms:
            note = str(bal.metadata.get("notes", "")).lower()
            if bal.type is not RoomType.BALCONY or "opens off the" not in note:
                continue
            host_name = note.split("opens off the", 1)[1].strip(" .")
            hosts = [r for r in level.rooms if r.type.value.replace("_", " ") == host_name]
            if not hosts:
                continue
            host = hosts[0]
            shared = [w for w in level.walls if bal.id in w.rooms and host.id in w.rooms and w.length >= 1.0]
            if not shared:
                continue
            for w in level.walls:
                if bal.id in w.rooms:
                    w.openings = [o for o in w.openings if not (o.kind.is_door and o.connects and bal.id in o.connects)]
            wall = max(shared, key=lambda w: w.length)
            wall.openings.append(Opening(kind=OpeningKind.SLIDING_DOOR, wall_id=wall.id, position=0.5,
                                         width=min(1.8, wall.length - 0.3), height=2.1, sill_height=0.0,
                                         connects=(host.id, bal.id)))


#: A two-storey house is spread over one storey on a plot at least this big,
#: m² (about 8,000 sq ft), when its rooms fit comfortably on one floor of it.
SPREAD_PLOT = 750.0

#: How many runs of the parti planner, and the seconds they share, before
#: the corridor planners are let in.
PARTI_RUNS = 30
PARTI_SECONDS = 30.0

#: A passage longer than this is a corridor, not a hall or a landing.
LONG_PASSAGE = 6.0


def _long_passage(plan: FloorPlan) -> bool:
    return any(r.type in (RoomType.CORRIDOR, RoomType.LOBBY) and max(r.bbox.width, r.bbox.height) > LONG_PASSAGE
               for lv in plan.levels for r in lv.rooms)


def _passage_tier(plan: FloorPlan) -> int:
    """0: no passage at all, the rooms open off one another; 1: a short hall; 2: a corridor."""
    if _long_passage(plan):
        return 2
    return int(any(r.type in (RoomType.CORRIDOR, RoomType.LOBBY) for lv in plan.levels for r in lv.rooms))


def _pristine(plan: FloorPlan) -> bool:
    return not plan.metadata["guardrail"] and not plan.metadata["quality"]


def _weight(plan: FloorPlan) -> float:
    """Ordering for plans with something to say: guardrail failures first, then quality."""
    return 10.0 * len(plan.metadata["guardrail"]) + _severity(plan.metadata["quality"])


def _severity(problems: list[str]) -> float:
    """How bad a list of guardrail findings is: a room too big is a lesser fault
    than a room that cannot be used, a bedroom entered through another, or a
    kitchen that does not meet the dining room. A room too big reads "is N m²,
    over the M m²"; a toilet "over the Kitchen" is a leak over the stove and a
    Vastu fault, and weighs as the serious kind."""
    return sum(1.0 if ("m², over the" in p or "passages take" in p) else 3.0 for p in problems)


def _loose_touch(a: BoundingBox, b: BoundingBox, tol: float = 0.02, need: float = 0.3) -> bool:
    """Do two rooms share any wall at all (more than `need` m)? A shrine and a toilet
    need only a hand's breadth of common wall to be a problem."""
    if (abs(a.max_x - b.min_x) < tol or abs(a.min_x - b.max_x) < tol) and (
        min(a.max_y, b.max_y) - max(a.min_y, b.min_y) > need
    ):
        return True
    return (abs(a.max_y - b.min_y) < tol or abs(a.min_y - b.max_y) < tol) and (
        min(a.max_x, b.max_x) - max(a.min_x, b.min_x) > need
    )


def _touch_matrix(rects: list[BoundingBox]) -> list[list[bool]]:
    """`m[i][j]` is True when rooms i and j share enough wall to hang a door."""
    n = len(rects)
    tol = 0.02
    need = max(tol, DOOR_WALL)
    m = [[False] * n for _ in range(n)]
    for i in range(n):
        a = rects[i]
        for j in range(i + 1, n):
            b = rects[j]
            if (
                (abs(a.max_x - b.min_x) < tol or abs(a.min_x - b.max_x) < tol)
                and min(a.max_y, b.max_y) - max(a.min_y, b.min_y) > need
            ) or (
                (abs(a.max_y - b.min_y) < tol or abs(a.min_y - b.max_y) < tol)
                and min(a.max_x, b.max_x) - max(a.min_x, b.min_x) > need
            ):
                m[i][j] = m[j][i] = True
    return m


class LayoutGenerator:
    """Produces buildable, optimised floorplans from a client brief."""

    #: Rooms past their comfortable size on a large plot (see `_grow_programme`);
    #: a class default, so per-floor workers made without __init__ have it too.
    _cap_boost = 1.0

    def __init__(self, brief: ClientBrief, config: GeneratorConfig | None = None) -> None:
        from aip.engines.architecture.programme import apply_defaults

        # A client states rooms and areas; they never state that the kitchen
        # should be near the dining room, because nobody thinks to write down
        # what everybody knows. Without it the search has no opinion on where
        # anything goes relative to anything else, and produces plans that pass
        # every metric while being unusable. The programme is the architect's
        # contribution to the brief, so the generator supplies it.
        self.brief = apply_defaults(brief)
        self.config = config or GeneratorConfig()
        self.rng = random.Random(self.config.seed)
        # The programme and its split across levels are fixed here, once.
        # They used to be recomputed on every realisation, and each pass
        # appended another staircase: thirteen stair cells on one floor was
        # the visible symptom. Nothing below may add to either again.
        #
        # The feasibility gate runs first and may change what "the programme"
        # is - add a floor, drop a study, draw rooms smaller - or refuse with
        # `InfeasibleBriefError`. Whatever it decided is in `self.advisories`.
        self.advisories: list[str] = []
        self._bedrooms = bedrooms_in(self.brief.expanded_requirements())
        # Set by the gate when the plot is generous enough to grow the house:
        # the footprint to draw, and how much the stair and the passage scale.
        self._footprint_area: float | None = None
        # How far past their comfortable size rooms may grow (toward the luxury
        # ceiling) when a large plot would otherwise be left mostly lawn.
        self._cap_boost = 1.0
        self._stair_scale = 1.0
        self._compact_stair = False
        self._spread = False            # set when a two-storey brief is drawn on one floor (see `_resolve_programme`)
        self._passage_scale = 1.0
        self._resolve_programme()
        self._envelope = self._buildable_envelope()
        # Set on a per-level worker: which floor it lays out.
        self._level_index = 0
        # The staircase is decided once, now, for every floor.
        self._facts: list[_Facts] | None = None
        self._door_ok: list[list[bool]] = []
        # How each plan was made, per floor, so a near-miss can be repaired.
        self._recipes: dict[str, list[tuple[LayoutGenerator, Genome]]] = {}
        # The rooms of the floor below, for the floor being searched.
        self._below: list[tuple[RoomType, BoundingBox]] = []
        self._below_xs: list[float] = []
        self._below_ys: list[float] = []
        self._below_lines: tuple[dict, dict] | None = None
        self._carried_cache: dict[tuple, float] = {}
        self._stairs: list[StairPlan] = self._plan_stairs()
        self._stair: StairPlan | None = self._stairs[0] if self._stairs else None

    # ------------------------------------------------------------- public --

    def generate(
        self,
        count: int = 3,
        *,
        fitness_fn: Callable[[FloorPlan], tuple[float, dict[str, float]]] | None = None,
    ) -> list[FloorPlan]:
        """Evolve `count` diverse, high-quality plans.

        Uses a **surrogate-assisted** search. Evolution is driven by a cheap
        geometric proxy that scores raw rectangles - area fit, proportion,
        external-wall access, adjacency and orientation - without materialising
        walls, doors or windows. The expensive exact evaluation, which builds the
        full plan and runs the complete physics and code suite, is then applied
        only to the elite survivors, which are re-ranked on the true objective.

        This is the standard remedy for expensive-evaluation evolutionary search,
        and here it is the difference between roughly 25 seconds and under a
        second per scheme - which is what makes the platform usable interactively
        inside an architect's website rather than only as a batch job.

        Diversity is enforced rather than hoped for: independent runs seed from
        different random states, and near-identical schemes are filtered out. A
        committee reviewing three copies of the same plan learns nothing.

        Every candidate then passes the guardrail: a plan with a room nobody
        can walk to properly, a floor with two passages or two staircases, or
        a cell too narrow to be a room is not offered, however it scored.
        """
        fitness_fn = fitness_fn or self._default_fitness
        scored: list[tuple[float, dict[str, float], FloorPlan]] = []
        signatures: set[tuple] = set()

        runs = max(3, count + 1)
        started = time.perf_counter()
        # The spine planner first: an architect's parti fitted to the programme.
        # When it yields enough clean, distinct schemes the search is skipped.
        spine_clean = 0
        for plan in self._spine_candidates():
            signature = self._signature(plan)
            if signature in signatures:
                continue
            signatures.add(signature)
            exact, breakdown = fitness_fn(plan)
            # The parti is the plan an architect draws; while one is clean it leads.
            lead = _PARTI_LEAD if plan.metadata.get("planner") == "parti" else 0.0
            plan.metadata["_lead"] = lead
            scored.append((exact + lead - _QUALITY_WEIGHT * min(6.0, _severity(plan.metadata["quality"])), breakdown, plan))
            spine_clean += not plan.metadata["guardrail"]
        # Most of the time goes to searching; the rest is kept for repairing the
        # near-misses the search leaves (see `_repair`).
        search_budget = 0.8 * self.config.time_budget
        run = 0
        tried: dict[int, float] = {}           # carve index -> best finding weight it produced
        while spine_clean < count:
            if run >= 1:
                # After the first run, another is made only if it fits the time
                # budget - a tall house takes several seconds a run - and, once
                # the usual number have been made, only while nothing clean has
                # turned up.
                elapsed = time.perf_counter() - started
                if elapsed + elapsed / run > search_budget:
                    break
                if run >= runs:
                    clean_so_far = sum(1 for item in scored if _pristine(item[2]))
                    if clean_so_far >= count or run >= self.config.max_runs:
                        break
            seed = None if self.config.seed is None else self.config.seed + run * 7919
            option = 0
            if self._stairs:
                # Each run carves the stair somewhere; within a run every floor
                # shares the one carve. Carves differ a great deal in how often
                # they lead to a clean plan, so the search explores a new one
                # every other run and spends the rest on the best so far.
                if not tried:
                    option = 0
                elif run % 2 == 1 and len(tried) < len(self._stairs):
                    option = len(tried)
                else:
                    option = min(tried, key=lambda k: tried[k])
                self._stair = self._stairs[option]
            for plan in self._candidates(seed):
                signature = self._signature(plan)
                if signature in signatures:
                    continue
                signatures.add(signature)
                self._judge(plan)
                tried[option] = min(tried.get(option, 1e9), _weight(plan))
                exact, breakdown = fitness_fn(plan)
                scored.append((exact - _QUALITY_WEIGHT * min(6.0, _severity(plan.metadata["quality"])), breakdown, plan))
            run += 1

        deadline = started + self.config.time_budget
        wanted = count - sum(1 for item in scored if _pristine(item[2]))
        if wanted > 0:
            near = sorted(
                (item for item in scored if not _pristine(item[2])),
                key=lambda item: (_weight(item[2]), -item[0]),
            )
            for item in near[: max(wanted + 2, 3)]:
                if time.perf_counter() >= deadline:
                    break
                fixed = self._repair(item[2], deadline)
                if fixed is not item[2]:
                    exact, breakdown = fitness_fn(fixed)
                    scored.append((exact - _QUALITY_WEIGHT * min(6.0, _severity(fixed.metadata["quality"])),
                                   breakdown, fixed))
        self._recipes.clear()

        # A client who keeps Vastu strictly gets the finalists tuned for it.
        from aip.domain.brief import VastuStance

        if self.brief.vastu in (VastuStance.STRICT, VastuStance.ORTHODOX):
            scored.sort(key=lambda item: -item[0])
            tune_until = time.perf_counter() + 2.5
            for i, (exact, breakdown, plan) in enumerate(scored[:6]):
                if plan.metadata["guardrail"]:
                    continue
                tuned = self._vastu_tune(plan, fitness_fn, exact, tune_until)
                if tuned is not None:
                    scored[i] = tuned

        # On a plot the house is meant to grow into (see `_grow_programme`), a
        # scheme left at its comfortable size leaves the lawn the client did not
        # ask for, so it ranks below the schemes that use the plot.
        if self._cap_boost > 1.0 and self._footprint_area:
            plate = 0.85 * self._footprint_area

            def unfilled(plan: FloorPlan) -> float:
                ground = plan.level_at(0) if plan.levels else None
                return max(0.0, 1.0 - (sum(r.area for r in ground.rooms) if ground else 0.0) / plate)

            def cost(plan: FloorPlan) -> float:
                # A parti that leaves a sixth of the plate unbuilt has not used the
                # plot, and loses the lead its plan would otherwise earn it.
                gap = unfilled(plan)
                return 0.6 * gap + (plan.metadata.get("_lead", 0.0) if gap > 0.15 else 0.0)

            scored = [(exact - cost(plan), breakdown, plan) for exact, breakdown, plan in scored]

        clean = [item for item in scored if not item[2].metadata["guardrail"]]
        flawed = [item for item in scored if item[2].metadata["guardrail"]]
        # Rooms that open straight off one another come first, then a plan with
        # a short hall; a passage running the length or width of the house is
        # the corridor plan again, offered only when there is nothing else at
        # all - two sound schemes are better than three with a corridor in one.
        selected: list[tuple[float, dict[str, float], FloorPlan]] = []
        for tier in (0, 1, 2):
            if tier == 2 and selected:
                break
            pool = [item for item in clean if _passage_tier(item[2]) == tier]
            if pool and len(selected) < count:
                selected += self._select_diverse(pool, count - len(selected))
        if not selected and flawed:
            # Nothing clean at all. Offer the least-broken rather than nothing,
            # but say so on the plan and in the log: a silent fallback is how a
            # bad plan reaches a client looking like a good one. While anything
            # sound exists, fewer schemes are offered rather than a broken one.
            flawed.sort(key=lambda item: (_weight(item[2]), -item[0]))
            for item in flawed[: count - len(selected)]:
                selected.append(item)
                log_event(
                    logger, "layout.guardrail", level=30,
                    problems=item[2].metadata["guardrail"][:6],
                )

        plans: list[FloorPlan] = []
        for index, (exact, breakdown, plan) in enumerate(selected):
            plan.metadata["fitness"] = round(exact - plan.metadata.pop("_lead", 0.0), 4)
            plan.metadata["fitness_breakdown"] = breakdown
            plan.metadata["advisories"] = list(self.advisories)
            plan.metadata["feasibility"] = self.feasibility.to_dict()
            plan.name = f"Scheme {chr(ord('A') + index)}"
            plans.append(plan)

        log_event(
            logger, "layout.generated",
            requested=count, evaluated=len(scored), produced=len(plans),
            rejected=len(flawed),
            best=max((p.metadata.get("fitness", 0.0) for p in plans), default=0.0),
        )
        return plans

    def _spine_candidates(self) -> Iterator[FloorPlan]:
        """Plans from the spine planner, one per variant that fits, judged."""
        from aip.engines.architecture.spine import SpinePlanner, variants

        if not self.config.spine:
            return
        try:
            levels = [[self.requirements[i] for i in bucket] for bucket in self.level_buckets]
            roads = self.brief.site.road_directions
            road = roads[0] if roads else None
            diagonal = road is not None and len(road.cardinal.value) == 2
            sides = (0, 1) if diagonal else (0,)
            # The planners size the house from its rooms and leave the rest as
            # garden, so they are also given the whole plot inside the setbacks:
            # the coverage-scaled box is a guess at the house's shape, and on a
            # deep or wide plot the wrong one.
            outer = self._site_box()
            boxes = [self._envelope] + ([outer] if outer is not None and outer.area > self._envelope.area + 1.0 else [])
            planners = [SpinePlanner(box, road, len(levels) > 1, outer=outer, side=k) for box in boxes for k in sides]
        except Exception as exc:  # noqa: BLE001 - the search is the fallback
            log_event(logger, "layout.spine_failed", error=str(exc))
            return
        from aip.engines.architecture.rowhouse import RowHousePlanner, row_variants

        rows = [RowHousePlanner(box, road, len(levels) > 1, outer=outer, side=k) for box in boxes for k in sides]
        cover = self.brief.site.max_footprint if self.brief.site.plot_area else 0.0
        made = 0
        # The parti planner first: the plan an architect would draw. Then the
        # spine and, on a narrow plot, the row house, as the alternatives.
        from aip.engines.architecture.corridor import CorridorPlanner, corridor_variants
        from aip.engines.architecture.parti import PartiPlanner

        site = self.brief.site
        elders = any(getattr(o, "role", "") == "elder" for o in getattr(self.brief, "occupants", []) or [])
        partis = [PartiPlanner(outer or self._envelope, road, len(levels) > 1, cover=cover, side=k,
                               north_angle=site.north_angle, prefer=self._vastu_direction,
                               vastu_weight=self.brief.vastu.tradition_weight, elders=elders,
                               seed=(self.config.seed or 0) + 31 * k + 977 * run,
                               compact_stair=self._compact_stair, landing="none" if run % 2 == 0 else None,
                               boost=self._cap_boost)
                  for k in sides for run in range(PARTI_RUNS)]
        # Several runs of the parti from different starts: one run often finds a
        # single sound plan, and the client should have three to choose from.
        # Every other run keeps upstairs to rooms off the stair's landing, so
        # the plan without a passage is always looked for; the rest may also
        # try a small lobby at the head of the stair.
        # A narrow plot also gets the row house: no hall, a short passage between two bands.
        tries = [(p, None) for p in partis] + [(p, v) for p in planners for v in variants()] \
            + [(r, v) for r in rows if r.fits() for v in row_variants()]
        def build(who, rooms) -> FloorPlan | None:
            if not rooms:
                return None
            if cover and sum(r.area for r in rooms[0]) > cover * 1.02:
                return None            # over the ground coverage the plot allows
            # A bath or wardrobe drawn away from the bedroom it was meant for is
            # not that bedroom's: a bath opens off the passage for everyone, a
            # wardrobe is a store. Left as a suite, the door placer will not give
            # it a door, and an otherwise sound plan is lost.
            for lv in rooms:
                by_id = {r.id: r for r in lv}
                for r in lv:
                    owner = by_id.get(r.metadata.get("suite_of"))
                    if owner is None or _shared_length(r, owner) >= DOOR_WALL:
                        continue
                    r.metadata.pop("suite_of", None)
                    if r.type in (RoomType.BATHROOM, RoomType.TOILET):
                        r.metadata["common"] = True
                    elif r.type is RoomType.WARDROBE:
                        r.type, r.name = RoomType.STORE, "Store"
            # The master bedroom is the largest one: where a plain bedroom came
            # out bigger and is as well served (its own bath, or the master has
            # none), the two change names rather than the plan being lost.
            for lv in rooms:
                suites = {r.metadata.get("suite_of") for r in lv if r.type is RoomType.BATHROOM}
                masters = [r for r in lv if r.type is RoomType.MASTER_BEDROOM]
                others = [r for r in lv if r.type in (RoomType.BEDROOM, RoomType.CHILDREN_BEDROOM)]
                if len(masters) == 1 and others:
                    m, big = masters[0], max(others, key=lambda r: r.area)
                    if big.area > 1.05 * m.area and (big.id in suites or m.id not in suites):
                        m.type, big.type = big.type, m.type
                        m.name, big.name = big.name, m.name
                        for key in ("target_area", "brief_area", "notes"):
                            if key in m.metadata and key in big.metadata:
                                m.metadata[key], big.metadata[key] = big.metadata[key], m.metadata[key]
            # Walls on the house's own outline are its outside walls; the
            # buildable envelope may be larger (the rest is garden).
            xs = [p.x for lv in rooms for r in lv for p in r.polygon]
            ys = [p.y for lv in rooms for r in lv for p in r.polygon]
            envelope = self._envelope
            self._envelope = BoundingBox(min(xs), min(ys), max(xs), max(ys))
            self._open_outline = True
            try:
                plan = self._assemble(rooms)
            finally:
                self._envelope = envelope
                self._open_outline = False
            plan.metadata["planner"] = ("parti" if isinstance(who, PartiPlanner)
                                        else "row" if isinstance(who, RowHousePlanner)
                                        else "corridor" if isinstance(who, CorridorPlanner) else "spine")
            _doors_to_hosts(plan)
            self._judge(plan)
            # A suite's bath opens from its own bedroom, or the suite is not one.
            for lv in plan.levels:
                linked = {frozenset(o.connects) for w in lv.walls for o in w.openings if o.kind.is_door and o.connects}
                for r in lv.rooms:
                    owner = r.metadata.get("suite_of")
                    if owner and r.type is RoomType.BATHROOM and frozenset((r.id, owner)) not in linked:
                        plan.metadata["guardrail"].append(f"level {lv.index}: a bedroom's own bathroom does not open from it")
            # Everything the client asked for must be in the plan.
            have = {r.type for lv in plan.levels for r in lv.rooms}
            if RoomType.VERANDAH in have:
                have.add(RoomType.BALCONY)          # on a single floor the balcony is the sit-out
            names = {r.name for lv in plan.levels for r in lv.rooms}
            for req in self.requirements:
                if "Requested" in (req.notes or "") and req.type not in have:
                    plan.metadata["guardrail"].append(f"the {req.type.label.lower()} the client asked for is missing")
                elif req.label and req.label not in names:
                    plan.metadata["guardrail"].append(f"the {req.label.lower()} the client asked for is missing")
            # A toilet over the kitchen, the puja or the dining table is a
            # plumbing leak waiting to happen and a Vastu fault: mark it so the
            # variant without it wins.
            from shapely.geometry import Polygon as _P
            for lo, hi in zip(plan.levels, plan.levels[1:]):
                below = [(r, _P([(q.x, q.y) for q in r.polygon])) for r in lo.rooms
                         if r.type in (RoomType.KITCHEN, RoomType.PUJA, RoomType.DINING)]
                for r in hi.rooms:
                    if r.type in (RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER):
                        pr = _P([(q.x, q.y) for q in r.polygon])
                        for b_room, pb in below:
                            if pr.intersection(pb).area > 0.3 * pr.area:
                                plan.metadata["quality"].append(f"level {hi.index}: {r.display_name()} over the {b_room.display_name()}")
                                break
            return plan

        clean_yielded = 0
        short_partis: list[FloorPlan] = []
        parti_started = None
        for who, v in tries:
            try:
                if isinstance(who, PartiPlanner):
                    # Another run of the parti only while it is needed: three
                    # different sound plans without a passage are enough, and
                    # the runs share a few seconds between them.
                    if parti_started is None:
                        parti_started = time.perf_counter()
                    elif time.perf_counter() - parti_started > PARTI_SECONDS or sum(
                        1 for i, a in enumerate(short_partis)
                        if all(self._similarity(a, b) < 0.5 for b in short_partis[:i])
                    ) >= 3:
                        continue
                    # The parti's own score ranks its sketches; the judge has the
                    # last word on the best of them, and the best few are offered.
                    judged = [p for p in (build(who, rooms) for rooms in who.plans(levels, count=20, samples=400, climbs=20)) if p is not None]
                    order = {id(p): k for k, p in enumerate(judged)}
                    judged.sort(key=lambda p: (_weight(p), order[id(p)]))
                    # The clean sketches all go to the selector, so it can offer
                    # different partis rather than three takes on one.
                    batch = [p for p in judged if not p.metadata["guardrail"]][:8] or judged[:5]
                else:
                    batch = [build(who, who.plan(levels, v))]
            except Exception as exc:  # noqa: BLE001
                log_event(logger, "layout.spine_failed", error=str(exc))
                continue
            for plan in batch:
                if plan is None:
                    continue
                made += 1
                clean_yielded += not plan.metadata.get("guardrail")
                if isinstance(who, PartiPlanner) and not plan.metadata.get("guardrail") and _passage_tier(plan) == 0:
                    short_partis.append(plan)
                yield plan
        # None of the searching planners found a plan that holds: the corridor
        # planner builds one that does, whatever the plot.
        if clean_yielded < 2:
            corridors = []
            for k in sides:
                cp = CorridorPlanner(outer or self._envelope, road, len(levels) > 1, outer=outer, side=k)
                cp.cover = cover
                corridors.append(cp)
            clean_corr = 0
            for cp in corridors:
                for v in corridor_variants():
                    if clean_corr >= 3:
                        break
                    try:
                        plan = build(cp, cp.plan(levels, v))
                    except Exception as exc:  # noqa: BLE001
                        log_event(logger, "layout.corridor_failed", error=str(exc))
                        continue
                    if plan is None:
                        continue
                    made += 1
                    clean_corr += not plan.metadata.get("guardrail")
                    yield plan
        log_event(logger, "layout.spine", variants=made)

    def _candidates(self, seed: int | None) -> Iterator[FloorPlan]:
        """One run of the search: the elite plans it converged on.

        A single-level brief evolves one partition. A multi-level brief evolves
        each floor as its own partition of the same footprint: the ground
        floor first, then every upper floor against it, with its staircase
        pulled onto the footprint of the one below. One tree for the whole
        house, realised on the ground and then thinned to the ground-floor
        rooms, is what left holes in the plan where the bedrooms had been.
        """
        # A tall house multiplies every ground-floor scheme by its upper floors,
        # so it keeps fewer of them.
        elite_out = 2 if len(self.level_buckets) >= 3 else max(3, self.config.elite // 2)
        if len(self.level_buckets) == 1:
            self.rng = random.Random(seed)
            for genome in self._evolve(elite_out=elite_out):
                plan = self._assemble([self._realise_level(genome, 0)])
                self._recipes[plan.id] = [(self, genome)]
                yield plan
            return

        ground = self._worker(0, seed)
        for k, genome in enumerate(ground._evolve(elite_out=elite_out)):
            rooms_by_level = [ground._realise_level(genome, 0)]
            recipe = [(ground, genome)]
            for level_index in range(1, len(self.level_buckets)):
                worker = self._worker(
                    level_index,
                    None if seed is None else seed + 31 * level_index + 7 * k,
                    budget=0.75,
                )
                worker.set_below([(r.type, r.bbox) for r in rooms_by_level[level_index - 1]])
                best = worker._evolve(elite_out=1)[0]
                rooms_by_level.append(worker._realise_level(best, level_index))
                recipe.append((worker, best))
            plan = self._assemble(rooms_by_level)
            self._recipes[plan.id] = recipe
            yield plan

    #: Rooms the Vastu tuning never moves: the stair stacks, passages and the
    #: foyer belong to the entrance, outdoor rooms belong to their faces.
    _TUNE_FIXED = frozenset({RoomType.STAIRCASE, RoomType.CORRIDOR, RoomType.LOBBY, RoomType.FOYER, RoomType.SHAFT,
                             RoomType.COURTYARD, RoomType.VERANDAH, RoomType.BALCONY, RoomType.TERRACE, RoomType.GARAGE})

    def _vastu_tune(self, plan: FloorPlan, fitness_fn, score: float, deadline: float):
        """Swap rooms of similar size on each floor, steepest gain first,
        keeping a swap only while the plan's whole fitness rises (Vastu is
        part of it, never all of it) and the plan stays clean. Returns the
        tuned (score, breakdown, plan), or None when nothing improved."""
        from aip.engines.architecture.editor import apply_edits

        lead = plan.metadata.get("_lead", 0.0)
        current, best_score, best_breakdown = plan, score, None
        for _ in range(4):
            best = None
            for level in current.levels:
                rooms = [r for r in level.rooms if r.type not in self._TUNE_FIXED and r.area > 0]
                for i, a in enumerate(rooms):
                    for b in rooms[i + 1:]:
                        if a.type is b.type or not 0.6 <= a.area / b.area <= 1.67:
                            continue
                        if time.perf_counter() > deadline:
                            break
                        try:
                            new, applied, _refused = apply_edits(current, [{"op": "swap", "a": a.id, "b": b.id}])
                        except Exception:  # noqa: BLE001 - a swap that cannot be made is skipped
                            continue
                        if not applied:
                            continue
                        self._judge(new)
                        if new.metadata["guardrail"]:
                            continue
                        exact, breakdown = fitness_fn(new)
                        cand = exact + lead - _QUALITY_WEIGHT * min(6.0, _severity(new.metadata["quality"]))
                        if cand > best_score + 0.002 and (best is None or cand > best[0]):
                            best = (cand, breakdown, new)
            if best is None:
                break
            best_score, best_breakdown, current = best
        if current is plan:
            return None
        current.metadata["_lead"] = lead
        current.metadata["vastu_tuned"] = True
        log_event(logger, "layout.vastu_tuned", plan=current.id, before=round(score, 4), after=round(best_score, 4))
        return best_score, best_breakdown, current

    def _judge(self, plan: FloorPlan) -> None:
        """Write the guardrail and quality findings onto the plan."""
        plan.metadata["guardrail"], plan.metadata["quality"] = self._findings(plan)

    def _repair(self, plan: FloorPlan, deadline: float, max_steps: int = 160) -> FloorPlan:
        """Close the last few gaps in a plan the search left almost right.

        The surrogate is a proxy, and the guardrail is the judge: a bedroom
        2.87 m wide, a bathroom over the puja, a third door in the master. A
        near-miss is closed best by asking the judge directly. Each step makes
        one small change to one floor - nudge a cut, or swap two rooms - rebuilds
        the plan and keeps the change if the guardrail finds no more to say
        than before. It is the architect's last hour at the drawing board, and
        it costs about nine milliseconds a step.
        """
        recipe = self._recipes.get(plan.id)
        if recipe is None:
            return plan
        genomes = [genome.copy() for _w, genome in recipe]
        rooms = [w._realise_level(g, i) for i, ((w, _g), g) in enumerate(zip(recipe, genomes, strict=True))]
        current = plan
        guard, quality = list(plan.metadata["guardrail"]), list(plan.metadata["quality"])
        score = 10.0 * len(guard) + _severity(quality)
        if score <= 0:
            return plan
        improved = False
        fits: dict[int, float] = {}
        for _step in range(max_steps):
            if score <= 0 or time.perf_counter() >= deadline:
                break
            # Work on a floor that has something wrong with it.
            tagged = [int(p.split()[1].rstrip(":")) for p in guard + quality
                      if p.startswith("level ") and p.split()[1].rstrip(":").isdigit()]
            level = self.rng.choice(tagged) if tagged and self.rng.random() < 0.8 else self.rng.randrange(len(recipe))
            if level >= len(recipe):
                continue
            worker, _ = recipe[level]
            trial = genomes[level].copy()
            splits = _collect_splits(trial.tree)
            roll = self.rng.random()
            # Most moves go where the trouble is: the cuts above a room the
            # findings name. A room cannot be widened by moving a cut on the
            # far side of the plan.
            named = [p for p in guard + quality if p.startswith(f"level {level}:")]
            culprit_slots: list[int] = []
            for text in named:
                for slot, ri in enumerate(trial.assignment):
                    if worker.requirements[ri].type.label in text:
                        culprit_slots.append(slot)
            if roll < 0.55 and culprit_slots:
                path = _splits_above(trial.tree, self.rng.choice(culprit_slots))
                if path:
                    node = self.rng.choice(path)
                    node.ratio = min(0.9, max(0.1, node.ratio + self.rng.gauss(0.0, 0.06)))
            elif roll < 0.70 and splits:
                for node in self.rng.sample(splits, min(len(splits), self.rng.choice((1, 1, 2)))):
                    node.ratio = min(0.9, max(0.1, node.ratio + self.rng.gauss(0.0, 0.05)))
            elif roll < 0.92:
                movable = [i for i in range(len(trial.assignment)) if i not in trial.pinned]
                if len(movable) < 2:
                    continue
                a, b = self.rng.sample(movable, 2)
                trial.assignment[a], trial.assignment[b] = trial.assignment[b], trial.assignment[a]
            elif splits:
                self.rng.choice(splits).vertical ^= True
            # The search's own opinion of the move is a veto: a swap that clears
            # one finding by putting the living room where the courtyard was is
            # not a repair.
            if level not in fits:
                fits[level] = worker._surrogate_fitness(genomes[level], worker._envelope, worker.level_buckets)
            fit_after = worker._surrogate_fitness(trial, worker._envelope, worker.level_buckets)
            if fit_after < fits[level] - 0.08:
                continue
            new_rooms = list(rooms)
            new_rooms[level] = worker._realise_level(trial, level)
            candidate = self._assemble(new_rooms)
            g2, q2 = self._findings(candidate)
            trial_score = 10.0 * len(g2) + _severity(q2)
            if trial_score <= score:
                if trial_score < score:
                    improved = True
                genomes[level], rooms, guard, quality, score, current = trial, new_rooms, g2, q2, trial_score, candidate
                fits[level] = fit_after
        if not improved:
            return plan
        current.metadata["guardrail"], current.metadata["quality"] = guard, quality
        current.metadata["repaired"] = True
        return current

    def _worker(
        self, level_index: int, seed: int | None, *, budget: float = 1.0,
    ) -> LayoutGenerator:
        """A generator for one floor: this floor's rooms in the shared footprint."""
        worker = object.__new__(LayoutGenerator)
        worker.brief = self.brief
        cfg = self.config
        # A floor with twenty rooms costs twice what one with ten does per
        # evaluation; give it a proportionally smaller search so a large house
        # is not the slow one.
        crowd = min(1.0, (14 / max(1, len(self.level_buckets[level_index]))) ** 0.5)
        worker.config = GeneratorConfig(
            population=max(16, int(cfg.population * budget * crowd)),
            generations=max(14, int(cfg.generations * budget * crowd)),
            elite=cfg.elite, tournament=cfg.tournament, mutation_rate=cfg.mutation_rate,
            seed=seed, corridor_share=cfg.corridor_share, max_stagnation=cfg.max_stagnation,
            check_feasibility=False, max_runs=cfg.max_runs, time_budget=cfg.time_budget,
        )
        worker.rng = random.Random(seed)
        worker.requirements = [self.requirements[i] for i in self.level_buckets[level_index]]
        worker.level_buckets = [list(range(len(worker.requirements)))]
        worker._envelope = self._envelope
        worker._level_index = level_index
        worker._footprint_area = self._footprint_area
        worker._bedrooms = self._bedrooms
        worker._stair_scale = self._stair_scale
        worker._compact_stair = self._compact_stair
        worker._passage_scale = self._passage_scale
        worker._stairs = []
        worker._stair = self._stair
        worker._facts = None
        worker._door_ok = []
        worker._below = []
        worker._below_xs = []
        worker._below_ys = []
        worker._below_lines = None
        worker._carried_cache = {}
        worker.advisories = []
        return worker

    # ------------------------------------------------------------ guardrail --

    def _sanity(self, plan: FloorPlan) -> list[str]:
        """What is wrong with a plan that no score should be allowed to excuse.

        These are the failures a client sees in the first ten seconds - a
        bedroom reached through the kitchen, three passages, a room a metre
        wide - and a fitness function that trades them against daylight has
        already lost the argument. A plan that lists anything here is not
        offered while a clean one exists.
        """
        return self._findings(plan)[0]

    def _findings(self, plan: FloorPlan) -> tuple[list[str], list[str]]:
        """(guardrail, quality): what makes a plan unusable, and what makes it merely poor.

        The guardrail is the first group - a room too narrow to be that room, a
        slot, a bedroom entered through another, a stair that does not stack. A
        plan with any of those is not offered while one without exists. The
        second group is what an architect would mark in red on a good plan: a
        bedroom that cannot take a bed, a passage that is a hall, a bathroom
        over the kitchen, a third door in the master. Those rank plans against
        each other and drive the search for something better; they do not by
        themselves make a plan unofferable.
        """
        from collections import Counter

        from aip.engines.architecture.programme import walkability

        quality: list[str] = []
        problems: list[str] = []
        multi = len(plan.levels) > 1
        if multi:
            # A staircase that does not stack is not a staircase: the flight
            # from one floor must arrive where the next one starts.
            rects = [
                next((r.bbox for r in level.rooms if r.type is RoomType.STAIRCASE), None)
                for level in plan.levels
            ]
            first = rects[0]
            if first is not None and any(
                r is not None and (abs(r.min_x - first.min_x) > 0.05 or abs(r.max_x - first.max_x) > 0.05
                                   or abs(r.min_y - first.min_y) > 0.05 or abs(r.max_y - first.max_y) > 0.05)
                for r in rects[1:]
            ):
                problems.append("staircase does not stack from floor to floor")
        for level in plan.levels:
            kinds = Counter(r.type for r in level.rooms)
            tag = f"level {level.index}"
            if multi and kinds[RoomType.STAIRCASE] != 1:
                problems.append(f"{tag}: {kinds[RoomType.STAIRCASE]} staircases")
            passages = kinds[RoomType.CORRIDOR] + kinds[RoomType.LOBBY]
            if passages > 1:
                problems.append(f"{tag}: {passages} passages")
            for room in level.rooms:
                short = min(room.bbox.width, room.bbox.height)
                floor = MIN_CLEAR_WIDTH.get(room.type, MIN_ROOM_DIMENSION)
                limit = aspect_limit(room.type)
                aspect = room.bbox.aspect_ratio
                # A slot is a guardrail failure beyond 2.2:1 for the rooms people
                # live in and 4:1 for the rest; between the room's own cap and
                # that it is only poor.
                hard = None if limit is None else (3.5 if room.type.is_habitable else 4.0)
                statutory = NBC_MIN_AREAS.get(room.type)
                if statutory is not None and room.type.is_habitable and room.area < statutory - 0.05:
                    # Under the code's own floor: the code officer would remove the scheme.
                    problems.append(f"{tag}: {room.display_name()} is {room.area:.1f} m2, under the {statutory:.1f} m2 the code requires")
                if short < floor - 0.05:
                    problems.append(f"{tag}: {room.display_name()} is {short:.1f} m wide")
                elif hard is not None and aspect > hard:
                    problems.append(f"{tag}: {room.display_name()} is a {aspect:.1f}:1 slot")
                elif limit is not None and aspect > limit + 0.05:
                    quality.append(f"{tag}: {room.display_name()} is a {aspect:.1f}:1 slot")
                if (cap := self._cap(room.type)) is not None and room.area > 1.08 * cap:
                    quality.append(f"{tag}: {room.display_name()} is {room.area:.0f} m², over the {cap:.0f} m² a room of its kind needs")
                if (need := FURNISH_MIN.get(room.type)) is not None and (
                    short < need[0] - 0.05 or max(room.bbox.width, room.bbox.height) < need[1] - 0.05
                ) and short >= floor - 0.05:
                    quality.append(
                        f"{tag}: {room.display_name()} is {short:.1f} x "
                        f"{max(room.bbox.width, room.bbox.height):.1f} m, too small to furnish "
                        f"({need[0]} x {need[1]} m needed)"
                    )
                # A landing lobby with doors on both sides is 2.2 m; a passage is a strip.
                if room.type in (RoomType.CORRIDOR, RoomType.LOBBY) and short > (2.4 if room.type is RoomType.LOBBY else 1.9):
                    quality.append(f"{tag}: {room.display_name()} is {short:.1f} m wide, a room and not a strip")
            built = sum(r.area for r in level.rooms) or 1.0
            share = sum(r.area for r in level.rooms
                        if r.type in (RoomType.CORRIDOR, RoomType.LOBBY)) / built
            if share > 0.12:
                quality.append(f"{tag}: passages take {share:.0%} of the floor")
            if len(level.rooms) > 1:
                for route in walkability(plan, level.index):
                    if not route.legal:
                        problems.append(f"{tag}: {route.room} {route.reason}")
        quality.extend(self._household_problems(plan))
        problems.extend(self._ensuite_problems(plan))
        return problems, quality

    @staticmethod
    def _ensuite_problems(plan: FloorPlan) -> list[str]:
        """With a bathroom for every bedroom, or one opening off a lesser
        bedroom, the master's bath is its own, not the one down the landing."""
        every = plan.all_rooms
        bath_each = sum(r.type is RoomType.BATHROOM for r in every) >= sum(r.type in _BEDROOMS for r in every)
        problems = []
        for level in plan.levels:
            by_id = {r.id: r for r in level.rooms}
            baths_of: dict[str, set[str]] = {r.id: set() for r in level.rooms}
            for wall in level.walls:
                for o in wall.openings:
                    if o.kind.is_door and o.connects and all(x in by_id for x in o.connects):
                        a, b = o.connects
                        if by_id[b].type is RoomType.BATHROOM:
                            baths_of[a].add(b)
                        if by_id[a].type is RoomType.BATHROOM:
                            baths_of[b].add(a)
            beds = [r for r in level.rooms if r.type in _BEDROOMS and r.type is not RoomType.MASTER_BEDROOM]
            for m in (r for r in level.rooms if r.type is RoomType.MASTER_BEDROOM):
                if not baths_of[m.id] and (bath_each or any(baths_of[b.id] for b in beds)):
                    problems.append(f"level {level.index}: the master bedroom has no bathroom of its own")
        return problems

    def _household_problems(self, plan: FloorPlan) -> list[str]:
        """The things a household checks on first reading the plan.

        Doors, adjacencies and what sits over what - all of them cheap on
        rectangles, and none of them something a fitness score should be able
        to trade away.
        """
        from collections import Counter

        problems: list[str] = []
        for level in plan.levels:
            tag = f"level {level.index}"
            rooms = level.rooms
            by_id = {r.id: r for r in rooms}
            count: Counter[str] = Counter()
            doors_of: dict[str, set[str]] = {r.id: set() for r in rooms}
            for wall in level.walls:
                for o in wall.openings:
                    if o.kind.is_door and o.connects and all(o.connects):
                        count[o.connects[0]] += 1
                        count[o.connects[1]] += 1
                        doors_of.setdefault(o.connects[0], set()).add(o.connects[1])
                        doors_of.setdefault(o.connects[1], set()).add(o.connects[0])
                        a, b = by_id.get(o.connects[0]), by_id.get(o.connects[1])
                        if a and b and ({a.type, b.type} & _WET_TYPES) and ({a.type, b.type} & {RoomType.KITCHEN, RoomType.DINING}):
                            problems.append(f"{tag}: {a.display_name()} opens into {b.display_name()}")
            lit = {rid for w in level.walls for o in w.openings if not o.kind.is_door for rid in w.rooms}
            for room in rooms:
                if room.type.is_habitable and room.id not in lit:
                    problems.append(f"{tag}: {room.display_name()} has no window")
            for room in rooms:
                if (not room.type.is_circulation and room.type not in _BEDROOMS
                        and room.type is not RoomType.TERRACE and count[room.id] > 3):
                    problems.append(f"{tag}: {room.display_name()} has {count[room.id]} doors")
            plate = sum(r.area for r in rooms) or 1.0
            for room in rooms:
                asked = float(room.metadata.get("brief_area", 0.0))
                if (
                    not room.type.is_outdoor and room.type is not RoomType.STAIRCASE
                    and ((asked > 0 and room.area > 1.6 * asked) or room.area > 0.28 * plate)
                ):
                    problems.append(f"{tag}: {room.display_name()} is {room.area:.0f} m², out of proportion to the plan")
                if room.type is RoomType.UTILITY:
                    if not any(w.kind is WallKind.EXTERIOR and room.id in w.rooms for w in level.walls):
                        problems.append(f"{tag}: the utility has no outside wall")
                    if not any(by_id[x].type is RoomType.KITCHEN for x in doors_of[room.id]) and any(
                            r.type is RoomType.KITCHEN for r in rooms):
                        problems.append(f"{tag}: the utility does not open off the kitchen")
                if room.type is RoomType.CORRIDOR and len(doors_of[room.id]) < 3:
                    problems.append(f"{tag}: the passage reaches only {len(doors_of[room.id])} rooms")
                if room.type is RoomType.DINING and any(by_id[x].type is RoomType.STAIRCASE for x in doors_of[room.id]):
                    problems.append(f"{tag}: the dining room opens onto the stair")
            dining_rooms = [r for r in rooms if r.type is RoomType.DINING]
            living_rooms = [r for r in rooms if r.type is RoomType.LIVING]
            if dining_rooms and living_rooms and dining_rooms[0].area > 0.85 * living_rooms[0].area:
                problems.append(f"{tag}: the dining room is bigger than the living room")
            masters = [r for r in rooms if r.type is RoomType.MASTER_BEDROOM]
            beds = [r for r in rooms if r.type in (RoomType.BEDROOM, RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM)]
            if masters and beds and masters[0].area < 1.1 * max(r.area for r in beds):
                problems.append(f"{tag}: the master bedroom is not the largest bedroom")
            # A shared bathroom is one off a hall everybody uses: the passage, the
            # landing, the dining hall, the family lounge, the courtyard.
            passage_ids = {r.id for r in rooms if r.type in (RoomType.CORRIDOR, RoomType.LOBBY, RoomType.DINING,
                                                             RoomType.FAMILY, RoomType.STAIRCASE, RoomType.COURTYARD)}
            for room in beds + masters:
                bath_doors = [x for x in doors_of[room.id] if by_id[x].type is RoomType.BATHROOM]
                shared = any(
                    by_id[b.id] and (doors_of[b.id] & passage_ids)
                    for b in rooms if b.type is RoomType.BATHROOM
                )
                if not bath_doors and not shared:
                    problems.append(f"{tag}: {room.display_name()} has no bathroom it can reach")
            for room in rooms:
                if room.type is RoomType.TERRACE and not any(
                    w.kind is WallKind.PARAPET and room.id in w.rooms for w in level.walls
                ):
                    problems.append(f"{tag}: the terrace is not on the edge of the house")
            for room in rooms:
                if self._wants_attached(room) and not any(
                    by_id[x].type is RoomType.BATHROOM for x in doors_of[room.id]
                ):
                    problems.append(f"{tag}: {room.display_name()} has no bathroom of its own")
            for room in rooms:
                # Its own bathroom, dressing room and balcony are the bedroom's
                # own doors; past one more, to the hall, it is a through room.
                own = sum(1 for x in doors_of[room.id] if by_id.get(x) is not None
                          and by_id[x].type in (RoomType.BATHROOM, RoomType.WARDROBE, RoomType.BALCONY))
                if room.type in _BEDROOMS and count[room.id] - own > 2:
                    problems.append(f"{tag}: {room.display_name()} has {count[room.id]} doors")

            def kinds(kind: RoomType, rooms=rooms) -> list[Room]:
                return [r for r in rooms if r.type is kind]

            for a_kind, b_kind in ((RoomType.KITCHEN, RoomType.DINING), (RoomType.LIVING, RoomType.DINING)):
                for a in kinds(a_kind):
                    others = kinds(b_kind)
                    if others and not any(_loose_touch(a.bbox, b.bbox, 0.1, 0.8) for b in others):
                        problems.append(f"{tag}: {a.display_name()} does not meet the {others[0].display_name()}")
            for puja in kinds(RoomType.PUJA):
                if any(_loose_touch(puja.bbox, w.bbox, 0.1, 0.4) for w in rooms if w.type in _WET_TYPES):
                    problems.append(f"{tag}: the puja shares a wall with a toilet")
            if level.index == 0:
                for foyer in kinds(RoomType.FOYER):
                    living = kinds(RoomType.LIVING)
                    if living and not any(
                        o.kind.is_door and o.connects and {foyer.id, living[0].id} == set(o.connects)
                        for w in level.walls for o in w.openings
                    ):
                        problems.append(f"{tag}: the foyer does not open into the living room")
            if level.index > 0:
                below = plan.level_at(level.index - 1)
                if below is not None:
                    for room in rooms:
                        if room.type not in _WET_TYPES:
                            continue
                        wet_over = 0.0
                        for under in below.rooms:
                            if under.type not in _NO_WET_ABOVE:
                                continue
                            a, b = room.bbox, under.bbox
                            dx = min(a.max_x, b.max_x) - max(a.min_x, b.min_x)
                            dy = min(a.max_y, b.max_y) - max(a.min_y, b.min_y)
                            if dx > 0 and dy > 0:
                                wet_over += dx * dy
                        if wet_over > 0.3 * room.area:
                            problems.append(f"{tag}: {room.display_name()} sits over a kitchen, dining room or puja")
        return problems

    # -------------------------------------------------------- preparation --

    def _prepare_requirements(
        self,
        levels: int | None = None,
        reqs: list[RoomRequirement] | None = None,
    ) -> tuple[list[RoomRequirement], list[list[int]]]:
        """Expand the brief, add the circulation nobody asks for, split by floor.

        Returns the room list and, per level, the indices of the rooms on it.
        It is a pure function of `levels` and `reqs` so the feasibility gate
        can ask "what would this look like on three floors?" without
        committing to the answer; `__init__` calls it for the final time.
        """
        levels = self.brief.levels if levels is None else levels
        reqs = self.brief.expanded_requirements() if reqs is None else reqs
        if not reqs:
            reqs = [RoomRequirement(type=RoomType.LIVING, preferred_area=20.0)]

        has_circulation = any(r.type.is_circulation for r in reqs)
        habitable_count = sum(1 for r in reqs if r.type.is_habitable)
        if not has_circulation and habitable_count >= 4:
            programme = sum(r.target_area for r in reqs)
            reqs.append(
                RoomRequirement(
                    type=RoomType.CORRIDOR,
                    preferred_area=max(5.0, programme * self.config.corridor_share),
                    needs_external_wall=False,
                    needs_daylight=False,
                    priority=0.8,
                )
            )

        if levels <= 1:
            return reqs, [list(range(len(reqs)))]

        def stair() -> RoomRequirement:
            return RoomRequirement(
                type=RoomType.STAIRCASE, preferred_area=round((STAIR_WIDTH_COMPACT * STAIR_LENGTH_COMPACT if self._compact_stair else STAIR_AREA)
                                     * self._stair_scale ** 2, 2),
                needs_external_wall=False, needs_daylight=False, priority=1.4,
            )

        # Public and service functions stay on the entrance level; bedrooms
        # move up. Anything the brief pinned to a level is honoured exactly.
        ground_types = {
            RoomType.LIVING, RoomType.DRAWING, RoomType.DINING, RoomType.KITCHEN,
            RoomType.FOYER, RoomType.PUJA, RoomType.UTILITY, RoomType.PANTRY,
            RoomType.STORE, RoomType.GARAGE, RoomType.POWDER, RoomType.SERVANT,
            RoomType.VERANDAH, RoomType.STAIRCASE, RoomType.LAUNDRY,
        }
        private_types = {RoomType.MASTER_BEDROOM, RoomType.BEDROOM,
                         RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM}
        passage_types = {RoomType.CORRIDOR, RoomType.LOBBY}
        buckets: list[list[int]] = [[] for _ in range(levels)]
        passages: list[int] = []
        # A house with two or more bathrooms keeps one downstairs: a guest
        # should not be sent up through the bedrooms to wash their hands.
        ground_baths = 1 if sum(1 for r in reqs if r.type is RoomType.BATHROOM) >= 2 else 0
        upper = 1
        for idx, req in enumerate(reqs):
            if req.level is not None and 0 <= req.level < levels:
                buckets[req.level].append(idx)
            elif req.type in passage_types:
                passages.append(idx)
            elif req.type is RoomType.BATHROOM and ground_baths:
                buckets[0].append(idx)
                ground_baths -= 1
            elif req.type in ground_types:
                buckets[0].append(idx)
            else:
                buckets[upper].append(idx)
                upper = 1 + (upper % max(1, levels - 1))

        # A ground floor asked to hold more than its footprint (a garage, a
        # courtyard and the whole public programme on a small plot) sends up
        # what lives as well upstairs - laundry first, then a store, a study, a
        # spare bathroom - to the lightest floor, rather than squeezing every
        # room below what it needs while the floors above are half terrace.
        fp = self._footprint_area or self._footprint_cap()
        if levels > 1 and fp:
            movable = [RoomType.LAUNDRY, RoomType.STORE, RoomType.STUDY, RoomType.HOME_OFFICE,
                       RoomType.LIBRARY, RoomType.GYM, RoomType.SERVANT]

            def load(b: list[int]) -> float:
                return sum(reqs[i].target_area for i in b) + 11.0 + 0.06 * fp

            cap = 0.84 * fp
            for kind in movable:
                for idx in [i for i in buckets[0] if reqs[i].type is kind and reqs[i].level is None]:
                    if load(buckets[0]) <= cap:
                        break
                    dest = min(range(1, levels), key=lambda k: load(buckets[k]))
                    if load(buckets[dest]) + reqs[idx].target_area <= cap:
                        buckets[0].remove(idx)
                        buckets[dest].append(idx)

        # Every level needs at least one room.
        for bucket in buckets:
            if not bucket:
                donor = max(buckets, key=len)
                if len(donor) > 1:
                    bucket.append(donor.pop())

        # The passage the programme added goes where the bedrooms are; the
        # old rule filed it under "ground" and left the bedrooms upstairs
        # opening into each other. Then every floor gets what it lacks: a
        # staircase to arrive by, and a hall to walk along.
        def private_count(bucket: list[int]) -> int:
            return sum(1 for i in bucket if reqs[i].type in private_types)

        order = sorted(range(levels), key=lambda i: (-private_count(buckets[i]), i))
        for level_index, idx in zip(order, passages, strict=False):
            buckets[level_index].append(idx)
        for idx in passages[levels:]:
            buckets[0].append(idx)

        passage = passage_area(self.brief.site) * self._passage_scale
        if self._footprint_area:
            # A passage is a strip about 1.2 m wide and as long as the private zone;
            # on a generous plot it grows by length, never into a hall.
            passage = min(passage, 0.06 * self._footprint_area, 16.0)
        for level_index, bucket in enumerate(buckets):
            has_passage = any(reqs[i].type in passage_types for i in bucket)
            if not has_passage:
                # Ground: a hall running back from the living room that the
                # stair, the toilet and the service rooms open off. Without
                # one the living room becomes the hall, with the foyer, the
                # dining room, the stair and the puja all opening off it.
                # Upper: a passage across the bedrooms, or with a single
                # bedroom just a landing - a bedroom door straight off a
                # flight of stairs is not a door anyone would draw.
                # (The plan without corridors never draws this; it guides the
                # fallback planners, which draw longer passages from a "hall".)
                if level_index == 0:
                    kind, area, needed = RoomType.CORRIDOR, passage * 0.9, True
                elif private_count(bucket) >= 2:
                    kind, area, needed = RoomType.CORRIDOR, passage, True
                else:
                    kind, area, needed = RoomType.LOBBY, 3.6, True
                if needed:
                    reqs.append(RoomRequirement(
                        type=kind,
                        preferred_area=round(max(3.5, area), 1),
                        needs_daylight=False, needs_external_wall=False, priority=1.2,
                        notes="Passage added by the generator.",
                    ))
                    bucket.append(len(reqs) - 1)
            if not any(reqs[i].type is RoomType.STAIRCASE for i in bucket):
                reqs.append(stair())
                bucket.append(len(reqs) - 1)

        self._fill_floors(reqs, buckets)
        return reqs, buckets

    def _fill_floors(self, reqs: list[RoomRequirement], buckets: list[list[int]]) -> None:
        """Give a light upper floor the terrace a real house has there.

        Every floor is drawn on the same footprint, so a floor whose rooms add
        up to a third of it has its rooms stretched to three times their size:
        a 44 m2 master bedroom, a 48 m2 bathroom. A real house is not built
        that way - the upper floor is smaller and the roof of the floor below
        is a terrace - so the shortfall is drawn as one. It is outdoor space,
        so it adds nothing to the built-up area the FAR is counted on.
        """
        cap = self._footprint_area or self._footprint_cap()
        needs = [
            sum(reqs[i].target_area for i in bucket if reqs[i].notes != FILL_NOTE)
            for bucket in buckets
        ]
        footprint = max(needs) if needs else 0.0
        if cap:
            footprint = min(footprint, cap)
        for level_index in range(1, len(buckets)):
            gap = footprint - needs[level_index]
            # On a house grown to its plot, every floor is meant to fill the plate;
            # otherwise a floor may run a quarter light before it earns a terrace.
            slack = 0.12 if self._footprint_area else 1.0 - COMFORT_FRACTION
            if gap < slack * footprint or gap < 8.0:
                continue
            bucket = buckets[level_index]
            # An Indian house fills its upper floor with rooms: a family lounge
            # the bedrooms open off, and bedrooms and a study at their full
            # comfortable size. Only what is left is the terrace or balcony over
            # the floor below - one, not a floor of open roof.
            if not self._spread and gap > 14.0 and not any(r.type is RoomType.FAMILY for r in reqs):
                cap = self._cap(RoomType.FAMILY) or 22.0
                area = round(min(cap, max(12.0, gap * 0.55)), 1)
                reqs.append(RoomRequirement(
                    type=RoomType.FAMILY, preferred_area=area, level=level_index, priority=0.7,
                    needs_daylight=True, needs_external_wall=True,
                    notes="Family lounge upstairs, so the floor is lived in rather than left as roof.",
                ))
                bucket.append(len(reqs) - 1)
                gap -= area
            growable = [i for i in bucket if reqs[i].type in _UPSTAIRS_GROW and reqs[i].notes != FILL_NOTE]
            base_area = sum(reqs[i].target_area for i in growable)
            if gap > 4.0 and base_area > 0:
                share = gap / base_area
                for i in growable:
                    r = reqs[i]
                    ceiling = self._cap_for(r) or r.target_area * 1.3
                    grown = min(r.target_area * (1 + share), max(r.target_area, CAP_HEADROOM * ceiling))
                    gap -= grown - r.target_area
                    r.preferred_area = round(grown, 2)
            terrace = min(gap, max(9.0, 0.15 * footprint))
            if terrace < 6.0:
                continue
            reqs.append(RoomRequirement(
                type=RoomType.TERRACE, preferred_area=round(terrace, 1),
                needs_daylight=False, needs_external_wall=True, priority=0.3,
                notes=FILL_NOTE,
            ))
            bucket.append(len(reqs) - 1)

    # ----------------------------------------------------- feasibility gate --

    def _cap(self, room_type: RoomType) -> float | None:
        """The most a room of this kind is drawn in a house this size: its
        comfortable size, raised toward the luxury ceiling on a large plot."""
        cap = comfort_cap(room_type, self._bedrooms)
        if cap is None or self._cap_boost <= 1.0:
            return cap
        ceiling = luxury_max(room_type)
        return min(cap * self._cap_boost, ceiling) if ceiling is not None else cap * self._cap_boost

    def _cap_for(self, req: RoomRequirement) -> float | None:
        """The cap for one room: its kind's, and never past 1.6 x what was asked
        (more on a large plot the house is growing into)."""
        cap = self._cap(req.type)
        if cap is None:
            return None
        asked = req.asked_area or req.target_area
        return min(cap, 1.6 * self._cap_boost * asked) if req.notes != FILL_NOTE else cap

    def _site_box(self) -> BoundingBox | None:
        """The plot after setbacks, before coverage; None when there is no boundary."""
        site = self.brief.site
        if not site.boundary:
            return None
        # A rectangular plot: each side takes its own setback - the road side its
        # front, the opposite its rear, the others the side setbacks.
        xs0 = sorted({round(p.x, 4) for p in site.boundary})
        ys0 = sorted({round(p.y, 4) for p in site.boundary})
        if len(site.boundary) == 4 and len(xs0) == 2 and len(ys0) == 2 and min(site.setback_left, site.setback_right) <= 0.0:
            road = site.road_directions[0].cardinal.value if site.road_directions else "N"
            f, r, lft, rgt = site.setback_front, site.setback_rear, site.setback_left, site.setback_right
            west, east, south, north = {
                "N": (lft, rgt, r, f), "S": (lft, rgt, f, r),
                "E": (r, f, rgt, lft), "W": (f, r, rgt, lft),
            }.get(road, (lft, rgt, r, f))
            x0, x1, y0, y1 = xs0[0] + west, xs0[1] - east, ys0[0] + south, ys0[1] - north
            if x1 - x0 > 0.5 and y1 - y0 > 0.5:
                return BoundingBox(x0, y0, x1, y1)
        inner = shrink_polygon(
            site.boundary,
            min(site.setback_front, site.setback_rear, site.setback_left, site.setback_right),
        )
        if inner:
            xs = [p.x for p in inner]
            ys = [p.y for p in inner]
            return BoundingBox(min(xs), min(ys), max(xs), max(ys))
        return site.bbox

    def _footprint_cap(self) -> float | None:
        """The largest floor plate the plot allows: setbacks, then coverage."""
        box = self._site_box()
        if box is None:
            return None
        site = self.brief.site
        cap = box.area
        if site.plot_area and site.max_footprint > 0:
            cap = min(cap, site.max_footprint)
        return cap

    def _assess(self, levels: int, base: list[RoomRequirement]) -> _Assessment:
        """What a programme needs on each floor, at its minimum and comfortably."""
        reqs, buckets = self._prepare_requirements(levels, list(base))
        minimum: list[float] = []
        comfort: list[float] = []
        target: list[float] = []
        for bucket in buckets:
            lo = ok = tg = 0.0
            for i in bucket:
                r = reqs[i]
                if r.notes == FILL_NOTE:
                    continue
                floor, easy = self._room_bounds(r)
                lo += floor
                ok += easy
                tg += r.target_area
            minimum.append(lo)
            comfort.append(ok)
            target.append(tg)
        return _Assessment(levels, reqs, buckets, minimum, comfort, target)

    def _room_bounds(self, req: RoomRequirement) -> tuple[float, float]:
        """(smallest, comfortable) area for one room."""
        target = req.target_area
        if req.type is RoomType.STAIRCASE:
            return target, target
        # On a small plot the rooms are drawn at the least a household can live
        # with, and the passage shrinks to what a door needs.
        compact = getattr(self, "_compact_stair", False)
        if req.type in (RoomType.CORRIDOR, RoomType.LOBBY):
            k = 0.55 if compact else 0.8
            return k * target, (0.65 if compact else 0.9) * target
        floor = minimum_area(req, MIN_CLEAR_WIDTH.get(req.type, MIN_ROOM_DIMENSION))
        if compact and req.type in _COMPACT_ROOMS:
            floor *= 0.86
        return floor, comfortable_area(req, floor)

    def _resolve_programme(self) -> None:
        """Decide, once, what is built: how many floors, which rooms, what sizes.

        See `feasibility` for the order. Every departure from the brief is
        written to `self.advisories` so the plan carries the explanation.
        """
        brief = self.brief
        base = brief.expanded_requirements()
        for r in base:
            if r.asked_area is None:
                r.asked_area = r.target_area       # what the programme asked, kept for the audit
        requested = brief.levels
        cap = self._footprint_cap()
        self._compact_stair = cap is not None and cap < COMPACT_PLATE
        self.feasibility = FeasibilityReport(requested_levels=requested, levels=requested)
        if not self.config.check_feasibility or cap is None:
            self.requirements, self.level_buckets = self._prepare_requirements(requested, base)
            return

        site = brief.site
        avail = cap * COMFORT_PACKING                 # comfortable: room to give every room its shape
        hard = cap * PACKING_EFFICIENCY               # the most any programme can be squeezed into
        advisories: list[str] = []
        levels = requested
        cur = self._assess(levels, base)
        beds = bedrooms_in(base)

        # A floor that would hold little but the stair is not a floor.
        while levels > 2 and min(cur.target[1:]) < 0.30 * max(cur.target):
            levels -= 1
            cur = self._assess(levels, base)
            advisories.append(
                f"The brief asks for {requested} floors, but its rooms fill only {levels}: "
                f"a third floor would hold little more than the staircase, so the house "
                f"is drawn with {levels}."
            )

        # A plot that can hold the whole house on one floor gets it on one floor:
        # the footprint doubles, nobody climbs a stair, and the plot is used
        # rather than left to paving round a small two-storey block.
        if requested == 2 and levels == 2:
            one = self._assess(1, base)
            if (site.plot_area or 0.0) >= SPREAD_PLOT and max(one.comfort) <= avail:
                advisories.append(
                    f"The brief asks for {requested} floors, but this plot holds the whole house on one: "
                    f"it is spread over a single storey, so the house uses the plot and nobody climbs a stair."
                )
                levels = 1
                cur = one
                self._spread = True

        def comfy(a: _Assessment) -> bool:
            return max(a.comfort) <= avail

        # (a) Add a floor.
        if not comfy(cur):
            lmax = max_levels(site.max_height)
            while levels < lmax:
                nxt = self._assess(levels + 1, base)
                footprint = min(cap, max(nxt.target) * 1.08)
                if site.max_built_area and (levels + 1) * footprint > site.max_built_area:
                    break
                if max(nxt.comfort) >= max(cur.comfort) - 0.5:
                    break          # a floor that does not lighten the heaviest one is not the answer
                needed_before = max(cur.comfort) / COMFORT_PACKING
                before = storey_word(levels)
                levels += 1
                cur = nxt
                advisories.append(
                    f"A {beds}-bedroom {before} house needs about {needed_before:.0f} m² "
                    f"even with rooms drawn smaller than usual, and this plot's buildable "
                    f"area is {cap:.0f} m², so a floor was added ({levels} floors): the "
                    f"bedrooms moved upstairs, the living rooms stay on the ground floor, "
                    f"and a staircase links them."
                )
                if comfy(cur):
                    break

        # (b) Give up what is optional, least important first.
        dropped: list[str] = []
        if not comfy(cur):
            def drop(kind: RoomType) -> None:
                for pos in range(len(base) - 1, -1, -1):
                    if base[pos].type is kind and not base[pos].label:
                        base.pop(pos)
                        return

            notes = {
                RoomType.STUDY: "The study was left out to fit the plot.",
                RoomType.BALCONY: "The balcony was left out to fit the plot.",
                RoomType.UTILITY: "The utility room was left out to fit the plot; the kitchen "
                                  "carries the wash area.",
                RoomType.PUJA: "The puja room became a wall niche in the living room: a "
                               "separate room did not fit the plot.",
            }
            # What the programme added goes first; a room the client asked for
            # goes only if nothing else makes the house fit, and the advisory
            # says so.
            requested = {r.type for r in base if "Requested" in (r.notes or "")}
            order = [k for k in OPTIONAL_ORDER if k not in requested] + [k for k in OPTIONAL_ORDER if k in requested]
            for kind in order:
                while not comfy(cur) and any(r.type is kind and not r.label for r in base):
                    drop(kind)
                    cur = self._assess(levels, base)
                    dropped.append(kind.value)
                    advisories.append(notes[kind])
            allowed = allowed_bathrooms(beds)
            while not comfy(cur) and sum(1 for r in base if r.type is RoomType.BATHROOM and not r.label) > allowed:
                drop(RoomType.BATHROOM)
                cur = self._assess(levels, base)
                dropped.append("bathroom")
                advisories.append(
                    f"A bathroom was left out: {beds} bedrooms keep {allowed} "
                    f"(one per two bedrooms plus a common one) on a plot this size."
                )

        # (c) Draw the rooms smaller; (d) or say it cannot be done.
        shrunk = False
        if not comfy(cur):
            if max(cur.minimum) > hard:
                # The brief asks for more than the plot can hold at any size.
                # A client is never sent away with nothing: add a floor if the
                # height limit allows, then let go of the least important
                # rooms one at a time, then of bedrooms - and say each step.
                lmax = max_levels(site.max_height)
                # Least important first. A room is only let go if that really
                # lightens the floor that is too full - taking a bedroom off
                # the upper floor does nothing for a crowded ground floor.
                order = (RoomType.LAUNDRY, RoomType.PANTRY, RoomType.WARDROBE, RoomType.SERVANT, RoomType.LIBRARY,
                         RoomType.GYM, RoomType.HOME_THEATRE, RoomType.STORE, RoomType.GUEST_BEDROOM,
                         RoomType.HOME_OFFICE, RoomType.STUDY, RoomType.FAMILY, RoomType.POWDER, RoomType.FOYER,
                         RoomType.UTILITY, RoomType.PUJA, RoomType.DINING, RoomType.TOILET, RoomType.GARAGE,
                         RoomType.CHILDREN_BEDROOM, RoomType.BEDROOM)
                before = bedrooms_in(base)
                let_go: list[str] = []
                guard = 0
                while max(cur.minimum) > hard and guard < 40:
                    guard += 1
                    if levels < lmax:
                        nxt = self._assess(levels + 1, base)
                        footprint = min(cap, max(nxt.target) * 1.08)
                        over_far = bool(site.max_built_area) and (levels + 1) * footprint > site.max_built_area
                        if not over_far and max(nxt.minimum) < max(cur.minimum) - 0.3:
                            levels += 1
                            cur = nxt
                            advisories.append(f"A floor was added ({levels} floors): the rooms asked for "
                                              f"do not fit one level less on this plot.")
                            continue
                    taken = False
                    for kind in order:
                        if kind in (RoomType.CHILDREN_BEDROOM, RoomType.BEDROOM) and bedrooms_in(base) <= 1:
                            continue
                        pick = next((r for r in reversed(base) if r.type is kind), None)
                        if pick is None:
                            continue
                        rest = [r for r in base if r is not pick]
                        trial = self._assess(levels, rest)
                        if max(trial.minimum) < max(cur.minimum) - 0.05:
                            base[:] = rest
                            cur = trial
                            let_go.append(getattr(pick, "label", None) or {
                                RoomType.DINING: "the separate dining room (the living room doubles as dining)",
                                RoomType.PUJA: "the puja room (a wall niche instead)",
                                RoomType.FOYER: "the entrance foyer",
                            }.get(pick.type, pick.type.label.lower()))
                            if kind in (RoomType.CHILDREN_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM):
                                baths = [r for r in base if r.type is RoomType.BATHROOM and not r.label]
                                if len(baths) > allowed_bathrooms(bedrooms_in(base)):
                                    rest = [r for r in base if r is not baths[-1]]
                                    base[:] = rest
                                    cur = self._assess(levels, base)
                            taken = True
                            break
                    if not taken:
                        break
                if let_go:
                    kept = bedrooms_in(base)
                    advisories.append(
                        "To fit this plot, left out: " + ", ".join(dict.fromkeys(let_go)) + ". "
                        + (f"The house keeps {kept} bedrooms; a larger plot holds the rest."
                           if kept < before else "A larger plot would hold them."))
            # A programme within 4% of what the plot can hold is drawn at its minimum
            # (walls take less than the packing allowance on a small plot) rather than refused.
            if max(cur.minimum) <= hard * 1.04:
                advisories.append(self._shrink(cur, max(avail, max(cur.minimum) * 1.02)))
                shrunk = True
            else:
                needed = max(cur.minimum) / PACKING_EFFICIENCY
                can_add = levels < max_levels(site.max_height)
                raise InfeasibleBriefError(
                    f"A {beds}-bedroom {storey_word(levels)} house needs about {needed:.0f} m² "
                    f"but this plot's buildable area is {cap:.0f} m². "
                    + ("Add a floor, reduce bedrooms, or use a larger plot." if can_add
                       else "Reduce bedrooms or use a larger plot."),
                    needed_area=needed, available_area=cap, levels=levels,
                    advisories=advisories,
                )

        if not shrunk:
            cur = self._grow_programme(levels, base, cap, cur, advisories)

        brief.levels = levels
        self.requirements, self.level_buckets = cur.reqs, cur.buckets
        self.advisories = advisories
        self.feasibility = FeasibilityReport(
            requested_levels=requested, levels=levels,
            needed_area=max(cur.minimum) / PACKING_EFFICIENCY, available_area=cap,
            dropped=dropped, shrunk=shrunk, advisories=list(advisories),
        )
        if advisories:
            log_event(logger, "layout.feasibility", level=20, advisories=advisories)

    def _design_footprint(self, levels: int) -> float | None:
        """The floor plate a generous plot allows: setbacks, coverage, and the FAR.

        The FAR caps the sum of the floors, so a four-floor house on a plot with
        FAR 1.5 cannot have the ground floor the coverage rule alone permits.
        """
        cap = self._footprint_cap()
        if cap is None:
            return None
        built = self.brief.site.max_built_area
        if built and built > 0:
            cap = min(cap, built / max(1, levels))
        return cap

    def _grow_programme(
        self,
        levels: int,
        base: list[RoomRequirement],
        cap: float,
        cur: _Assessment,
        advisories: list[str],
    ) -> _Assessment:
        """Let the house grow to the plot it is given.

        The footprint used to shrink to the programme's own area, which put an
        8.9 x 13.6 m house in the corner of a 40 x 60 m site. A large plot is
        an invitation to larger rooms: every room's target is scaled by one
        factor, until the busiest floor fills the plot's allowed footprint,
        each capped at what a room of that kind can usefully be. When the caps
        bind and the footprint is still empty, rooms the plot can carry are
        added - a lounge, a study, a guest suite, a theatre, a verandah, a
        courtyard - rather than leaving empty space or stretching a living room
        into a hall. Plots the programme already fills are left exactly alone.
        """
        footprint = self._design_footprint(levels)
        footprint = self._design_footprint(levels)
        if footprint is None or max(cur.target) * 1.08 >= 0.97 * footprint:
            return cur
        # How much of the plot the brief leaves open: the lawn asked for, and the
        # drive and paths (as `SimpleBriefRequest._coverage` allows for them). A
        # house far smaller than that leaves a lawn the client never asked for -
        # 72% of a 55 x 85 ft plot when they asked to keep 25% - so on a plot past
        # town size it grows into the rest, up to what the byelaw allows: rooms
        # past their comfortable size toward the luxury ceiling, then the rooms a
        # house that size holds.
        plot_area = self.brief.site.plot_area or 0.0
        lawn = float(getattr(self.brief.site, "garden_share", 0.0) or 0.0)
        want = min(footprint, plot_area * (1.0 - lawn)) if plot_area else footprint
        # A pool asked for keeps its ground: the water, its deck and the path to the house.
        from aip.engines.experience.landscape import POOL_DECK, POOLS

        if self.brief.site.pool in POOLS:
            pw, pl = POOLS[self.brief.site.pool]
            margin = 2 * (POOL_DECK + 0.9)
            want = max(0.0, want - (pw + margin) * (pl + margin))
        left_open = 1.0 - max(cur.target) * 1.08 / plot_area if plot_area else 0.0
        # The lawn the client fixed is kept, and the drive and paths; every other
        # square metre the byelaws let the house stand on is house. So a house
        # that leaves more open than that grows into it, on any size of plot.
        too_much_lawn = plot_area > 0 and left_open > lawn + 0.04
        if too_much_lawn:
            self._cap_boost = max(1.0, min(2.2, want / (max(cur.target) * 1.08)))
        original = {id(r): r.target_area for r in base}
        fixed: set[int] = set()            # rooms added below keep the size they were added at
        goal = footprint / 1.08
        if too_much_lawn:
            # Everything but the lawn is house - up to 1.45 times the rooms asked for.
            # Past that a small programme on a huge plot is stretched into halls
            # and corridors; the rest of such a plot stays garden.
            goal = min(goal, want / 1.08, max(cur.target) * 1.45)
        elif self.brief.site.plot_area < 300.0:
            # On a town plot the rooms are not stretched to the coverage the byelaw
            # allows: a 135 m2 plot does not get a 48 m2 master bedroom. The rest is garden.
            goal = min(goal, max(cur.target) * 1.45)

        def apply(f: float) -> _Assessment:
            self._stair_scale = 1.0              # a stair is a stair: never grown with the plot
            self._passage_scale = min(2.2, math.sqrt(f))
            for r in base:
                if r.notes == FILL_NOTE or id(r) in fixed:
                    continue
                cap_area = self._cap(r.type)
                if cap_area is not None:
                    cap_area = min(cap_area, 1.5 * self._cap_boost * original[id(r)])
                scaled = original[id(r)] * f
                if cap_area is not None and r.type is not RoomType.STAIRCASE:
                    scaled = min(scaled, CAP_HEADROOM * cap_area)
                r.preferred_area = round(max(original[id(r)], scaled), 2)
            return self._assess(levels, base)

        def drawn(a: _Assessment, level: int | None = None) -> float:
            """What a floor's rooms cover as the house is drawn: passages a plan
            without corridors never draws are not counted as house."""
            def one(bucket):
                return sum(a.reqs[i].target_area for i in bucket
                           if a.reqs[i].type not in (RoomType.CORRIDOR, RoomType.LOBBY) and a.reqs[i].notes != FILL_NOTE)
            if level is not None:
                return one(a.buckets[level]) if level < len(a.buckets) else 0.0
            return max((one(b) for b in a.buckets), default=0.0)

        def solve() -> tuple[float, _Assessment, bool]:
            """The scale that fills the footprint; True when the caps allowed it."""
            top = apply(10.0)
            if drawn(top) < goal:
                return 10.0, top, False
            lo, hi = 1.0, 10.0
            for _ in range(24):
                mid = (lo + hi) / 2
                if drawn(apply(mid)) > goal:
                    hi = mid
                else:
                    lo = mid
            return lo, apply(lo), True

        def rebalance(a: _Assessment) -> _Assessment:
            """Bring the lighter floors up to the busiest one's size.

            One scale fills the busiest floor and leaves the others short; a
            bedroom on a floor that is three-quarters full is then stretched by
            the search to a size nobody asked for. So each lighter floor's
            rooms are scaled, within their caps, until it fills the plate too.
            What the caps will not absorb is left to the terrace.
            """
            for _ in range(3):
                busiest = max(a.target)
                moved = False
                for level, bucket in enumerate(a.buckets):
                    if a.target[level] >= 0.97 * busiest:
                        continue
                    scalable = [a.reqs[i] for i in bucket
                                if id(a.reqs[i]) in original and id(a.reqs[i]) not in fixed
                                and a.reqs[i].notes != FILL_NOTE and a.reqs[i].type is not RoomType.STAIRCASE
                                and self._cap(a.reqs[i].type) is not None]
                    mass = sum(r.target_area for r in scalable)
                    if mass <= 0:
                        continue
                    ratio = min(2.0, (busiest - (a.target[level] - mass)) / mass)
                    if ratio <= 1.02:
                        continue
                    for r in scalable:
                        grown_area = r.target_area * ratio
                        r.preferred_area = round(min(grown_area, CAP_HEADROOM * (self._cap(r.type) or grown_area)), 2)
                    moved = True
                if not moved:
                    break
                a = self._assess(levels, base)
            return a

        factor, grown, filled = solve()
        grown = rebalance(grown)
        added: list[str] = []
        # Rooms the client did not ask for are added if they said the studio may
        # (auto_extras), or when the house would otherwise leave far more lawn
        # than they asked to keep; otherwise the rest of the plot is garden.
        auto = bool((self.brief.metadata or {}).get("auto_extras", False)) or too_much_lawn
        # Not a study or a theatre the client never asked for: one more room on
        # a floor than its hall can open onto brings the corridor back. Never a
        # guest suite either: it brings a bathroom, and the client chose how
        # many bathrooms the house has. A house spread over one storey has the
        # plot already; it is not given rooms.
        skip = {RoomType.STUDY, RoomType.HOME_THEATRE, RoomType.GUEST_BEDROOM}
        if self._spread:
            skip.add(RoomType.FAMILY)
        pending = [e for e in EXTRA_ROOMS if e[0] not in skip] if auto else []
        # Elders go first to a bedroom on the ground floor: stairs are the thing
        # an older household avoids, and a guest suite is the room that serves.
        if any(o.role == "elder" and o.count for o in self.brief.occupants):
            pending.sort(key=lambda e: e[0] is not RoomType.GUEST_BEDROOM)
        # Where each addition belongs: the living and sleeping extras downstairs,
        # where a household uses them every day; the study and the theatre above,
        # and the family lounge with them, as the room the bedrooms open off.
        home_level = {RoomType.STUDY: 1, RoomType.HOME_THEATRE: 1, RoomType.FAMILY: 1}
        fill_to = 0.92 * want if too_much_lawn else FILL_TARGET * footprint
        while not filled and drawn(grown) * 1.08 < fill_to and pending:
            kind, area, label, why = pending.pop(0)
            if any(r.type is kind for r in base):
                continue
            pin = min(home_level.get(kind, 0), levels - 1) if levels > 1 else None
            new = [RoomRequirement(
                type=kind, preferred_area=area, level=pin, priority=0.7,
                needs_daylight=kind.is_habitable, needs_external_wall=kind is not RoomType.COURTYARD,
                notes="Added to fill a generous plot.",
            )]
            if kind is RoomType.GUEST_BEDROOM:
                new.append(RoomRequirement(
                    type=RoomType.BATHROOM, preferred_area=7.0, level=pin, priority=0.8,
                    needs_daylight=False, notes="Added to fill a generous plot.",
                ))
            for room in new:
                base.append(room)
                original[id(room)] = room.target_area
                fixed.add(id(room))
            added.append(f"{label} ({why})")
            factor, grown, filled = solve()
            grown = rebalance(grown)

        # The extras are small beside a large plot, and a house that uses a third
        # of what it may build on has wasted the rest. What remains is given to
        # the two rooms that can be any size without becoming a worse room: the
        # verandah that wraps the front and the courtyard at the heart of the
        # plan. Both are open to the sky, so neither adds to the built-up area.
        coverage = self._footprint_cap() or footprint
        goal_fill = min(0.95 * coverage, 0.97 * footprint, 0.97 * want)
        # Both are ground-floor rooms, so it is the ground floor's shortfall they
        # make up; the floors above fill with terrace.
        gap = goal_fill / 1.08 - drawn(grown, 0)
        if gap > 6.0 and auto:
            pin = 0 if levels > 1 else None
            plate = goal_fill
            for kind, share, label in ((RoomType.COURTYARD, 0.6, "courtyard"), (RoomType.VERANDAH, 0.4, "verandah")):
                room = next((r for r in base if r.type is kind and id(r) in fixed), None)
                if room is None and any(r.type is kind for r in base):
                    continue                      # the client asked for one of their own
                if room is None:
                    room = RoomRequirement(
                        type=kind, preferred_area=0.0001, level=pin, priority=0.5,
                        needs_daylight=False, needs_external_wall=kind is not RoomType.COURTYARD,
                        notes="Added to fill a generous plot.",
                    )
                    base.append(room)
                    fixed.add(id(room))
                    added.append(f"a larger {label}, to use the rest of the plot")
                room.preferred_area = round(min(0.4 * plate, max(room.preferred_area or 0.0, 0.0) + share * gap), 1)
            grown = self._assess(levels, base)

        # The plate is what the rooms fill. When even the extras cannot fill the
        # allowance, drawing the plate larger would stretch every room past its
        # cap, so the house stops where the programme does and says so.
        env_area = min(footprint, max(grown.target) * 1.08)
        self._footprint_area = env_area
        grown = self._assess(levels, base)      # the terraces depend on the plate just chosen
        fill = env_area / footprint
        if factor < 1.08 and not added:
            return grown            # the plot was barely bigger than the programme: nothing to say
        advisories.append(
            f"This plot is generous, so the house is drawn to fill it: a {env_area:.0f} m² floor "
            f"plate ({fill:.0%} of the {footprint:.0f} m² the setbacks, coverage and FAR allow) "
            + (f"with rooms up to {factor:.1f}x their usual size, " if factor < 9.9
               else "with every room at the largest size a room of its kind usefully is, ")
            + "none larger than that."
            + ("" if fill >= FILL_TARGET else
               " The rooms a house like this can sensibly hold do not fill the rest, so it is left as garden.")
        )
        for note in added:
            advisories.append(
                f"Added {note}." if note.startswith("a larger")
                else f"Added {note}, because every room was already at its largest sensible size."
            )
        return grown

    def _shrink(self, cur: _Assessment, avail: float) -> str:
        """Scale rooms down toward their minimum until each floor fits.

        Water-filling: one scale `s` per floor, every room drawn at
        `max(minimum, s x asked)`, `s` found by bisection so the floor sums to
        what the plot offers. Rooms already at their minimum stay there and
        the rest share the loss, which is how a practice squeezes a plan -
        the bedrooms give a little, the bathroom does not go under 1.5 m.
        """
        before = {r.type: r.target_area for r in cur.reqs}
        for bucket in cur.buckets:
            real = [i for i in bucket if cur.reqs[i].notes != FILL_NOTE]
            if sum(self._room_bounds(cur.reqs[i])[1] for i in real) <= avail:
                continue
            fixed = sum(cur.reqs[i].target_area for i in real
                        if cur.reqs[i].type is RoomType.STAIRCASE)
            free = [i for i in real if cur.reqs[i].type is not RoomType.STAIRCASE]
            bounds = {i: self._room_bounds(cur.reqs[i])[0] for i in free}
            asked = {i: cur.reqs[i].target_area for i in free}

            def total(s: float, free=free, bounds=bounds, asked=asked) -> float:
                return sum(max(bounds[i], s * asked[i]) for i in free)

            lo, hi = 0.0, 1.0
            for _ in range(40):
                mid = (lo + hi) / 2
                if total(mid) > avail - fixed:
                    hi = mid
                else:
                    lo = mid
            for i in free:
                cur.reqs[i].preferred_area = round(max(bounds[i], lo * asked[i]), 2)
        parts: list[str] = []
        seen: set[RoomType] = set()
        for r in cur.reqs:
            was = before.get(r.type)
            if r.type in seen or was is None or r.type is RoomType.STAIRCASE:
                continue
            if r.target_area < 0.93 * was and not r.type.is_circulation:
                seen.add(r.type)
                parts.append(f"{r.type.label.lower()} about {r.target_area:.0f} m² (asked {was:.0f})")
        return (
            "The programme is tight for this plot, so rooms are drawn smaller than asked, "
            "no smaller than their minimum: " + ", ".join(parts[:6]) + "."
            if parts else "Rooms are drawn a little smaller than asked to fit the plot."
        )

    def _buildable_envelope(self) -> BoundingBox:
        """The rectangle the building may occupy, after setbacks and coverage."""
        site = self.brief.site
        box = self._site_box()
        if box is None:
            side = math.sqrt(max(self.brief.target_built_area, 40.0))
            box = BoundingBox(0.0, 0.0, side * 1.25, side / 1.25 * 1.0)

        # Respect ground coverage by shrinking the footprint proportionally.
        # The footprint is stacked, so it is sized for the largest floor's
        # programme, not for the average: dividing the whole house by the
        # number of floors starved the ground floor.
        max_footprint = site.max_footprint if site.plot_area else box.area
        per_level_target = max(
            sum(self.requirements[i].target_area for i in bucket) for bucket in self.level_buckets
        )
        # The plate the rooms ask for; `_grow_programme` grows it (and sets
        # `_footprint_area`) when the plot leaves more open than the lawn.
        target = min(box.area, max_footprint if max_footprint > 0 else box.area, per_level_target * 1.08)
        if self._footprint_area:
            target = self._footprint_area          # the gate grew the house to the plot
        if target > 0 and box.area > target:
            # The house keeps the whole buildable frontage between the side
            # setbacks; the depth takes up the difference, leaving a front yard
            # and a rear garden rather than gaps down the sides.
            roads = [getattr(d, "value", d) for d in (getattr(site, "road_directions", None) or ["N"])]
            along_x = (roads[0] if roads else "N") in ("N", "S", "NE", "NW", "SE", "SW")
            if along_x:
                new_w, new_h = box.width, target / max(box.width, 0.1)
            else:
                new_w, new_h = target / max(box.height, 0.1), box.height
            centre = box.centre
            box = BoundingBox(
                centre.x - new_w / 2, centre.y - new_h / 2,
                centre.x + new_w / 2, centre.y + new_h / 2,
            )
        return box

    # ------------------------------------------------------------- stairs ---

    def _road_axes(self) -> tuple[bool, bool] | None:
        """(depth runs along y, road is at the high end of the depth axis); None with no road."""
        site = self.brief.site
        if not site.road_directions:
            return None
        bearing = (site.road_directions[0].bearing + site.north_angle) % 360
        depth_along_y = bearing < 45 or bearing >= 315 or 135 <= bearing < 225
        road_at_high_end = bearing < 45 or bearing >= 315 or 45 <= bearing < 135
        return depth_along_y, road_at_high_end

    def _plan_stairs(self) -> list[StairPlan]:
        """Every place the staircase could go, best first; empty for one floor.

        The stair is decided before any floor is searched: a dog-leg of about
        2.5 x 4.2 m against a side wall at the seam between the public and the
        private rooms, or across the rear wall when the plan is too shallow
        for that. Each option is a locked carve (see `StairPlan`), and each
        run of the search takes the next one, so the schemes offered differ in
        where the stair is as well as in how the rooms are arranged.
        """
        if len(self.level_buckets) <= 1:
            return []
        env = self._envelope
        axes = self._road_axes()
        depth_along_y, road_at_high_end = axes if axes is not None else (True, True)
        depth = env.height if depth_along_y else env.width
        across = env.width if depth_along_y else env.height
        side_edges = ("low_x", "high_x") if depth_along_y else ("low_y", "high_y")
        rear_edges = (("low_y",) if road_at_high_end else ("high_y",)) if depth_along_y else (
            ("low_x",) if road_at_high_end else ("high_x",))

        def from_road(d0: float, length: float) -> float:
            """Offset from the wall's low end of a stair that starts d0 from the road."""
            return depth - d0 - length if road_at_high_end else d0

        options: list[StairPlan] = []
        grown = self._stair_scale
        sizes = ((STAIR_WIDTH * grown, STAIR_LENGTH * grown), (2.4, 4.2), (2.3, 4.0))
        if self._compact_stair:
            sizes = ((STAIR_WIDTH_COMPACT, STAIR_LENGTH_COMPACT),) + sizes
        for thickness, length in sizes:
            # Side wall: long axis along the depth of the plan.
            if across - thickness >= _MIN_STRIP:
                seam = 0.42 * depth - length / 2
                starts: list[float] = []
                for cand in (seam, _MIN_STRIP):
                    cand = max(cand, _MIN_STRIP)
                    if depth - cand - length < _MIN_STRIP:
                        cand = depth - length            # no room for a rear strip: use the wall
                    starts.append(cand)
                starts.append(depth - length)             # against the rear wall
                for d0 in dict.fromkeys(round(v, 3) for v in starts):
                    if d0 < _MIN_STRIP - 1e-6 or d0 + length > depth + 1e-6:
                        continue
                    for edge in side_edges:
                        plan = carve_stair(env, edge, thickness, length, from_road(d0, length),
                                           f"{edge}@{d0:.1f}")
                        if plan is not None:
                            options.append(plan)
            # Rear wall: long axis across the plan, at one end of it.
            if across >= length and depth - thickness >= _MIN_STRIP:
                for edge in rear_edges:
                    for offset in (0.0, across - length):
                        plan = carve_stair(env, edge, thickness, length, offset,
                                           f"{edge}-rear@{offset:.1f}", side=False)
                        if plan is not None:
                            options.append(plan)

        # A carve with more free regions than the sparsest floor has rooms
        # would leave a hole on that floor.
        sparsest = min(len(bucket) - 1 for bucket in self.level_buckets)
        options = [o for o in options if len(o.regions) <= sparsest]
        if not options:
            return []

        # And one the floors can fill: a strip beside the stair needs rooms
        # small enough to sit in it, on every floor. A carve whose strip would
        # be filled with a lobby or a puja three times its size is a bad carve.
        def misfit_of(plan: StairPlan) -> float:
            worst = 0.0
            probe = random.Random(7)
            for bucket in self.level_buckets:
                slots = [i for i in bucket if self.requirements[i].type is not RoomType.STAIRCASE]
                groups = _deal_rooms(self.requirements, slots, plan.regions, probe)
                for group, box in zip(groups[1:], plan.regions[1:], strict=True):
                    big = min(box.width, box.height) >= 3.6
                    if any(self.requirements[s].type is RoomType.PUJA
                           or (not big and self.requirements[s].type in (RoomType.KITCHEN, RoomType.DINING,
                                                                         RoomType.LIVING))
                           for s in group):
                        worst = max(worst, 2.0)      # a strip is no place for the kitchen
                    got = sum(
                        min(self.requirements[s].target_area, box.area)
                        if self.requirements[s].notes == FILL_NOTE else self.requirements[s].target_area
                        for s in group
                    )
                    worst = max(worst, abs(got - box.area) / box.area)
            return worst

        scored = [(misfit_of(o), k, o) for k, o in enumerate(options)]
        log_event(logger, "layout.stairs", level=10, options=[(o.label, round(m, 2)) for m, _k, o in scored])
        good = [t for t in scored if t[0] <= 0.35]
        # Best-fitting carves first: the first runs are the ones that always happen.
        # (A corner stair costs a little more than a side or rear one: it is the
        # carve with the least structure to seed.)
        options = [o for _m, _k, o in sorted(good or sorted(scored, key=lambda t: (t[0], t[1]))[:2],
                                              key=lambda t: (round((t[0] + (0.5 if min(t[2].rect.width, t[2].rect.height) >= 3.5 else 0.0)) / 0.2), t[1]))][:10]
        # Vastu puts the stair south or west; otherwise keep the generated order.
        preferred = self._vastu_direction(RoomType.STAIRCASE)
        if preferred is not None:
            def misfit(plan: StairPlan) -> float:
                actual = direction_of(plan.rect.centre, env.centre, self.brief.site.north_angle)
                return abs(((actual.bearing - preferred.bearing) + 180) % 360 - 180)

            options.sort(key=misfit)
        return options

    def _deal(self, slots: list[int], regions: list[BoundingBox], rng: random.Random) -> list[list[int]]:
        """Share this floor's rooms out among the free regions the stair carve left."""
        return _deal_rooms(self.requirements, slots, regions, rng, self._below)

    def _cross_body(
        self, body_slots: list[int], plan: StairPlan, rng: random.Random, areas: list[float]
    ) -> Node | None:
        """The body of the plan as two rows of rooms either side of a cross passage.

        The passage is a strip a little over a metre wide that runs across the
        body from the flank of the stair, so it meets the stair and every room
        in both rows opens off it. That is how a narrow plot is planned by hand,
        and it is the arrangement the search finds slowest by mutation: a
        bedroom reaches the passage only if it is in the row beside it.
        """
        reqs = self.requirements
        passage = [s for s in body_slots if reqs[s].type in (RoomType.CORRIDOR, RoomType.LOBBY)]
        if len(passage) != 1 or not plan.side or not plan.regions:
            return None
        axes = self._road_axes()
        depth_along_y, high = axes if axes is not None else (True, True)
        body = plan.regions[0]
        thick = 1.2 if reqs[passage[0]].type is RoomType.CORRIDOR else 1.3
        stair = plan.rect
        lo_edge, hi_edge = (body.min_y, body.max_y) if depth_along_y else (body.min_x, body.max_x)
        across = body.width if depth_along_y else body.height
        centre = (stair.min_y + stair.max_y) / 2 if depth_along_y else (stair.min_x + stair.max_x) / 2
        start = centre - thick / 2
        if start - lo_edge < _MIN_STRIP:
            start = lo_edge
        elif hi_edge - (start + thick) < _MIN_STRIP:
            start = hi_edge - thick
        low_len, high_len = start - lo_edge, hi_edge - (start + thick)
        if low_len < 1e-6 and high_len < 1e-6:
            return None
        others = [s for s in body_slots if s != passage[0]]
        if len(others) < (2 if low_len > 1e-6 and high_len > 1e-6 else 1):
            return None

        # Share the rooms between the rows by the area each row has.
        capacity = [low_len * across, high_len * across]
        front_row = 1 if high else 0
        if self._level_index == 0 and len(self.level_buckets) >= 1:
            ordered = _depth_sorted(others, reqs, rng)       # front of the plot first
        else:
            ordered = others[:]
            rng.shuffle(ordered)
        rows: list[list[int]] = [[], []]
        load = [0.0, 0.0]
        wanted_first = front_row if self._level_index == 0 else None
        for slot in sorted(ordered, key=lambda x: -areas[x]) if wanted_first is None else ordered:
            if capacity[0] <= 0:
                choice = 1
            elif capacity[1] <= 0:
                choice = 0
            elif wanted_first is not None:
                choice = wanted_first if load[wanted_first] < capacity[wanted_first] else 1 - wanted_first
            else:
                choice = 0 if load[0] / capacity[0] <= load[1] / capacity[1] else 1
            rows[choice].append(slot)
            load[choice] += areas[slot]
        if (low_len > 1e-6 and not rows[0]) or (high_len > 1e-6 and not rows[1]):
            return None

        def row_tree(group: list[int], vertical: bool) -> Node:
            """Rooms side by side along the passage, a bathroom beside its bedroom."""
            beds = [x for x in group if reqs[x].type in _BEDROOMS]
            rest = [x for x in group if x not in beds]
            rng.shuffle(beds)
            baths = [x for x in rest if reqs[x].type is RoomType.BATHROOM]
            others_ = [x for x in rest if x not in baths]
            seq: list[int] = []
            for b in beds:
                seq.append(b)
                if baths:
                    seq.append(baths.pop())
            seq += baths + others_
            if rng.random() < 0.5:
                seq.reverse()
            return _row_tree(seq, areas, vertical)

        vertical_rows = depth_along_y          # rows run along x when depth runs along y
        nodes: list[tuple[float, Node]] = []
        if low_len > 1e-6:
            nodes.append((low_len, row_tree(rows[0], vertical_rows)))
        nodes.append((thick, Leaf(passage[0])))
        if high_len > 1e-6:
            nodes.append((high_len, row_tree(rows[1], vertical_rows)))
        cut_vertical = not depth_along_y

        def chain(items: list[tuple[float, Node]]) -> Node:
            if len(items) == 1:
                return items[0][1]
            head = items[0][0]
            rest = sum(length for length, _ in items[1:])
            return Split(cut_vertical, head / (head + rest), items[0][1], chain(items[1:]))

        return chain(nodes)

    def _seed_population(
        self, slots: list[int], areas: list[float], envelope: BoundingBox
    ) -> list[Genome]:
        """The first generation: organised starts, not random ones.

        A mix of four kinds of tree, because each is good at something the
        others are not: the zoned template (front-to-back bands with a spine),
        a depth-ordered banded tree, a squarified random tree whose rooms are
        never slots, and a few fully shuffled ones for diversity. With a stair
        plan every kind is grown inside the free regions of the locked carve,
        so every genome has the stair exactly where the plan says.
        """
        cfg = self.config
        rng = self.rng
        reqs = self.requirements
        axes = self._road_axes()
        plan = self._stair if self._stair is not None else None
        stair_slot = next((s for s in slots if reqs[s].type is RoomType.STAIRCASE), None)
        if plan is None or stair_slot is None:
            plan, stair_slot = None, None
        movable = [s for s in slots if s != stair_slot]

        def grow(group: list[int], box: BoundingBox, style: int, bands: int) -> Node:
            if len(group) == 1:
                return Leaf(group[0])
            if axes is None:
                order = group[:]
                rng.shuffle(order)
                return build_balanced_tree(order, rng, areas, box, 0.85)
            depth_along_y, high = axes
            if style == 0 and len(group) >= 3:
                return build_zoned_tree(
                    group, reqs, areas, rng,
                    road_along_y=depth_along_y, road_at_high_end=high,
                    bands=bands, brief_kind=self.brief.kind,
                    frontage=box.width if depth_along_y else box.height,
                )
            if style == 1:
                ordered = _depth_sorted(group, reqs, rng)
                return build_banded_tree(ordered, areas, box, rng,
                                         depth_along_y=depth_along_y, road_at_high_end=high)
            order = group[:]
            rng.shuffle(order)
            return build_balanced_tree(order, rng, areas, box, 0.85 if style == 2 else 0.4)

        population: list[Genome] = []
        # style: 0 zoned, 1 banded, 2 squarified, 3 loosely shaped and shuffled.
        styles = (0, 4, 1, 2, 4, 0, 4, 3)
        for k in range(cfg.population):
            style = styles[k % len(styles)]
            bands = 3 if k % 3 else 4
            assignment = slots[:]
            if style == 3:
                shuffled = movable[:]
                rng.shuffle(shuffled)
                for slot, value in zip(movable, shuffled, strict=True):
                    assignment[slot] = value
            if plan is None:
                tree = grow(movable, envelope, 1 if style == 4 else style, bands)
                population.append(Genome(tree, assignment))
                continue
            groups = self._deal(movable, plan.regions, rng)
            subtrees = {-(i + 1): grow(g, box, 1 if style == 4 else style, bands)
                        for i, (g, box) in enumerate(zip(groups, plan.regions, strict=True))}
            if style == 4:
                cross = self._cross_body(groups[0], plan, rng, areas)
                if cross is not None:
                    subtrees[-1] = cross
            population.append(Genome(plan.build(subtrees, stair_slot), assignment,
                                     pinned=frozenset({stair_slot})))
        return population

    def _level_assignment(self) -> list[list[int]]:
        """Per level, the indices of the requirements on it. Fixed at construction."""
        return self.level_buckets

    # ---------------------------------------------------------- evolution --

    def _evolve(self, elite_out: int = 3) -> list[Genome]:
        """Evolve against the surrogate and return the best `elite_out` genomes."""
        cfg = self.config
        slots = list(range(len(self.requirements)))
        areas = [r.target_area for r in self.requirements]
        envelope = self._envelope
        level_buckets = self._level_assignment()

        population = self._seed_population(slots, areas, envelope)
        if self._below_xs:
            for genome in population:
                _snap_tree(genome.tree, envelope, self._below_xs, self._below_ys, self.rng)

        best_score = -math.inf
        stagnant = 0

        for generation in range(cfg.generations):
            for genome in population:
                if genome.fitness <= UNSCORED:
                    genome.fitness = self._surrogate_fitness(genome, envelope, level_buckets)

            population.sort(key=lambda g: g.fitness, reverse=True)
            if population[0].fitness > best_score + 1e-6:
                best_score = population[0].fitness
                stagnant = 0
            else:
                stagnant += 1
            if stagnant >= cfg.max_stagnation:
                break

            survivors = population[: cfg.elite]
            children: list[Genome] = []
            for source in survivors:
                clone = source.copy()
                clone.fitness = source.fitness
                children.append(clone)

            # Anneal the mutation strength: explore early, refine late.
            strength = 1.0 - 0.7 * (generation / max(1, cfg.generations))
            while len(children) < cfg.population:
                parent_a = self._tournament(population)
                if self.rng.random() < 0.35:
                    parent_b = self._tournament(population)
                    child = crossover(parent_a, parent_b, self.rng)
                else:
                    child = parent_a.copy()
                if self.rng.random() < cfg.mutation_rate:
                    child = mutate(child, self.rng, strength)
                if self._below_xs and self.rng.random() < 0.3:
                    _snap_tree(child.tree, envelope, self._below_xs, self._below_ys, self.rng, p=0.5)
                child.fitness = UNSCORED
                children.append(child)
            population = children

        for genome in population:
            if genome.fitness <= UNSCORED:
                genome.fitness = self._surrogate_fitness(genome, envelope, level_buckets)
        population.sort(key=lambda g: g.fitness, reverse=True)
        return population[:elite_out]

    # --------------------------------------------------------- surrogate ---

    def _warm(self) -> None:
        """Per-requirement facts the surrogate would otherwise recompute ten thousand times.

        The surrogate runs about twenty thousand times for one scheme; looking
        up Vastu's ideal direction, the statutory width or whether a door may
        lead from one room type to another on every call was a third of the
        generation time. All of it depends on the requirement alone, so it is
        worked out once per floor.
        """
        if self._facts is not None:
            return
        from aip.engines.architecture.programme import PRIVATE_HOST, is_through, may_enter

        vastu_weight = self.brief.tradition_weight if self.brief.vastu.is_constraining else 0.0
        reqs = self.requirements
        facts: list[_Facts] = []
        for req in reqs:
            preferred = req.preferred_direction or self._vastu_direction(req.type)
            facts.append(_Facts(
                type=req.type,
                target=max(req.target_area, 0.5),
                floor=MIN_CLEAR_WIDTH.get(req.type, MIN_ROOM_DIMENSION),
                habitable=req.type.is_habitable,
                needs_light=req.needs_daylight or req.needs_external_wall,
                needs_daylight=req.needs_daylight,
                bearing=None if preferred is None else preferred.bearing,
                orient_weight=1.0 if req.preferred_direction else max(0.25, vastu_weight),
                entry=req.type in _ENTRY_ROOMS,
                circulation=req.type.is_circulation,
                passage=req.type in (RoomType.CORRIDOR, RoomType.LOBBY),
                corridor=req.type is RoomType.CORRIDOR,
                stair=req.type is RoomType.STAIRCASE,
                fill=req.notes == FILL_NOTE,
                through=is_through(req.type),
                cap=self._cap_for(req),
                furnish=FURNISH_MIN.get(req.type),
                bedroom=req.type in _BEDROOMS,
                wet=req.type in _WET_TYPES,
                outdoor=req.type.is_outdoor,
                ensuite=req.attached_bathroom and req.type in _BEDROOMS,
                utility=req.type is RoomType.UTILITY,
                asked=max(req.asked_area or req.target_area, 0.5),
                sized=not (req.type.is_outdoor or req.type is RoomType.STAIRCASE or req.notes == FILL_NOTE),
            ))
        # door_ok[i][j]: may room i be entered from room j by a door the
        # door tree reaches on its own - a through-room, or i's private host.
        door_ok: list[list[bool]] = []
        for i, a in enumerate(reqs):
            row = []
            for j, b in enumerate(reqs):
                ok = False
                if i != j and may_enter(a.type, b.type):
                    host = b.type in PRIVATE_HOST.get(a.type, ()) or (
                        a.type is RoomType.BATHROOM and b.attached_bathroom
                    )
                    # A bathroom beside a bedroom is that bedroom's bathroom: the
                    # door placer cuts it, and the walkability check allows it.
                    ok = is_through(b.type) or host or (
                        a.type is RoomType.BATHROOM and b.type in _BEDROOMS
                    )
                row.append(ok)
            door_ok.append(row)
        self._door_ok = door_ok
        self._facts = facts

    def _surrogate_fitness(
        self,
        genome: Genome,
        envelope: BoundingBox,
        level_buckets: list[list[int]],
    ) -> float:
        """Cheap geometric proxy for plan quality.

        Scores the raw partition rectangles without building walls or openings.
        The terms are chosen to correlate with the exact metrics they stand in
        for: external-wall access predicts daylight, corner cells predict cross
        ventilation, aspect ratio predicts furnishability, and the orientation
        term predicts the Vastu and solar scores. Because it touches no Pydantic
        models and no wall graph, it runs about two orders of magnitude faster
        than the exact evaluation.

        It scores one floor: a multi-level brief searches each floor with its
        own worker, so every room here is on the same level.
        """
        boxes = realise(genome.tree, envelope)
        if not boxes:
            return 0.0
        self._warm()
        facts = self._facts
        assert facts is not None

        from aip.engines.architecture.programme import depth_fit, score_pairs

        area_terms: list[float] = []
        shape_terms: list[float] = []
        light_terms: list[float] = []
        orientation_terms: list[float] = []
        depth_terms: list[float] = []
        penalty = 0.0

        cx0, cy0 = (envelope.min_x + envelope.max_x) / 2, (envelope.min_y + envelope.max_y) / 2
        north = self.brief.site.north_angle
        ew, eh = max(envelope.width, 1e-6), max(envelope.height, 1e-6)

        # The road-to-rear axis. Depth 0 is the frontage, 1 the back boundary,
        # measured along whichever axis faces the road.
        road = self.brief.site.road_directions[0] if self.brief.site.road_directions else None
        mode = 0
        if road is not None:
            bearing = (road.bearing + north) % 360
            mode = 1 if 45 <= bearing < 135 else 2 if 225 <= bearing < 315 else (
                3 if bearing >= 315 or bearing < 45 else 4)

        level0 = self._level_index == 0
        assignment = genome.assignment
        refs: list[int] = []
        rects: list[BoundingBox] = []
        landlocked: list[int] = []
        for slot, box in boxes.items():
            ri = assignment[slot]
            f = facts[ri]
            refs.append(ri)
            rects.append(box)

            w = box.max_x - box.min_x
            h = box.max_y - box.min_y
            short, long = (w, h) if w < h else (h, w)
            aspect = long / short if short > 1e-9 else 50.0
            if aspect > 50.0:
                aspect = 50.0
            cx, cy = (box.min_x + box.max_x) / 2, (box.min_y + box.max_y) / 2

            # Hard geometric viability.
            if short < MIN_ROOM_DIMENSION:
                penalty += 0.14 * (MIN_ROOM_DIMENSION - short) / MIN_ROOM_DIMENSION

            # Statutory minimum width for this room type, not merely a generic
            # floor. A dining room 1.7 m across clears MIN_ROOM_DIMENSION and is
            # still a corridor with a table in it.
            if short < f.floor:
                penalty += (1.8 if f.habitable else 0.9) * (f.floor - short) / f.floor

            # A room can have the right area and the wrong shape: the smallest
            # rectangle its furniture fits in is a hard floor on both sides.
            if f.furnish is not None and (short < f.furnish[0] or long < f.furnish[1]):
                penalty += (1.5 if f.habitable else 1.0) * (
                    max(0.0, f.furnish[0] - short) / f.furnish[0]
                    + max(0.0, f.furnish[1] - long) / f.furnish[1]
                ) + 0.5

            # A passage is a strip, not a room: wider than a metre and a half it
            # is a hall someone has to furnish.
            if f.passage and short > PASSAGE_STRIP_MAX:
                penalty += 0.3 * (short - PASSAGE_STRIP_MAX) + (0.6 + (short - 1.85) if short > 1.85 else 0.0)

            # Where the room sits between road and rear.
            if mode == 0:
                depth = 0.5
            elif mode == 1:
                depth = (envelope.max_x - cx) / ew
            elif mode == 2:
                depth = (cx - envelope.min_x) / ew
            elif mode == 3:
                depth = (envelope.max_y - cy) / eh
            else:
                depth = (cy - envelope.min_y) / eh
            depth_terms.append(depth_fit(f.type, depth))

            # The room that receives the front door must actually reach the
            # frontage. A northerly centre is not enough: a foyer with the puja
            # packed in front of it has no road-facing wall, and the entrance
            # ends up on the side of the house.
            if level0 and f.entry and road is not None and not self._touches_road_edge(box, envelope, road):
                penalty += 0.18

            # Proportion: a gentle slope toward square, and a steep one past the
            # cap for this kind of room. See `proportion_penalty`.
            penalty += proportion_penalty(f.type, aspect)

            # Area fidelity: undersize is a defect, oversize merely costs money.
            ratio = w * h / f.target
            if f.fill and ratio >= 1.0:
                ratio = 1.0       # the terrace is whatever the rooms leave over
            deviation = abs(math.log(max(ratio, 0.12)))
            area_terms.append(max(0.0, 1.0 - deviation * (1.5 if ratio < 1 else 0.7)))

            # A room is never drawn at more than one and a half times what the
            # programme asked, nor as more than a quarter of the floor: a puja
            # twice its size and a living room that is a third of the plate are
            # how a plan comes to look out of proportion.
            if f.sized:
                if w * h > 1.5 * f.asked:
                    penalty += 0.08 + 0.25 * (w * h / (1.5 * f.asked) - 1.0)
                if w * h > 0.26 * envelope.area:
                    penalty += 0.10 + 0.6 * (w * h / (0.26 * envelope.area) - 1.0)

            # However large the plot, a room past its kind's sensible maximum
            # is a hall, not a room.
            if f.cap is not None and w * h > f.cap:
                penalty += 0.15 + 0.5 * (w * h / f.cap - 1.0)

            # The mean above hides outliers: one room at four times its target
            # among ten near theirs barely moves the average, which is how a
            # 22 m2 foyer survived. A gross miss is a penalty in its own right,
            # unbounded, so the search cannot buy it back with small gains
            # elsewhere.
            if ratio > 1.55 or ratio < 0.62:
                penalty += 0.10 * deviation
            # Circulation that grows is not generosity but an exploit: a foyer
            # the size of a living room touches every room and scores perfectly
            # on adjacency while wasting the floor area that paid for it.
            if f.circulation and ratio > 1.25:
                penalty += 0.22 * (ratio - 1.25)

            # Proportion, as a mean the other terms can trade against.
            shape_terms.append(1.0 if aspect <= 1.6 else max(0.0, 1.0 - (aspect - 1.6) / 1.5))

            # External-wall access, and how many faces are external. Two external
            # faces is what makes cross ventilation possible at all.
            faces = _external_faces(box, envelope)
            if f.outdoor and f.type is not RoomType.COURTYARD and faces == 0:
                penalty += 0.25         # a terrace or balcony is on the edge of the house, open to the sky
            if f.utility and faces == 0:
                penalty += 0.3          # a wash area with no outside wall has nowhere to vent or dry
            if f.needs_light:
                light_terms.append(0.0 if faces == 0 else (0.72 if faces == 1 else 1.0))
                # Averaged into light_terms, one landlocked bedroom among ten lit
                # rooms costs almost nothing. It is a statutory failure with no
                # local repair - you cannot add a window to a wall that is not
                # there - so it is priced as one.
                if faces == 0 and f.needs_daylight:
                    landlocked.append(len(refs) - 1)
            elif faces == 0:
                light_terms.append(1.0)          # interior room correctly interior

            # Orientation preference, from the brief and from Vastu.
            if f.bearing is not None:
                dx, dy = cx - cx0, cy - cy0
                if dx * dx + dy * dy < 1e-12:
                    raw = 0.0
                else:
                    raw = (math.degrees(math.atan2(dx, dy)) + north) % 360.0
                actual = _SECTOR_BEARING[int((raw + 11.25) % 360.0 // 22.5)]
                delta = abs(((actual - f.bearing) + 180) % 360 - 180)
                alignment = max(0.0, 1.0 - delta / 90.0)
                orientation_terms.append(alignment * f.orient_weight + (1 - f.orient_weight))

        # Which rooms can have a door between them: the one contact test the
        # circulation, adjacency and walkability terms all need.
        touch = _touch_matrix(rects)
        n = len(refs)

        # A room with no outside wall may still have a window onto a courtyard,
        # a verandah or a terrace; only one that has neither is landlocked, and
        # that is a statutory failure with no local repair.
        for p in landlocked:
            if not any(touch[p][q] and facts[refs[q]].outdoor for q in range(n)):
                penalty += 0.80

        # Circulation is overhead: a passage and a landing together should stay
        # under a tenth of the floor, and one short spine is better than two.
        passage_area = 0.0
        passage_at: list[int] = []
        stair_at: list[int] = []
        for p in range(n):
            f = facts[refs[p]]
            if f.passage:
                passage_at.append(p)
                bx = rects[p]
                passage_area += (bx.max_x - bx.min_x) * (bx.max_y - bx.min_y)
                run = max(bx.max_x - bx.min_x, bx.max_y - bx.min_y)
                if run > 6.5:
                    penalty += 0.06 * (run - 6.5)       # a short spine, not the whole depth of the house
            if f.stair:
                stair_at.append(p)
        penalty += corridor_penalty(passage_area / max(envelope.area, 1e-6))
        if stair_at and passage_at and not any(touch[p][s] for p in passage_at for s in stair_at):
            # An upper floor is entered from the stair; a landing that does not
            # meet it is a landing nobody reaches.
            penalty += 0.60

        # Adjacency: required pairs should touch, forbidden pairs should not.
        touching: set[tuple[RoomType, RoomType]] = set()
        for i in range(n):
            row = touch[i]
            ta = facts[refs[i]].type
            for j in range(i + 1, n):
                if row[j]:
                    tb = facts[refs[j]].type
                    touching.add((ta, tb))
                    touching.add((tb, ta))
        present = {facts[ri].type for ri in refs}
        adjacency_score = score_pairs(touching, present, self.brief.kind)[0]

        penalty += self._surrogate_relations(refs, rects, touch, facts)

        # Walkability. A dead-end room that touches no through-room can only
        # be entered through another dead end - a bedroom through a bedroom, a
        # kitchen through the master. That is the failure a client sees before
        # any other, so each such room is a penalty on its own, not a term
        # averaged away.
        penalty += self._surrogate_walkability(refs, touch)

        def mean(values: list[float], default: float = 0.7) -> float:
            return sum(values) / len(values) if values else default

        score = (
            0.17 * mean(area_terms)
            + 0.17 * mean(shape_terms)
            + 0.20 * mean(light_terms)
            + 0.06 * mean(orientation_terms, 0.75)
            + 0.22 * adjacency_score
            + 0.18 * mean(depth_terms)
        )
        return min(1.0, score - penalty)

    def set_below(self, below: list[tuple[RoomType, BoundingBox]]) -> None:
        """Tell this floor's search what lies beneath it.

        Two things follow. Wet rooms are steered off the kitchen, the dining
        room and the puja and onto the wet rooms below, and walls are steered
        onto the walls below, because a partition with nothing under it needs a
        beam and the structural engineer will say so.
        """
        self._below = below
        env = self._envelope
        xs: set[float] = set()
        ys: set[float] = set()
        vertical: dict[int, list[tuple[float, float]]] = {}
        horizontal: dict[int, list[tuple[float, float]]] = {}
        seen: set[tuple] = set()
        for _kind, b in below:
            for x in (b.min_x, b.max_x):
                if env.min_x + 0.5 < x < env.max_x - 0.5:
                    xs.add(round(x, 3))
                key = ("v", round(x, 2), round(b.min_y, 2), round(b.max_y, 2))
                if key not in seen:
                    seen.add(key)
                    vertical.setdefault(round(x * 5), []).append((b.min_y, b.max_y))
            for y in (b.min_y, b.max_y):
                if env.min_y + 0.5 < y < env.max_y - 0.5:
                    ys.add(round(y, 3))
                key = ("h", round(y, 2), round(b.min_x, 2), round(b.max_x, 2))
                if key not in seen:
                    seen.add(key)
                    horizontal.setdefault(round(y * 5), []).append((b.min_x, b.max_x))
        self._below_xs, self._below_ys = sorted(xs), sorted(ys)
        self._below_lines = (vertical, horizontal)
        self._carried_cache = {}

    def _borne_ratio(self, rects: list[BoundingBox], envelope: BoundingBox) -> float:
        """Estimate of the audit's measure: wall length that stands on a wall below.

        Perimeter walls always do; an interior wall does when a wall below runs
        within 0.2 m along it. Returns (perimeter + borne) / (perimeter + interior).
        """
        lines = self._below_lines
        if lines is None:
            return 1.0
        vertical, horizontal = lines
        tol = 0.02
        interior = borne = 0.0

        cache = self._carried_cache

        def carried(table: dict, coord: float, lo: float, hi: float) -> float:
            # The same edge turns up in most of a population, so it is
            # answered once.
            key = (id(table), round(coord, 2), round(lo, 2), round(hi, 2))
            hit = cache.get(key)
            if hit is not None:
                return hit
            k = round(coord * 5)
            total = 0.0
            for kk in (k - 1, k, k + 1):
                for l0, l1 in table.get(kk, ()):
                    overlap = min(hi, l1) - max(lo, l0)
                    if overlap > 0:
                        total += overlap
            result = min(total, hi - lo)
            cache[key] = result
            return result

        for b in rects:
            for x in (b.min_x, b.max_x):
                if abs(x - envelope.min_x) < tol or abs(x - envelope.max_x) < tol:
                    continue
                interior += (b.max_y - b.min_y) * 0.5
                borne += carried(vertical, x, b.min_y, b.max_y) * 0.5
            for y in (b.min_y, b.max_y):
                if abs(y - envelope.min_y) < tol or abs(y - envelope.max_y) < tol:
                    continue
                interior += (b.max_x - b.min_x) * 0.5
                borne += carried(horizontal, y, b.min_x, b.max_x) * 0.5
        perimeter = 2 * (envelope.width + envelope.height)
        return (perimeter + borne) / (perimeter + interior) if perimeter + interior > 0 else 1.0

    def _surrogate_relations(
        self,
        refs: list[int],
        rects: list[BoundingBox],
        touch: list[list[bool]],
        facts: list[_Facts],
    ) -> float:
        """The adjacencies a household checks first, priced one by one.

        The weighted programme averages them with thirty others, and an average
        lets a plan lose the kitchen-dining wall and make it up in daylight.
        These are the ones whose absence is the first thing anyone notices, so
        each is its own penalty: the foyer opens into the living room, the
        living and the kitchen both meet the dining room, no shrine shares a
        wall with a toilet, every bedroom meets the passage, and an upstairs
        bathroom never sits over a kitchen, a dining table or a puja.
        """
        by_type: dict[RoomType, list[int]] = {}
        for p, ri in enumerate(refs):
            by_type.setdefault(facts[ri].type, []).append(p)

        def meets(a: RoomType, b: RoomType) -> bool:
            return any(touch[i][j] for i in by_type.get(a, ()) for j in by_type.get(b, ()))

        penalty = 0.0
        # The master is the largest bedroom, and the dining room is smaller than
        # the living room: a plan where they are not reads as miscalculated.
        def biggest(kind: RoomType) -> float:
            return max((rects[p].area for p in by_type.get(kind, ())), default=0.0)

        master = biggest(RoomType.MASTER_BEDROOM)
        others = max(biggest(RoomType.BEDROOM), biggest(RoomType.GUEST_BEDROOM), biggest(RoomType.CHILDREN_BEDROOM))
        if master and others and master < 1.1 * others:
            penalty += 0.1 + 0.3 * (1.1 - master / others)
        living_area, dining_area = biggest(RoomType.LIVING), biggest(RoomType.DINING)
        if living_area and dining_area and dining_area > 0.85 * living_area:
            penalty += 0.1 + 0.3 * (dining_area / living_area - 0.85)

        if RoomType.FOYER in by_type and RoomType.LIVING in by_type and not meets(RoomType.FOYER, RoomType.LIVING):
            penalty += 0.60
        if RoomType.KITCHEN in by_type and RoomType.DINING in by_type and not meets(RoomType.KITCHEN, RoomType.DINING):
            penalty += 0.60
        if RoomType.LIVING in by_type and RoomType.DINING in by_type and not meets(RoomType.LIVING, RoomType.DINING):
            penalty += 0.50

        for i in by_type.get(RoomType.PUJA, ()):
            for wet in _WET_TYPES:
                for j in by_type.get(wet, ()):
                    if _loose_touch(rects[i], rects[j]):
                        penalty += 0.80

        if RoomType.UTILITY in by_type and RoomType.KITCHEN in by_type and not meets(RoomType.UTILITY, RoomType.KITCHEN):
            penalty += 0.25         # the wash area opens off the kitchen

        # A passage that reaches fewer than three rooms is a stub, not a passage.
        for p, ri in enumerate(refs):
            if facts[ri].corridor:
                served = sum(1 for q in range(len(refs)) if touch[p][q])
                if served < 3:
                    penalty += 0.12 * (3 - served)

        # A bedroom that asked for its own bathroom has to touch one.
        for p, ri in enumerate(refs):
            if facts[ri].ensuite and not any(touch[p][q] and facts[refs[q]].type is RoomType.BATHROOM
                                             for q in range(len(refs))):
                penalty += 0.50

        passages = [p for p, ri in enumerate(refs) if facts[ri].passage]
        if passages:
            for p, ri in enumerate(refs):
                if facts[ri].bedroom and not any(touch[p][q] for q in passages):
                    penalty += 0.40

        below = self._below
        if below:
            ratio = self._borne_ratio(rects, self._envelope)
            if ratio < 0.76:
                penalty += 4.0 * (0.76 - ratio)
            for p, ri in enumerate(refs):
                f = facts[ri]
                if not f.wet:
                    continue
                box = rects[p]
                area = max(box.area, 1e-6)
                bad = stacked = 0.0
                for kind, under in below:
                    dx = min(box.max_x, under.max_x) - max(box.min_x, under.min_x)
                    dy = min(box.max_y, under.max_y) - max(box.min_y, under.min_y)
                    if dx <= 0 or dy <= 0:
                        continue
                    if kind in _NO_WET_ABOVE:
                        bad += dx * dy
                    elif kind in _WET_TYPES:
                        stacked += dx * dy
                over = min(1.0, bad / area)
                penalty += 0.9 * over + (0.7 if over > 0.2 else 0.0)
                penalty -= 0.04 * min(1.0, stacked / area)
        return penalty

    def _surrogate_walkability(self, refs: list[int], touch: list[list[bool]]) -> float:
        """Rooms with no legal way in, and through-rooms that do not form one chain."""
        facts = self._facts
        assert facts is not None
        door_ok = self._door_ok
        n = len(refs)

        # The same question the door placer will ask, so the search produces
        # layouts the placer can connect legally. Two rules kept in two places
        # drift apart, and then the search converges on plans whose doors the
        # placer has to cut through a bedroom.
        penalty = 0.0
        bath_without_passage: list[int] = []
        sole: dict[int, int] = {}          # room -> how many rooms can only be entered from it
        for i in range(n):
            fi = facts[refs[i]]
            if fi.through:
                continue
            row, ok = touch[i], door_ok[refs[i]]
            if fi.type is RoomType.BATHROOM:
                # Off the passage, or the one bathroom a bedroom may host: a
                # bedroom with a third door is a thoroughfare. Settled below.
                if not any(row[j] and facts[refs[j]].passage for j in range(n)):
                    bath_without_passage.append(i)
                continue
            # The door must come from somewhere the door tree reaches on its
            # own: a through-room, or this room's private host. A kitchen whose
            # only legal neighbour is the utility passed this test and was then
            # doored from the staircase.
            parents = [j for j in range(n) if row[j] and ok[refs[j]]]
            if not parents:
                # A bedroom cut off is worse than a store cut off.
                penalty += 0.60 if fi.habitable else 0.50
            elif len(parents) == 1:
                sole[parents[0]] = sole.get(parents[0], 0) + 1

        # A living or dining room that is the only way into four rooms has four
        # doors and a plan that reads as one big room with cupboards.
        for j, dependants in sole.items():
            if dependants > 2 and facts[refs[j]].type in (RoomType.LIVING, RoomType.DINING, RoomType.FAMILY):
                penalty += 0.25 * (dependants - 2)

        spare = {j: 1 for j in range(n) if facts[refs[j]].bedroom}
        for i in bath_without_passage:
            host = next((j for j in range(n) if touch[i][j] and spare.get(j, 0) > 0), None)
            if host is None:
                penalty += 0.60
            else:
                spare[host] -= 1

        # The through-rooms must form ONE connected chain. Each touching some
        # other through-room is not enough: foyer-living on one side of the
        # plot and dining-corridor on the other both pass that test, and the
        # only bridge between the two islands runs through a bedroom. So this
        # counts islands, and every island beyond the first is a bedroom
        # somebody has to walk through.
        through = [p for p in range(n) if facts[refs[p]].through]
        if len(through) > 1:
            parent = {p: p for p in through}

            def find(x: int) -> int:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for a_idx, p in enumerate(through):
                for q in through[a_idx + 1:]:
                    if touch[p][q]:
                        parent[find(p)] = find(q)
            islands = len({find(p) for p in through})
            # Steep on purpose. With fifteen rooms the other terms sum to a
            # lot, and at 0.3 the search happily paid it to buy a better area
            # fit - leaving the passage reachable only through the kitchen.
            penalty += 1.0 * (islands - 1)

            # The passage in particular must meet the public rooms directly:
            # a hall reached from the living or dining room is a hall; one
            # reached from anywhere else is a breach waiting to be cut. On an
            # upper floor the stair is the public room.
            public = _PUBLIC_FOR_PASSAGE
            for p in through:
                if not facts[refs[p]].corridor:
                    continue
                met = any(
                    facts[refs[q]].type in public and touch[p][q] for q in through if q != p
                )
                if not met:
                    penalty += 0.60
        return penalty

    def _touches_road_edge(self, box: BoundingBox, envelope: BoundingBox, road) -> bool:
        bearing = (road.bearing + self.brief.site.north_angle) % 360
        tol = 0.05
        if bearing < 45 or bearing >= 315:
            return box.max_y >= envelope.max_y - tol
        if 45 <= bearing < 135:
            return box.max_x >= envelope.max_x - tol
        if 135 <= bearing < 225:
            return box.min_y <= envelope.min_y + tol
        return box.min_x <= envelope.min_x + tol

    def _vastu_direction(self, room_type: RoomType) -> Direction | None:
        """Ideal Vastu direction for a room type, when the brief asks for it."""
        if not self.brief.vastu.is_constraining:
            return None
        try:
            from aip.engines.vastu.knowledge import ideal_direction

            return ideal_direction(room_type)
        except Exception:
            return None

    def _tournament(self, population: list[Genome]) -> Genome:
        contenders = self.rng.sample(population, min(self.config.tournament, len(population)))
        return max(contenders, key=lambda g: g.fitness)

    # ---------------------------------------------------------- fitness ----

    def _default_fitness(self, plan: FloorPlan) -> tuple[float, dict[str, float]]:
        """Analytical fitness. No model call, so it is free and instant."""
        from aip.engines.architecture.codes import compliance_analysis
        from aip.engines.architecture.metrics import analyse_all

        reports = analyse_all(plan, self.brief)
        compliance = compliance_analysis(plan, self.brief)

        weights = self.brief.priority_weights()
        breakdown = {
            "daylight": reports["daylight"].score,
            "ventilation": reports["ventilation"].score,
            "privacy": reports["privacy"].score,
            "circulation": reports["circulation"].score,
            "accessibility": reports["accessibility"].score,
            "spatial": reports["spatial"].score,
            "compliance": compliance.score,
            "programme": self._programme_fit(plan),
            "layout": self._layout_sense(plan),
        }

        score = (
            weights.get("daylight", 0.16) * breakdown["daylight"]
            + weights.get("ventilation", 0.16) * breakdown["ventilation"]
            + weights.get("privacy", 0.16) * breakdown["privacy"]
            + weights.get("circulation", 0.16) * breakdown["circulation"]
        )
        # Compliance, spatial usability, programme fit and functional layout are
        # not client preferences - they are prerequisites, so they carry fixed
        # weight. `layout` is weighted comparably to compliance deliberately: a
        # kitchen across the house from the dining room is not a lesser defect
        # than an undersized window, and weighting it lower is precisely how the
        # search previously produced plans that passed every check and made no
        # sense to walk through.
        score = 0.38 * score + 0.24 * breakdown["compliance"] + 0.13 * breakdown["spatial"]
        score += 0.08 * breakdown["programme"] + 0.05 * breakdown["accessibility"]
        score += 0.12 * breakdown["layout"]

        # Proportion and circulation, priced on the finished rooms exactly as
        # the surrogate priced them on rectangles: a plan whose best bedroom is
        # a 3:1 slot, or that spends a seventh of each floor on passage, loses
        # to one that does not however well the physics scored it.
        slots = sum(proportion_penalty(r.type, r.bbox.aspect_ratio) for r in plan.all_rooms)
        passage = 0.0
        for level in plan.levels:
            built = sum(r.area for r in level.rooms) or 1.0
            passage += corridor_penalty(sum(
                r.area for r in level.rooms if r.type in (RoomType.CORRIDOR, RoomType.LOBBY)
            ) / built)
        breakdown["proportion"] = max(0.0, 1.0 - slots)
        breakdown["passage"] = max(0.0, 1.0 - passage)
        score -= min(0.40, 0.5 * slots + 0.5 * passage)

        if self.brief.vastu.is_constraining:
            try:
                from aip.engines.vastu.engine import quick_vastu_score

                vastu = quick_vastu_score(plan, self.brief.tradition_weight)
                breakdown["vastu"] = vastu
                # A strict or orthodox client asked for Vastu first: it weighs more.
                weight = 0.10 + (0.35 if self.brief.tradition_weight >= 0.8 else 0.20) * self.brief.tradition_weight
                score = score * (1 - weight) + vastu * weight
            except Exception:  # pragma: no cover - Vastu is optional in fitness
                pass

        return round(max(0.0, min(1.0, score)), 5), {k: round(v, 4) for k, v in breakdown.items()}

    def _layout_sense(self, plan: FloorPlan) -> float:
        """Does the plan work as a building, not just as a set of rooms?"""
        from aip.engines.architecture.programme import evaluate

        scores = [
            evaluate(plan, self.brief, level.index).score
            for level in plan.levels if len(level.rooms) > 1
        ]
        return sum(scores) / len(scores) if scores else 0.0

    def _programme_fit(self, plan: FloorPlan) -> float:
        """How closely realised room areas match what the brief asked for."""
        rooms = plan.all_rooms
        if not rooms:
            return 0.0
        errors: list[float] = []
        for room in rooms:
            target = float(room.metadata.get("target_area", 0.0))
            if target <= 0:
                continue
            ratio = room.area / target
            # Undersize hurts more than oversize: a small bedroom is a defect,
            # a generous one is a bonus that only costs money.
            errors.append(1.0 - min(1.0, abs(math.log(max(ratio, 0.15))) * (1.4 if ratio < 1 else 0.8)))
        return sum(errors) / len(errors) if errors else 0.6

    # ------------------------------------------------------- realisation ---

    def _to_plan(self, genome: Genome) -> FloorPlan:
        """Convert a single-level genome into a fully-detailed FloorPlan."""
        return self._assemble([self._realise_level(genome, self._level_index)])

    def _realise_level(self, genome: Genome, level_index: int) -> list[Room]:
        """The rooms of one floor: the genome's partition of the footprint."""
        boxes = realise(genome.tree, self._envelope)
        rooms: list[Room] = []
        for slot, box in sorted(boxes.items()):
            req = self.requirements[genome.assignment[slot]]
            polygon = rectangle(Vec2(box.min_x, box.min_y), box.width, box.height)
            rooms.append(Room(
                name=req.label or req.type.label,
                type=req.type,
                polygon=polygon,
                level=level_index,
                ceiling_height=3.0,
                metadata={"target_area": req.target_area, "slot": slot,
                          "brief_area": req.asked_area or req.target_area},
            ))
        return rooms

    def _assemble(self, rooms_by_level: list[list[Room]]) -> FloorPlan:
        """Walls, stairs, structure and openings for realised floors."""
        envelope = self._envelope
        levels: list[Level] = []
        for level_index, rooms in enumerate(rooms_by_level):
            if not rooms:
                continue
            levels.append(
                Level(
                    index=level_index,
                    elevation=level_index * 3.15,
                    floor_to_floor=3.15,
                    rooms=rooms,
                    walls=self._build_walls(rooms, envelope, level_index),
                    staircases=self._build_stairs(rooms, level_index),
                )
            )

        plan = FloorPlan(
            name="Generated Scheme",
            site=self.brief.site,
            levels=levels,
            structural_system=StructuralSystem.RCC_FRAME,
            style=self.brief.style.primary.value,
        )
        plan.column_grid = self._build_column_grid(envelope)
        # A drawn parti is not shuffled: swapping room identities to mend a
        # door is the search's repair, and it moves a car porch to the back.
        self._place_openings(plan, envelope, repair=not getattr(self, "_open_outline", False))
        return plan

    # ------------------------------------------------------------- walls ---

    def _build_walls(self, rooms: list[Room], envelope: BoundingBox, level_index: int) -> list[Wall]:
        """Derive the wall set from room rectangles: one wall for each stretch of line.

        A large room routinely abuts two smaller ones, so its single long edge
        meets two short ones at a T-junction. Drawing one wall per room edge
        gives three walls on the same line, two of them lying on top of the
        third; the DXF, the quantities and the cost then count that wall twice.
        Instead every line is cut at each point where any room's edge starts or
        stops, and each stretch between is one wall, carrying both rooms that
        meet there. Neighbouring stretches shared by the same rooms are joined,
        so a wall between two rooms is still one wall however long it is.
        """
        tol = 1e-6
        by_id = {room.id: room for room in rooms}
        # (orientation, coordinate) -> [(from, to, room id)]
        lines: dict[tuple[str, float], list[tuple[float, float, str]]] = {}
        for room in rooms:
            box = room.bbox
            for y in (box.min_y, box.max_y):
                lines.setdefault(("h", round(y, 3)), []).append((box.min_x, box.max_x, room.id))
            for x in (box.min_x, box.max_x):
                lines.setdefault(("v", round(x, 3)), []).append((box.min_y, box.max_y, room.id))

        walls: list[Wall] = []
        for (orientation, coord), edges in sorted(lines.items()):
            cuts = sorted({round(v, 6) for lo, hi, _r in edges for v in (lo, hi)})
            runs: list[list] = []                         # [lo, hi, rooms]
            for lo, hi in zip(cuts, cuts[1:], strict=False):
                if hi - lo < tol:
                    continue
                here = [r for a, z, r in edges if a <= lo + tol and z >= hi - tol]
                if not here:
                    continue
                key = tuple(sorted(here))
                if runs and abs(runs[-1][1] - lo) < tol and tuple(sorted(runs[-1][2])) == key:
                    runs[-1][1] = hi
                else:
                    runs.append([lo, hi, list(dict.fromkeys(here))])
            for lo, hi, ids in runs:
                if orientation == "h":
                    start, end = Vec2(lo, coord), Vec2(hi, coord)
                else:
                    start, end = Vec2(coord, lo), Vec2(coord, hi)
                on_envelope = _is_on_envelope(start, end, envelope)
                height = 3.0
                if on_envelope:
                    kind, thickness = WallKind.EXTERIOR, WALL_THICKNESS_EXTERIOR
                elif len(ids) > 1:
                    kind, thickness = WallKind.INTERIOR, WALL_THICKNESS_INTERIOR
                elif getattr(self, "_open_outline", False):
                    # A house that is not a rectangle (an L, a court): a wall with a
                    # room on one side only is an outside wall, garden beyond.
                    kind, thickness = WallKind.EXTERIOR, WALL_THICKNESS_EXTERIOR
                    on_envelope = True
                else:
                    # A wall bounding exactly one room and not on the envelope is a
                    # stub - the neighbouring cell was degenerate. A partition.
                    kind, thickness = WallKind.PARTITION, WALL_THICKNESS_INTERIOR
                # The edge of a terrace or balcony is a railing, not a wall: it is
                # open to the sky on the outside and only 1.1 m high.
                if on_envelope and all(by_id[r].type.is_outdoor for r in ids):
                    kind, height = WallKind.PARAPET, 1.1
                walls.append(Wall(
                    start=start, end=end, thickness=thickness, height=height, kind=kind, rooms=ids,
                ))
        return walls

    def _build_stairs(self, rooms: list[Room], level_index: int) -> list[Staircase]:
        if self.brief.levels <= 1 or level_index >= self.brief.levels - 1:
            return []
        stair_room = next((r for r in rooms if r.type is RoomType.STAIRCASE), None)
        if stair_room is None:
            return []

        rise = 3.15
        # Choose a riser that divides the floor-to-floor into a whole number of
        # steps at or below the 190 mm statutory maximum.
        steps = math.ceil(rise / 0.185)
        riser = rise / steps
        box = stair_room.bbox
        going_available = max(box.width, box.height) - 0.3
        tread = max(0.25, min(0.30, going_available / max(1, math.ceil(steps / 2) - 1)))

        return [
            Staircase(
                polygon=stair_room.polygon,
                from_level=level_index,
                to_level=level_index + 1,
                kind="dog_leg",
                tread=round(tread, 3),
                riser=round(riser, 4),
                width=round(max(1.0, min(box.width, box.height) / 2 - 0.1), 3),
                rise_total=rise,
                headroom=2.15,
            )
        ]

    def _build_column_grid(self, envelope: BoundingBox) -> ColumnGrid:
        """Regular RCC grid sized to economical spans.

        3.0-4.5 m bays keep beam depths and slab thickness at their cheapest for
        Indian residential construction; the grid is chosen to hit that band.
        """
        def spacings(total: float) -> list[float]:
            bays = max(1, round(total / 3.8))
            span = total / bays
            while span > 4.8 and bays < 12:
                bays += 1
                span = total / bays
            return [round(span, 3)] * bays

        return ColumnGrid(
            system=StructuralSystem.RCC_FRAME,
            x_spacings=spacings(envelope.width),
            y_spacings=spacings(envelope.height),
            origin=Vec2(envelope.min_x, envelope.min_y),
            column_size=(0.23, 0.45),
            beam_depth=0.45,
            slab_thickness=0.125,
        )

    # ---------------------------------------------------------- openings ---

    def _place_openings(
        self, plan: FloorPlan, envelope: BoundingBox, *, repair: bool = True
    ) -> None:
        """Place the main door, internal doors and windows.

        Doors are placed on a spanning tree of the adjacency graph rooted at the
        entrance, which guarantees every room is reachable - the single most
        common failure in naively generated plans. Windows are sized to satisfy
        the statutory light and ventilation ratios, biased toward the best
        daylight orientation for the site's latitude.
        """
        from aip.engines.architecture.metrics import OPENABLE_FRACTION
        from aip.engines.architecture.solar import daylight_quality_by_orientation

        quality = daylight_quality_by_orientation(plan.site.latitude)

        for level in plan.levels:
            if repair:
                self._repair_circulation(plan, level)
            self._place_doors(plan, level)
            for room in level.rooms:
                if room.type.is_outdoor or room.type is RoomType.SHAFT:
                    continue
                needs_light = room.type.is_habitable or room.type.is_wet
                if not needs_light:
                    continue

                exterior = [
                    w for w in level.walls
                    if room.id in w.rooms and w.kind is WallKind.EXTERIOR
                ]
                if not exterior and room.type.is_habitable:
                    # No outside wall: a window may open onto a courtyard, a
                    # verandah or a terrace that this room shares a wall with.
                    exterior = [
                        w for w in level.walls
                        if room.id in w.rooms and any(
                            other.type.is_outdoor and other.id in w.rooms
                            for other in level.rooms if other.id != room.id
                        )
                    ]
                if not exterior:
                    continue

                # Two statutory requirements govern the aperture:
                #   light  - glazed area >= 1/10 of the floor area
                #   air    - *openable* area >= 1/6 of the floor area
                # Only a fraction of a window actually opens, so the ventilation
                # requirement has to be divided by that fraction before sizing.
                # Skipping that division is the classic under-glazing error.
                # A kitchen is wet for its plumbing, but it is a room people work
                # in for hours over a hot stove: it gets a real window over the
                # counter, sized to the ventilation rule, not a bathroom's vent.
                kitchen = room.type is RoomType.KITCHEN
                wet_vent = room.type.is_wet and not kitchen
                kind = OpeningKind.VENTILATOR if wet_vent else OpeningKind.WINDOW
                openable_fraction = OPENABLE_FRACTION.get(kind, 0.7)
                required = max(room.area * 0.11, (room.area / 6) / openable_fraction)
                if room.type.is_habitable or kitchen:
                    # The code is a floor, not a design: rooms are glazed to about
                    # a sixth of their floor, as a practice would draw them.
                    required = max(required, room.area * 0.17)
                if wet_vent:
                    required = min(required, 1.4)

                ranked = sorted(
                    exterior,
                    key=lambda w: quality.get(_wall_direction(plan, w), 0.5),
                    reverse=True,
                )
                # Prefer two orientations when available: cross ventilation is
                # worth more in a hot-humid climate than any amount of glazing on
                # a single face, so the area is split across both walls rather
                # than concentrated on the best-lit one.
                chosen = _pick_cross_ventilating(plan, ranked)
                if not chosen:
                    continue

                # The glass is shared by how well each face is lit: the cooler,
                # better face takes more of it, the hot one less.
                faces = [_wall_direction(plan, w) for w in chosen]
                weights = [max(0.15, quality.get(d, 0.5)) for d in faces]
                # Every outside window is built with a 0.55 m chajja over it
                # (see the 3D builder): about half the opening is shaded.
                room.metadata["shading_factor"] = max(float(room.metadata.get("shading_factor", 0.0)), 0.5)
                for wall, face, weight in zip(chosen, faces, weights):
                    share = required * weight / sum(weights)
                    usable_length = max(0.6, wall.length - 0.6)
                    height = 0.75 if wet_vent else 1.2 if kitchen else 1.5
                    width = min(usable_length, max(0.6, share / height))
                    # Low western sun gets under a chajja; a west window in a room
                    # people live in also gets vertical fins (drawn in 3D), which
                    # shade it about three-quarters.
                    fins = room.type.is_habitable and face in HOT_FACES
                    if fins:
                        room.metadata["shading_factor"] = max(float(room.metadata["shading_factor"]), 0.75)
                    wall.openings.append(
                        Opening(
                            kind=kind,
                            wall_id=wall.id,
                            position=0.5,
                            width=round(width, 3),
                            height=height,
                            sill_height=1.8 if wet_vent else 1.05 if kitchen else 0.9,
                            notes="fins" if fins else "",
                        )
                    )

    @staticmethod
    def _door_adjacency(plan: FloorPlan, level: Level) -> dict[str, set[str]]:
        """Adjacency restricted to pairs that share enough wall for a door."""
        from aip.domain.geometry import shared_edge

        graph: dict[str, set[str]] = {r.id: set() for r in level.rooms}
        rooms = level.rooms
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                edge = shared_edge(a.polygon, b.polygon)
                if edge is not None and edge[0].distance_to(edge[1]) >= DOOR_WALL:
                    graph[a.id].add(b.id)
                    graph[b.id].add(a.id)
        return graph

    def _legally_reachable(self, level: Level, adjacency: dict[str, set[str]], plan: FloorPlan | None = None) -> set[str]:
        """Rooms a legal door tree can reach from the entrance.

        The same walk the door placer performs, without cutting anything: grow
        only out of through-rooms, enter only where the programme allows.
        Whatever it cannot reach, the placer will only reach by breaching.
        """
        from aip.engines.architecture.programme import is_through, may_enter

        rooms = {r.id: r for r in level.rooms}
        if not rooms:
            return set()
        root = self._entry_room(level, plan).id
        seen = {root} | {r.id for r in level.rooms if r.type is RoomType.GARAGE}   # a porch opens to the drive
        frontier = [root]
        while frontier:
            node = frontier.pop()
            if not is_through(rooms[node].type):
                continue
            for nxt in adjacency.get(node, set()):
                if nxt in seen or not may_enter(rooms[nxt].type, rooms[node].type):
                    continue
                seen.add(nxt)
                frontier.append(nxt)
        # Attached rooms hang off hosts that are not through-rooms.
        changed = True
        while changed:
            changed = False
            for rid, room in rooms.items():
                if rid in seen:
                    continue
                for host in adjacency.get(rid, set()):
                    if host in seen and may_enter(room.type, rooms[host].type)                             and not is_through(rooms[host].type):
                        seen.add(rid)
                        changed = True
                        break
        return seen

    def _repair_circulation(self, plan: FloorPlan, level: Level) -> None:
        """Swap room identities until every room has a legal way in.

        Geometry is left alone: a swap exchanges which room a cell *is*, not
        where the cell sits, so nothing statutory the search already satisfied
        is disturbed. It is what an architect does with a plan that is nearly
        right - "that bedroom and the kitchen should change places" - and it
        is cheap enough to try every pairing.
        """
        adjacency = self._door_adjacency(plan, level)
        rooms = list(level.rooms)
        by_id = {r.id: r for r in rooms}

        def unreachable() -> list[str]:
            reached = self._legally_reachable(level, adjacency, plan)
            return [r.id for r in rooms if r.id not in reached]

        from aip.engines.architecture.programme import is_through

        stuck = unreachable()
        attempts = 0
        while stuck and attempts < 12:
            attempts += 1
            improved = False
            for stuck_id in stuck:
                a = by_id[stuck_id]
                # A through-room is the spine: never swap one out of its place
                # and never swap a dead end into it. The first version of this
                # traded the living room into the rear of the house to make a
                # bedroom "reachable", which made every count go up and the
                # plan unusable.
                if is_through(a.type):
                    continue
                # Candidates: dead-end rooms whose area is close enough that
                # the swap does not wreck either programme entry.
                candidates = sorted(
                    (b for b in rooms if b.id != a.id and a.type is not b.type
                     and not is_through(b.type)
                     and 0.6 <= (b.area / max(a.area, 1e-6)) <= 1.7),
                    key=lambda b: abs(b.area - a.area),
                )
                for b in candidates:
                    a.type, b.type = b.type, a.type
                    a.name, b.name = b.name, a.name
                    after = unreachable()
                    if len(after) < len(stuck):
                        stuck = after
                        improved = True
                        plan.metadata.setdefault("circulation_repairs", []).append(
                            f"swapped {a.display_name()} and {b.display_name()}"
                        )
                        break
                    a.type, b.type = b.type, a.type
                    a.name, b.name = b.name, a.name
                if improved:
                    break
            if not improved:
                break

    def _place_doors(self, plan: FloorPlan, level: Level) -> None:
        """Connect every room via a spanning tree rooted at the entrance."""
        from aip.domain.geometry import shared_edge

        # A car porch is open to the drive: it is entered from outside, and is
        # given an inside door only where it meets the utility, foyer or passage.
        porch = {r.id for r in level.rooms if r.type is RoomType.GARAGE
                 and not any(by.type in (RoomType.UTILITY, RoomType.FOYER, RoomType.LOBBY, RoomType.CORRIDOR)
                             for by in level.rooms if by is not r and _shared_length(by, r) >= DOOR_WALL)}
        rooms = {r.id: r for r in level.rooms if r.id not in porch}
        if not rooms:
            return
        adjacency = {k: v - porch for k, v in self._door_adjacency(plan, level).items() if k not in porch}

        root = self._entry_room(level, plan).id

        # Prim-style traversal preferring links through circulation space, which
        # yields a plan where rooms open off a hall rather than through each other.
        connected = {root}
        frontier: list[tuple[float, str, str]] = []

        from aip.engines.architecture.programme import (
            PRIVATE_HOST,
            door_cost_factor,
            is_through,
            may_enter,
        )

        # A dead-end room is a leaf of the door tree: it can be entered, but the
        # tree never grows *out* of it. That single rule is what stops a plan
        # routing the household through a bedroom to reach the kitchen. The
        # only exception is a room whose correct host is itself private - an
        # attached bathroom opens from its bedroom, and that is the right door.
        def may_expand_from(node: str) -> bool:
            return is_through(rooms[node].type)

        # A bedroom that asked for an attached bathroom claims the bathroom
        # beside it before the passage can. Offered from the passage first -
        # it is nearer the passage's centre - the en-suite became a common
        # bathroom with the master's door bricked up.
        reserved: dict[str, str] = {}
        # A plan that says whose bath is whose is taken at its word.
        for r in level.rooms:
            owner = r.metadata.get("suite_of")
            if r.type in (RoomType.BATHROOM, RoomType.WARDROBE) and owner in rooms and owner in adjacency.get(r.id, set()):
                reserved[r.id] = owner
        for host in sorted(level.rooms, key=lambda r: r.type is not RoomType.MASTER_BEDROOM):
            if host.id in reserved.values():
                continue
            if not self._wants_attached(host):
                continue
            candidates = [
                n for n in adjacency.get(host.id, set())
                if rooms[n].type is RoomType.BATHROOM and n not in reserved and not rooms[n].metadata.get("common")
            ]
            if candidates:
                best = max(candidates, key=lambda n: _shared_length(rooms[host.id], rooms[n]))
                reserved[best] = host.id

        def push(node: str, *, strict: bool = True) -> None:
            if strict and not may_expand_from(node):
                return
            for neighbour in adjacency.get(node, set()):
                if neighbour in connected:
                    continue
                if strict and reserved.get(neighbour, node) != node:
                    continue
                a, b = rooms[node], rooms[neighbour]
                # Where may this room's door come from? In the strict pass a
                # bedroom is not offered a door off the foyer at any price;
                # only the fallback, which records the breach, may cut one.
                if strict and not may_enter(b.type, a.type):
                    continue
                cost = a.centre.distance_to(b.centre)

                if a.type.is_circulation or b.type.is_circulation:
                    cost *= 0.35
                if b.metadata.get("enter_from") == a.id:
                    cost *= 0.02          # the door the plan was drawn for

                # Everything else comes from the declared programme rather than
                # from heuristics maintained separately here, so the doors the
                # plan ends up with cannot contradict the adjacency rules the
                # same plan is scored against.
                cost *= door_cost_factor(a.type, b.type, self.brief.kind)
                # The living and dining rooms are not the house's hall. A study,
                # a puja or a bedroom opens off the passage when it touches one;
                # it takes the living room's door only when nothing else is there.
                if (
                    a.type in (RoomType.LIVING, RoomType.DINING, RoomType.FAMILY)
                    and not b.type.is_circulation
                    and b.type not in (RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN, RoomType.FAMILY)
                ):
                    cost *= 2.5
                # The stair is reached from the hall or the foyer, not through a
                # door at the bottom of the dining room.
                if b.type is RoomType.STAIRCASE and a.type in (RoomType.DINING, RoomType.KITCHEN, RoomType.FAMILY):
                    cost *= 3.0
                frontier.append((cost, node, neighbour))

        # Attached rooms hang off their host regardless of the through-rule.
        def push_attached(node: str) -> None:
            for neighbour in adjacency.get(node, set()):
                if neighbour in connected:
                    continue
                hosts = PRIVATE_HOST.get(rooms[neighbour].type, ())
                if rooms[node].type in hosts:
                    # A bathroom takes a bedroom's spare door before a balcony
                    # does: the balcony can be reached from the landing.
                    frontier.append((0.3 if rooms[neighbour].type.is_outdoor else 0.05, node, neighbour))
                # An attached bathroom: the one reserved for this host.
                if reserved.get(neighbour) == node:
                    frontier.append((0.05, node, neighbour))
                # A bathroom no passage reaches, beside a bedroom, is that
                # bedroom's bathroom. The alternative is a door from the
                # kitchen or nothing.
                elif (
                    rooms[neighbour].type is RoomType.BATHROOM
                    and rooms[node].type in _BEDROOMS
                    and neighbour not in reserved
                    and not any(
                        is_through(rooms[n].type) and may_enter(RoomType.BATHROOM, rooms[n].type)
                        for n in adjacency.get(neighbour, set())
                    )
                ):
                    frontier.append((0.08, node, neighbour))

        # A bedroom has its own door and, at most, its bathroom's: two doors.
        # A third - the balcony, the wardrobe, the study - makes the room a
        # thoroughfare, and the room that needs it is reached some other way.
        doors: dict[str, int] = {}
        deferred: set[tuple[str, str]] = set()

        def cut_door(source: str, target: str) -> None:
            wall = _wall_between(level, source, target)
            if wall is not None:
                edge = shared_edge(rooms[source].polygon, rooms[target].polygon)
                width = 0.9
                kind = OpeningKind.DOOR
                pair = {rooms[source].type, rooms[target].type}
                span = edge[0].distance_to(edge[1]) if edge is not None else 0.0
                if pair == {RoomType.LIVING, RoomType.DINING} and span >= 1.9:
                    # Eating and gathering are one room in an Indian household:
                    # the dining room opens into the living room, it is not a
                    # room you knock to enter.
                    kind, width = OpeningKind.ARCH, min(2.4, span - 0.5)
                elif pair == {RoomType.DINING, RoomType.KITCHEN} and span >= 1.5:
                    kind, width = OpeningKind.ARCH, min(1.5, span - 0.4)
                elif edge is not None:
                    width = min(1.05, max(0.75, span - 0.4))
                wall.openings.append(
                    Opening(
                        kind=kind,
                        wall_id=wall.id,
                        position=0.5,
                        width=round(width, 3),
                        height=2.1,
                        sill_height=0.0,
                        connects=(source, target),
                    )
                )
            doors[source] = doors.get(source, 0) + 1
            doors[target] = doors.get(target, 0) + 1

        push(root)
        held: list[tuple[float, str, str]] = []
        capped = True
        while True:
            if not frontier or len(connected) >= len(rooms):
                # A door held back because its bedroom already had two is cut
                # now if the room behind it has no other legal way in: a
                # bathroom through its bedroom's third door is a poorer plan
                # than one through its second, and a far better one than a
                # bathroom entered from the stair.
                relaxed = [h for h in held if rooms[h[2]].type in _WET_TYPES]
                if capped and relaxed and len(connected) < len(rooms):
                    capped = False
                    frontier.extend(relaxed)
                    held = [h for h in held if h not in relaxed]
                    continue
                break
            frontier.sort()
            _cost, source, target = frontier.pop(0)
            if target in connected:
                continue
            if capped and rooms[source].type in _BEDROOMS and doors.get(source, 0) >= 2:
                held.append((_cost, source, target))
                continue
            # A living or dining room that already has three doors is a hall with
            # furniture in it. Another door off it waits its turn behind every
            # route that does not use it; it is cut only if nothing else gets
            # there first.
            if (
                doors.get(source, 0) >= 3 and not rooms[source].type.is_circulation
                and (source, target) not in deferred
            ):
                deferred.add((source, target))
                frontier.append((_cost * 4.0, source, target))
                continue
            cut_door(source, target)
            connected.add(target)
            push(target)
            push_attached(target)

        # Anything still unconnected has no route that obeys the through-rule.
        # Connect it anyway so the plan is not physically sealed, but record
        # the breach: the fitness and the report both need to know a bedroom
        # is only reachable through somewhere it should not be.
        if len(connected) < len(rooms):
            for node in list(connected):
                push(node, strict=False)
            while frontier and len(connected) < len(rooms):
                frontier.sort()
                _cost, source, target = frontier.pop(0)
                if target in connected:
                    continue
                wall = _wall_between(level, source, target)
                if wall is not None:
                    wall.openings.append(Opening(
                        kind=OpeningKind.DOOR, wall_id=wall.id, position=0.5,
                        width=0.9, height=2.1, sill_height=0.0,
                        connects=(source, target),
                    ))
                    plan.metadata.setdefault("circulation_breaches", []).append(
                        f"{rooms[target].display_name()} is reached through "
                        f"{rooms[source].display_name()}"
                    )
                connected.add(target)
                push(target, strict=False)

        # The foyer opens into the living room: you arrive, and you are received.
        # The spanning tree may reach the living room another way (through the
        # dining room, say) and leave the two sharing a wall with no door in it.
        if level.index == 0:
            foyer = next((r for r in level.rooms if r.type is RoomType.FOYER), None)
            living = next((r for r in level.rooms if r.type is RoomType.LIVING), None)
            if (
                foyer is not None and living is not None
                and living.id in adjacency.get(foyer.id, set())
                and not any(
                    o.kind.is_door and o.connects and {foyer.id, living.id} == set(o.connects)
                    for w in level.walls for o in w.openings
                )
            ):
                cut_door(foyer.id, living.id)

        # Food goes from the kitchen to the table: the kitchen opens onto the
        # dining room whenever the two share a wall to hang the opening on.
        kitchen = next((r for r in level.rooms if r.type is RoomType.KITCHEN), None)
        dining = next((r for r in level.rooms if r.type is RoomType.DINING), None)
        if (
            kitchen is not None and dining is not None
            and dining.id in adjacency.get(kitchen.id, set())
            and not any(
                o.kind.is_door and o.connects and {kitchen.id, dining.id} == set(o.connects)
                for w in level.walls for o in w.openings
            )
        ):
            cut_door(kitchen.id, dining.id)

        # The main entrance goes on the exterior wall of the root room, facing
        # the road wherever the site tells us where the road is. An upper
        # floor has no front door; you arrive by the stair.
        if level.index == 0:
            self._place_main_door(plan, level, rooms[root])

    @staticmethod
    def _entry_room(level: Level, plan: FloorPlan | None = None) -> Room:
        """Where a person arrives on this floor: the door tree grows from here.

        Ground: the foyer, else the living room - but a room with a wall on the
        road, when the foyer has none: the front door faces the street. Upstairs:
        the staircase, else the landing. Rooting the upper floor at its largest
        room - the master bedroom - is how every other bedroom came to be
        entered through it.
        """
        order = (
            (RoomType.STAIRCASE, RoomType.LOBBY, RoomType.CORRIDOR)
            if level.index > 0 else
            (RoomType.FOYER, RoomType.LOBBY, RoomType.VERANDAH, RoomType.LIVING)
        )
        found = [r for kind in order for r in level.rooms if r.type is kind][:6]
        if level.index == 0 and plan is not None and found and plan.site.road_directions:
            road = plan.site.road_directions[0]

            def faces_road(room: Room) -> float:
                best = 360.0
                for w in level.walls:
                    if w.kind is WallKind.EXTERIOR and room.id in w.rooms:
                        d = _wall_direction(plan, w)
                        best = min(best, abs(((d.bearing - road.bearing) + 180) % 360 - 180))
                return best

            first = found[0]
            if faces_road(first) > 50.0:
                # Another room that receives people, if one has a wall on the road.
                more = [r for kind in (RoomType.CORRIDOR, RoomType.FAMILY, RoomType.DRAWING, RoomType.DINING,
                                       RoomType.STAIRCASE) for r in level.rooms if r.type is kind]
                better = [r for r in found + more if faces_road(r) <= 50.0]
                if better:
                    return better[0]
        if found:
            return found[0]
        return max(level.rooms, key=lambda r: r.area)

    def _wants_attached(self, room: Room) -> bool:
        return any(
            req.type is room.type and req.attached_bathroom
            for req in self.requirements
        )

    def _place_main_door(self, plan: FloorPlan, level: Level, entry_room: Room) -> None:
        road = plan.site.road_directions[0] if plan.site.road_directions else Direction.N
        candidates = [
            w for w in level.walls
            if entry_room.id in w.rooms and w.kind is WallKind.EXTERIOR
        ]
        if not candidates:
            candidates = [w for w in level.walls if w.kind is WallKind.EXTERIOR]
        if not candidates:
            return

        def alignment(wall: Wall) -> float:
            direction = _wall_direction(plan, wall)
            delta = abs(((direction.bearing - road.bearing) + 180) % 360 - 180)
            return delta

        wall = min(candidates, key=alignment)
        wall.openings.append(
            Opening(
                kind=OpeningKind.MAIN_DOOR,
                wall_id=wall.id,
                position=0.5,
                width=1.05,
                height=2.1,
                sill_height=0.0,
                connects=(entry_room.id, ""),
            )
        )

    # ------------------------------------------------------------- misc ----

    def _signature(self, plan: FloorPlan) -> tuple:
        """Coarse fingerprint used to reject exactly-duplicate schemes."""
        return tuple(
            sorted(
                (r.type.value, round(r.area, 0), round(r.centre.x, 0), round(r.centre.y, 0))
                for r in plan.all_rooms
            )
        )

    def _select_diverse(
        self,
        scored: list[tuple[float, dict[str, float], FloorPlan]],
        count: int,
    ) -> list[tuple[float, dict[str, float], FloorPlan]]:
        """Greedy fitness/diversity trade-off, best first.

        Taking the top N by score alone reliably returns N variations of the same
        scheme, because a converged population clusters. That wastes the critic
        committee: reviewing three copies of one design yields no more
        information than reviewing one. Each subsequent pick is therefore
        penalised by its similarity to what has already been chosen, so the
        architect is offered genuinely different options to choose between.
        """
        if not scored:
            return []
        pool = sorted(scored, key=lambda item: item[0], reverse=True)
        chosen: list[tuple[float, dict[str, float], FloorPlan]] = [pool.pop(0)]

        while pool and len(chosen) < count:
            best_index = 0
            best_value = -math.inf
            sims = [max(self._similarity(plan, picked[2]) for picked in chosen) for _s, _b, plan in pool]
            # A near-copy of a scheme already chosen - the same plan with a store
            # and a bath swapped - tells the client nothing new: it is offered
            # only when nothing different is left.
            distinct = any(x < 0.75 for x in sims)
            for index, (score, _breakdown, plan) in enumerate(pool):
                similarity = sims[index]
                if distinct and similarity >= 0.75:
                    continue
                value = score - 0.45 * similarity - 1.5 * max(0.0, similarity - 0.5)
                if value > best_value:
                    best_value = value
                    best_index = index
            chosen.append(pool.pop(best_index))
        return chosen

    @staticmethod
    def _similarity(a: FloorPlan, b: FloorPlan) -> float:
        """Fraction of rooms that occupy the same place at the same size."""
        def fingerprint(plan: FloorPlan) -> set[tuple]:
            return {
                (r.type.value, round(r.area / 3), round(r.centre.x / 1.5), round(r.centre.y / 1.5))
                for r in plan.all_rooms
            }

        fa, fb = fingerprint(a), fingerprint(b)
        if not fa or not fb:
            return 0.0
        return len(fa & fb) / max(len(fa), len(fb))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shared_length(a: Room, b: Room) -> float:
    """Length of wall two rooms share, 0 when they do not touch."""
    from aip.domain.geometry import shared_edge

    edge = shared_edge(a.polygon, b.polygon)
    return edge[0].distance_to(edge[1]) if edge is not None else 0.0


def _overlap_fraction(box: BoundingBox, anchor: BoundingBox) -> float:
    """How much of `anchor` the box covers, 0 to 1."""
    dx = min(box.max_x, anchor.max_x) - max(box.min_x, anchor.min_x)
    dy = min(box.max_y, anchor.max_y) - max(box.min_y, anchor.min_y)
    if dx <= 0 or dy <= 0 or anchor.area <= 0:
        return 0.0
    return min(1.0, (dx * dy) / anchor.area)


def _external_faces(box: BoundingBox, envelope: BoundingBox, tol: float = 0.02) -> int:
    """How many of a cell's four faces sit on the building envelope.

    Zero means a landlocked room with no possible window; one permits
    single-sided daylight; two or more permit genuine cross ventilation. This
    single integer is the surrogate's proxy for the entire daylight and
    ventilation metric suite.
    """
    faces = 0
    faces += abs(box.min_x - envelope.min_x) < tol
    faces += abs(box.max_x - envelope.max_x) < tol
    faces += abs(box.min_y - envelope.min_y) < tol
    faces += abs(box.max_y - envelope.max_y) < tol
    return faces


#: Shared wall needed to hang a door: leaf plus frame plus a little tolerance.
#: Two rooms that share less than this touch, but cannot be connected, and for
#: circulation purposes that is the same as not touching at all.
DOOR_WALL = 1.0


def _rects_touch(
    a: BoundingBox, b: BoundingBox, tol: float = 0.02, min_overlap: float = 0.0
) -> bool:
    """True when two cells share a boundary segment longer than `min_overlap`.

    The default counts any contact at all, which is right for "do these rooms
    neighbour each other". For "can a door join them" pass `DOOR_WALL`: a
    two-centimetre sliver of shared boundary satisfied the old test, the
    search scored the room as reachable, and the door placer then found no
    wall it could cut.
    """
    need = max(tol, min_overlap)
    vertical = (abs(a.max_x - b.min_x) < tol or abs(a.min_x - b.max_x) < tol) and (
        min(a.max_y, b.max_y) - max(a.min_y, b.min_y) > need
    )
    horizontal = (abs(a.max_y - b.min_y) < tol or abs(a.min_y - b.max_y) < tol) and (
        min(a.max_x, b.max_x) - max(a.min_x, b.min_x) > need
    )
    return vertical or horizontal


def _edge_key(a: Vec2, b: Vec2, precision: int = 3) -> tuple:
    pa = (round(a.x, precision), round(a.y, precision))
    pb = (round(b.x, precision), round(b.y, precision))
    return (pa, pb) if pa <= pb else (pb, pa)


def _is_on_envelope(a: Vec2, b: Vec2, envelope: BoundingBox, tol: float = 0.02) -> bool:
    on_x = (abs(a.x - envelope.min_x) < tol and abs(b.x - envelope.min_x) < tol) or (
        abs(a.x - envelope.max_x) < tol and abs(b.x - envelope.max_x) < tol
    )
    on_y = (abs(a.y - envelope.min_y) < tol and abs(b.y - envelope.min_y) < tol) or (
        abs(a.y - envelope.max_y) < tol and abs(b.y - envelope.max_y) < tol
    )
    return on_x or on_y


def _wall_direction(plan: FloorPlan, wall: Wall) -> Direction:
    from aip.domain.geometry import bearing_to_direction

    normal = wall.outward_normal(plan.centre)
    bearing = math.degrees(math.atan2(normal.x, normal.y)) + plan.site.north_angle
    return bearing_to_direction(bearing)


#: Faces the low afternoon sun reaches under a chajja: their windows also get fins.
HOT_FACES = {Direction.W, Direction.WSW, Direction.WNW, Direction.SW}


def _pick_cross_ventilating(plan: FloorPlan, walls: list[Wall]) -> list[Wall]:
    """Choose up to two walls facing meaningfully different directions."""
    if not walls:
        return []
    chosen = [walls[0]]
    first = _wall_direction(plan, walls[0])
    for wall in walls[1:]:
        direction = _wall_direction(plan, wall)
        delta = abs(((direction.bearing - first.bearing) + 180) % 360 - 180)
        if delta >= 80:
            chosen.append(wall)
            break
    return chosen


def _wall_between(level: Level, room_a: str, room_b: str) -> Wall | None:
    """Find the wall a door between two rooms should be cut into.

    The exact-match case covers rooms whose partition edges coincide end to end.
    It is not the common case: in a slicing partition, a large room routinely
    abuts two smaller ones, so its single long wall meets two short walls at a
    T-junction and no wall lists both rooms. Requiring an exact match there
    silently produced unreachable rooms - every generated scheme failed the
    circulation critic for a reason that was an artefact of wall bookkeeping
    rather than a real design fault.

    The fallback therefore locates any wall belonging to either room that lies
    along their genuinely shared boundary, and records the adjacency on it.
    """
    for wall in level.walls:
        if room_a in wall.rooms and room_b in wall.rooms:
            return wall

    rooms = {r.id: r for r in level.rooms}
    a, b = rooms.get(room_a), rooms.get(room_b)
    if a is None or b is None:
        return None
    edge = shared_edge(a.polygon, b.polygon)
    if edge is None:
        return None

    start, end = edge
    midpoint = (start + end) * 0.5
    overlap_length = start.distance_to(end)

    best: tuple[float, Wall] | None = None
    for wall in level.walls:
        if room_a not in wall.rooms and room_b not in wall.rooms:
            continue
        # The wall must lie on the shared boundary, not merely belong to the room.
        if distance_point_to_segment(midpoint, wall.start, wall.end) > 0.08:
            continue
        # Prefer the wall whose own extent best covers the shared segment.
        coverage = min(wall.length, overlap_length) / max(wall.length, overlap_length, 1e-6)
        if best is None or coverage > best[0]:
            best = (coverage, wall)

    if best is None:
        return None

    wall = best[1]
    for room_id in (room_a, room_b):
        if room_id not in wall.rooms:
            wall.rooms.append(room_id)
    # A wall that separates two rooms is a partition, not a stub.
    if wall.kind is WallKind.PARTITION:
        wall.kind = WallKind.INTERIOR
    return wall
