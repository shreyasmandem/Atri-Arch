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

import math
import random
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field

from aip.core.logging import get_logger, log_event
from aip.domain.brief import ClientBrief, RoomRequirement
from aip.domain.geometry import (
    BoundingBox,
    Direction,
    Vec2,
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

logger = get_logger("aip.layout")

MIN_ROOM_DIMENSION = 1.5          # m - below this nothing is buildable
WALL_THICKNESS_EXTERIOR = 0.23
WALL_THICKNESS_INTERIOR = 0.115


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
    """A cut. `vertical` splits left/right; otherwise bottom/top."""

    vertical: bool
    ratio: float
    left: Node
    right: Node

    def leaves(self) -> Iterator[Leaf]:
        yield from self.left.leaves()
        yield from self.right.leaves()

    def depth(self) -> int:
        return 1 + max(self.left.depth(), self.right.depth())

    def copy(self) -> Split:
        return Split(self.vertical, self.ratio, self.left.copy(), self.right.copy())


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
    ratio = min(0.92, max(0.08, node.ratio))
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


def build_balanced_tree(slots: Sequence[int], rng: random.Random, areas: Sequence[float]) -> Node:
    """Area-proportional recursive bisection.

    Splitting each group so the two halves carry roughly equal *area* - rather
    than an equal *count* - gives the optimiser a far better starting point,
    because room sizes in a real brief differ by an order of magnitude.
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
    ratio = left_area / (left_area + right_area)

    return Split(
        vertical=rng.random() < 0.5,
        ratio=min(0.88, max(0.12, ratio)),
        left=build_balanced_tree(left_slots, rng, areas),
        right=build_balanced_tree(right_slots, rng, areas),
    )


def build_zoned_tree(
    slots: Sequence[int],
    requirements: Sequence[RoomRequirement],
    areas: Sequence[float],
    rng: random.Random,
    *,
    road_along_y: bool,
    road_at_high_end: bool,
    bands: int = 3,
    brief_kind=None,
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
        req = requirements[slot]
        return req.needs_daylight and not req.type.is_circulation

    # The residential template, stated by role rather than discovered by
    # packing. This is how a practice lays out a plot: arrival and the
    # public rooms at the frontage; the dining-kitchen-utility group behind
    # them; a passage across the seam; the bedrooms beyond it, each with a
    # bathroom beside it. Packing rooms into bands by area alone put the
    # dining room in front of the living room and the kitchen behind the
    # bedrooms, because area does not know what a room is for.
    front_types = {RoomType.FOYER, RoomType.VERANDAH, RoomType.LIVING,
                   RoomType.DRAWING, RoomType.PUJA, RoomType.HOME_OFFICE}
    service_types = {RoomType.DINING, RoomType.KITCHEN, RoomType.UTILITY, RoomType.PANTRY,
                     RoomType.STORE, RoomType.LAUNDRY, RoomType.FAMILY}
    wet_types = {RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER}
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
    other = [s for s in slots if s not in front + service + wet + private + passage]

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
    if private_bands:
        if attached:
            private_bands[0] += attached
        for index, w in enumerate(common):
            private_bands[index % len(private_bands)].append(w)
    else:
        service += common + attached

    groups: list[list[int]] = []
    if front or other:
        groups.append(front + other)
    if service:
        groups.append(service)
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
    if passages:
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
        groups.insert(seam, passages)

    # Within a band, cut along the frontage; between bands, cut across it.
    # Band order runs from the road inward, so the first group must land on the
    # road side of the envelope.
    def band_tree(group: list[int]) -> Node:
        if len(group) == 1:
            return Leaf(group[0])
        order = list(group)
        # Divide the band by area along its length.
        gtotal = sum(areas[g] for g in order) or 1.0
        cut_index = 1
        acc = 0.0
        for i, g in enumerate(order):
            acc += areas[g]
            if acc >= gtotal / 2:
                cut_index = max(1, min(len(order) - 1, i + 1))
                break
        left, right = order[:cut_index], order[cut_index:]
        la = sum(areas[g] for g in left) or 1.0
        ra = sum(areas[g] for g in right) or 1.0
        return Split(
            vertical=road_along_y,     # cuts along the frontage
            ratio=min(0.88, max(0.12, la / (la + ra))),
            left=band_tree(left),
            right=band_tree(right),
        )

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

    return stack(groups)


# ---------------------------------------------------------------------------
# Genome
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Genome:
    """A candidate layout: a tree plus the slot-to-requirement assignment."""

    tree: Node
    assignment: list[int]         # assignment[slot] -> requirement index
    fitness: float = -1.0
    breakdown: dict[str, float] = field(default_factory=dict)

    def copy(self) -> Genome:
        return Genome(self.tree.copy(), list(self.assignment))


def mutate(genome: Genome, rng: random.Random, strength: float = 1.0) -> Genome:
    """Apply one random structural or parametric mutation."""
    child = genome.copy()
    splits = _collect_splits(child.tree)

    choice = rng.random()
    if choice < 0.34 and len(child.assignment) > 1:
        # Swap which rooms occupy two slots - changes orientation and adjacency
        # without disturbing the geometry, so it explores the assignment space.
        i, j = rng.sample(range(len(child.assignment)), 2)
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
    child = Genome(a.tree.copy(), list(b.assignment))
    if rng.random() < 0.5:
        splits_a = _collect_splits(child.tree)
        splits_b = _collect_splits(b.tree)
        for node_a, node_b in zip(splits_a, splits_b, strict=False):
            if rng.random() < 0.4:
                node_a.ratio = node_b.ratio
                node_a.vertical = node_b.vertical
    return child


def _collect_splits(node: Node) -> list[Split]:
    out: list[Split] = []
    stack: list[Node] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Split):
            out.append(current)
            stack.append(current.left)
            stack.append(current.right)
    return out


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GeneratorConfig:
    population: int = 48
    generations: int = 60
    elite: int = 6
    tournament: int = 3
    mutation_rate: float = 0.75
    seed: int | None = None
    corridor_share: float = 0.10
    max_stagnation: int = 18


#: Rooms that can receive the main entrance, in order of preference.
_ENTRY_ROOMS = (RoomType.FOYER, RoomType.LOBBY, RoomType.VERANDAH)


class LayoutGenerator:
    """Produces buildable, optimised floorplans from a client brief."""

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
        self.requirements = self._prepare_requirements()

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
        """
        fitness_fn = fitness_fn or self._default_fitness
        scored: list[tuple[float, dict[str, float], FloorPlan]] = []
        signatures: set[tuple] = set()

        runs = max(3, count + 1)
        for run in range(runs):
            self.rng = random.Random(
                None if self.config.seed is None else self.config.seed + run * 7919
            )
            for genome in self._evolve(elite_out=max(3, self.config.elite // 2)):
                plan = self._to_plan(genome)
                signature = self._signature(plan)
                if signature in signatures:
                    continue
                signatures.add(signature)
                exact, breakdown = fitness_fn(plan)
                scored.append((exact, breakdown, plan))

        selected = self._select_diverse(scored, count)
        plans: list[FloorPlan] = []
        for index, (exact, breakdown, plan) in enumerate(selected):
            plan.metadata["fitness"] = round(exact, 4)
            plan.metadata["fitness_breakdown"] = breakdown
            plan.name = f"Scheme {chr(ord('A') + index)}"
            plans.append(plan)

        log_event(
            logger, "layout.generated",
            requested=count, evaluated=len(scored), produced=len(plans),
            best=max((p.metadata.get("fitness", 0.0) for p in plans), default=0.0),
        )
        return plans

    # -------------------------------------------------------- preparation --

    def _prepare_requirements(self) -> list[RoomRequirement]:
        """Expand the brief and insert the circulation the client never asks for."""
        reqs = self.brief.expanded_requirements()
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
        if self.brief.levels > 1 and not any(r.type is RoomType.STAIRCASE for r in reqs):
            reqs.append(
                RoomRequirement(
                    type=RoomType.STAIRCASE,
                    preferred_area=9.0,
                    needs_external_wall=False,
                    needs_daylight=False,
                    priority=1.4,
                )
            )
        return reqs

    def _buildable_envelope(self) -> BoundingBox:
        """The rectangle the building may occupy, after setbacks and coverage."""
        site = self.brief.site
        if site.boundary:
            inner = shrink_polygon(
                site.boundary,
                min(site.setback_front, site.setback_rear, site.setback_left, site.setback_right),
            )
            if inner:
                xs = [p.x for p in inner]
                ys = [p.y for p in inner]
                box = BoundingBox(min(xs), min(ys), max(xs), max(ys))
            else:
                box = site.bbox
        else:
            side = math.sqrt(max(self.brief.target_built_area, 40.0))
            box = BoundingBox(0.0, 0.0, side * 1.25, side / 1.25 * 1.0)

        # Respect ground coverage by shrinking the footprint proportionally.
        max_footprint = site.max_footprint if site.plot_area else box.area
        per_level_target = self.brief.target_built_area / max(1, self.brief.levels)
        target = min(box.area, max_footprint if max_footprint > 0 else box.area, per_level_target * 1.06)
        if target > 0 and box.area > target:
            scale = math.sqrt(target / box.area)
            new_w = box.width * scale
            new_h = box.height * scale
            centre = box.centre
            box = BoundingBox(
                centre.x - new_w / 2, centre.y - new_h / 2,
                centre.x + new_w / 2, centre.y + new_h / 2,
            )
        return box

    def _level_assignment(self) -> list[list[int]]:
        """Distribute requirement indices across levels.

        Public and service functions stay on the entrance level; bedrooms move
        up when there is an upper floor. Anything the brief pinned to a level is
        honoured exactly.
        """
        levels = self.brief.levels
        buckets: list[list[int]] = [[] for _ in range(levels)]
        if levels == 1:
            buckets[0] = list(range(len(self.requirements)))
            return buckets

        ground_types = {
            RoomType.LIVING, RoomType.DRAWING, RoomType.DINING, RoomType.KITCHEN,
            RoomType.FOYER, RoomType.LOBBY, RoomType.PUJA, RoomType.UTILITY,
            RoomType.STORE, RoomType.GARAGE, RoomType.POWDER, RoomType.SERVANT,
            RoomType.VERANDAH, RoomType.CORRIDOR, RoomType.STAIRCASE,
        }
        upper_index = 1
        for idx, req in enumerate(self.requirements):
            if req.level is not None and 0 <= req.level < levels:
                buckets[req.level].append(idx)
            elif req.type in ground_types:
                buckets[0].append(idx)
            else:
                buckets[upper_index].append(idx)
                upper_index = 1 + (upper_index % max(1, levels - 1))

        # Every level needs vertical circulation and at least one room.
        for i, bucket in enumerate(buckets):
            if not bucket:
                donor = max(buckets, key=len)
                if len(donor) > 1:
                    bucket.append(donor.pop())
            if i > 0 and not any(self.requirements[j].type is RoomType.STAIRCASE for j in bucket):
                self.requirements.append(
                    RoomRequirement(
                        type=RoomType.STAIRCASE, preferred_area=9.0,
                        needs_external_wall=False, needs_daylight=False, priority=1.4,
                    )
                )
                bucket.append(len(self.requirements) - 1)
        return buckets

    # ---------------------------------------------------------- evolution --

    def _evolve(self, elite_out: int = 3) -> list[Genome]:
        """Evolve against the surrogate and return the best `elite_out` genomes."""
        cfg = self.config
        slots = list(range(len(self.requirements)))
        areas = [r.target_area for r in self.requirements]
        envelope = self._buildable_envelope()
        level_buckets = self._level_assignment()

        population: list[Genome] = []

        # Half the population starts from the front-to-back organisation a real
        # plan has; the other half is random, for diversity. A wholly random
        # start relies on evolution to rediscover the organising idea of a
        # house in thirty generations, and it mostly does not.
        road = self.brief.site.road_directions[0] if self.brief.site.road_directions else None
        if road is not None:
            bearing = (road.bearing + self.brief.site.north_angle) % 360
            # A north or south road means depth runs along Y; east or west, X.
            depth_along_y = bearing < 45 or bearing >= 315 or 135 <= bearing < 225
            # North sits at max_y and east at max_x: the high end of their axis.
            road_at_high_end = bearing < 45 or bearing >= 315 or 45 <= bearing < 135
            seeded = cfg.population // 2
            for k in range(seeded):
                bands = 3 if k % 3 else 4
                tree = build_zoned_tree(
                    slots, self.requirements, areas, self.rng,
                    road_along_y=depth_along_y, road_at_high_end=road_at_high_end,
                    bands=bands, brief_kind=self.brief.kind,
                )
                # The zoned tree already places the right requirement in each
                # slot, so the assignment is the identity.
                population.append(Genome(tree, slots[:]))

        while len(population) < cfg.population:
            order = slots[:]
            self.rng.shuffle(order)
            tree = build_balanced_tree(order, self.rng, areas)
            assignment = slots[:]
            self.rng.shuffle(assignment)
            population.append(Genome(tree, assignment))

        best_score = -1.0
        stagnant = 0

        for generation in range(cfg.generations):
            for genome in population:
                if genome.fitness < 0:
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
                child.fitness = -1.0
                children.append(child)
            population = children

        for genome in population:
            if genome.fitness < 0:
                genome.fitness = self._surrogate_fitness(genome, envelope, level_buckets)
        population.sort(key=lambda g: g.fitness, reverse=True)
        return population[:elite_out]

    # --------------------------------------------------------- surrogate ---

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
        """
        boxes = realise(genome.tree, envelope)
        if not boxes:
            return 0.0

        slot_to_level: dict[int, int] = {}
        for level_index, requirement_indices in enumerate(level_buckets):
            wanted = set(requirement_indices)
            for slot in range(len(genome.assignment)):
                if genome.assignment[slot] in wanted:
                    slot_to_level[slot] = level_index

        from aip.domain.brief import NBC_MIN_WIDTH
        from aip.engines.architecture.programme import depth_fit

        area_terms: list[float] = []
        shape_terms: list[float] = []
        light_terms: list[float] = []
        orientation_terms: list[float] = []
        depth_terms: list[float] = []
        penalty = 0.0

        centre = envelope.centre
        north = self.brief.site.north_angle
        vastu_weight = self.brief.tradition_weight if self.brief.vastu.is_constraining else 0.0

        # The road-to-rear axis. Depth 0 is the frontage, 1 the back boundary,
        # measured along whichever axis faces the road.
        road = self.brief.site.road_directions[0] if self.brief.site.road_directions else None

        def depth_of(box: BoundingBox) -> float:
            if road is None:
                return 0.5
            c = box.centre
            bearing = (road.bearing + north) % 360
            if 45 <= bearing < 135:      # road to the east
                return (envelope.max_x - c.x) / max(envelope.width, 1e-6)
            if 225 <= bearing < 315:     # road to the west
                return (c.x - envelope.min_x) / max(envelope.width, 1e-6)
            if bearing >= 315 or bearing < 45:   # road to the north (+Y)
                return (envelope.max_y - c.y) / max(envelope.height, 1e-6)
            return (c.y - envelope.min_y) / max(envelope.height, 1e-6)

        placed: list[tuple[int, BoundingBox]] = []
        for slot, box in boxes.items():
            req = self.requirements[genome.assignment[slot]]
            placed.append((genome.assignment[slot], box))

            # Hard geometric viability.
            short = min(box.width, box.height)
            if short < MIN_ROOM_DIMENSION:
                penalty += 0.14 * (MIN_ROOM_DIMENSION - short) / MIN_ROOM_DIMENSION

            # Statutory minimum width for this room type, not merely a generic
            # floor. A dining room 1.7 m across clears MIN_ROOM_DIMENSION and is
            # still a corridor with a table in it.
            floor = NBC_MIN_WIDTH.get(req.type)
            if floor is not None and short < floor:
                penalty += 0.20 * (floor - short) / floor

            # Where the room sits between road and rear.
            depth_terms.append(depth_fit(req.type, depth_of(box)))

            # The room that receives the front door must actually reach the
            # frontage. A northerly centre is not enough: a foyer with the puja
            # packed in front of it has no road-facing wall, and the entrance
            # ends up on the side of the house.
            if (
                req.type in _ENTRY_ROOMS and road is not None
                and not self._touches_road_edge(box, envelope, road)
            ):
                penalty += 0.18

            # The shape term below saturates at zero around 3:1, which makes an
            # 8:1 room cost exactly as much as a 3:1 one - so once a room is bad
            # the search has no reason to stop making it worse. This penalty has
            # no ceiling, which is what actually rules out habitable rooms shaped
            # like corridors.
            if req.type.is_habitable and box.aspect_ratio > 2.4:
                penalty += 0.09 * (box.aspect_ratio - 2.4)

            # Area fidelity: undersize is a defect, oversize merely costs money.
            ratio = box.area / max(req.target_area, 0.5)
            deviation = abs(math.log(max(ratio, 0.12)))
            area_terms.append(max(0.0, 1.0 - deviation * (1.5 if ratio < 1 else 0.7)))

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
            if req.type.is_circulation and ratio > 1.25:
                penalty += 0.22 * (ratio - 1.25)

            # Proportion.
            aspect = box.aspect_ratio
            shape_terms.append(1.0 if aspect <= 1.6 else max(0.0, 1.0 - (aspect - 1.6) / 1.5))

            # External-wall access, and how many faces are external. Two external
            # faces is what makes cross ventilation possible at all.
            faces = _external_faces(box, envelope)
            if req.needs_daylight or req.needs_external_wall:
                light_terms.append(0.0 if faces == 0 else (0.72 if faces == 1 else 1.0))
                # Averaged into light_terms, one landlocked bedroom among ten lit
                # rooms costs almost nothing. It is a statutory failure with no
                # local repair - you cannot add a window to a wall that is not
                # there - so it is priced as one.
                if faces == 0 and req.needs_daylight:
                    penalty += 0.30
            elif faces == 0:
                light_terms.append(1.0)          # interior room correctly interior

            # Orientation preference, from the brief and from Vastu.
            preferred = req.preferred_direction or self._vastu_direction(req.type)
            if preferred is not None:
                actual = direction_of(box.centre, centre, north)
                delta = abs(((actual.bearing - preferred.bearing) + 180) % 360 - 180)
                alignment = max(0.0, 1.0 - delta / 90.0)
                weight = 1.0 if req.preferred_direction else max(0.25, vastu_weight)
                orientation_terms.append(alignment * weight + (1 - weight))

        # Adjacency: required pairs should touch, forbidden pairs should not.
        adjacency_score = self._surrogate_adjacency(placed, slot_to_level)

        # Walkability. A dead-end room that touches no through-room can only
        # be entered through another dead end - a bedroom through a bedroom, a
        # kitchen through the master. That is the failure a client sees before
        # any other, so each such room is a penalty on its own, not a term
        # averaged away.
        penalty += self._surrogate_walkability(placed, slot_to_level)

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
        return max(0.0, min(1.0, score - penalty))

    def _surrogate_walkability(
        self, placed: list[tuple[int, BoundingBox]], slot_to_level: dict[int, int]
    ) -> float:
        from aip.engines.architecture.programme import is_through, may_enter

        # The same question the door placer will ask, so the search produces
        # layouts the placer can connect legally. Two rules kept in two places
        # drift apart, and then the search converges on plans whose doors the
        # placer has to cut through a bedroom.
        penalty = 0.0
        for req_index, box in placed:
            req = self.requirements[req_index]
            if is_through(req.type):
                continue
            reachable = False
            for other_index, other_box in placed:
                if other_index == req_index:
                    continue
                if slot_to_level.get(req_index) != slot_to_level.get(other_index):
                    continue
                if not _rects_touch(box, other_box, min_overlap=DOOR_WALL):
                    continue
                if may_enter(req.type, self.requirements[other_index].type):
                    reachable = True
                    break
            if not reachable:
                # A bedroom cut off is worse than a store cut off.
                penalty += 0.30 if req.type.is_habitable else 0.14

        # The through-rooms must form ONE connected chain. Each touching some
        # other through-room is not enough: foyer-living on one side of the
        # plot and dining-corridor on the other both pass that test, and the
        # only bridge between the two islands runs through a bedroom. So this
        # counts islands, and every island beyond the first is a bedroom
        # somebody has to walk through.
        through = [(i, b) for i, b in placed if is_through(self.requirements[i].type)]
        if len(through) > 1:
            parent = {i: i for i, _ in through}

            def find(x: int) -> int:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for a_idx, (i, box_i) in enumerate(through):
                for j, box_j in through[a_idx + 1:]:
                    if slot_to_level.get(i) != slot_to_level.get(j):
                        continue
                    if _rects_touch(box_i, box_j, min_overlap=DOOR_WALL):
                        parent[find(i)] = find(j)
            islands = len({find(i) for i, _ in through})
            penalty += 0.30 * (islands - 1)
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

    def _surrogate_adjacency(
        self, placed: list[tuple[int, BoundingBox]], slot_to_level: dict[int, int]
    ) -> float:
        """Score the programme against raw rectangles.

        Deliberately the *same* scoring the exact evaluation applies to finished
        walls, so the cheap search and the expensive ranking agree about what a
        good plan is. Two different notions of adjacency here would mean the
        search converges on plans the final ranking then throws away.

        Counting each relationship equally - which is what the flattened
        `must_be_adjacent_to` lists invite - treats kitchen-to-dining as no more
        important than study-to-bedroom. The weighted programme is what makes
        the search spend its effort on the pairs that matter.
        """
        from aip.engines.architecture.programme import score_pairs

        touching: set[tuple[RoomType, RoomType]] = set()
        for i, (req_index, box) in enumerate(placed):
            a = self.requirements[req_index].type
            for other_index, other_box in placed[i + 1:]:
                if slot_to_level.get(req_index) != slot_to_level.get(other_index):
                    continue
                if _rects_touch(box, other_box, min_overlap=DOOR_WALL):
                    b = self.requirements[other_index].type
                    touching.add((a, b))
                    touching.add((b, a))

        present = {self.requirements[i].type for i, _ in placed}
        score, _honoured, _broken = score_pairs(touching, present, self.brief.kind)
        return score

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

        if self.brief.vastu.is_constraining:
            try:
                from aip.engines.vastu.engine import quick_vastu_score

                vastu = quick_vastu_score(plan, self.brief.tradition_weight)
                breakdown["vastu"] = vastu
                weight = 0.10 + 0.20 * self.brief.tradition_weight
                score = score * (1 - weight) + vastu * weight
            except Exception:  # pragma: no cover - Vastu is optional in fitness
                pass

        return round(max(0.0, min(1.0, score)), 5), {k: round(v, 4) for k, v in breakdown.items()}

    def _layout_sense(self, plan: FloorPlan) -> float:
        """Does the plan work as a building, not just as a set of rooms?"""
        from aip.engines.architecture.programme import evaluate

        return evaluate(plan, self.brief).score

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
        """Convert a genome into a fully-detailed FloorPlan."""
        envelope = self._buildable_envelope()
        level_buckets = self._level_assignment()
        site = self.brief.site

        levels: list[Level] = []
        for level_index, requirement_indices in enumerate(level_buckets):
            if not requirement_indices:
                continue
            sub_slots = [s for s in range(len(genome.assignment)) if genome.assignment[s] in requirement_indices]
            if not sub_slots:
                sub_slots = list(range(min(len(requirement_indices), len(genome.assignment))))

            areas = [self.requirements[genome.assignment[s]].target_area for s in range(len(genome.assignment))]
            if level_index == 0:
                boxes = realise(genome.tree, envelope)
                boxes = {s: b for s, b in boxes.items() if s in set(sub_slots)}
                if not boxes:
                    boxes = realise(build_balanced_tree(sub_slots, self.rng, areas), envelope)
            else:
                # Upper floors reuse the footprint but get their own partition,
                # which keeps the structural envelope stackable while letting the
                # upper programme differ.
                tree = build_balanced_tree(sub_slots, random.Random(level_index * 104729), areas)
                boxes = realise(tree, envelope)

            rooms: list[Room] = []
            for slot, box in sorted(boxes.items()):
                req = self.requirements[genome.assignment[slot]]
                if box.width < MIN_ROOM_DIMENSION or box.height < MIN_ROOM_DIMENSION:
                    # Degenerate cell - the optimiser is penalised for this via
                    # spatial quality rather than the room being silently dropped.
                    pass
                polygon = rectangle(Vec2(box.min_x, box.min_y), box.width, box.height)
                room = Room(
                    name=req.type.label,
                    type=req.type,
                    polygon=polygon,
                    level=level_index,
                    ceiling_height=3.0,
                    metadata={"target_area": req.target_area, "slot": slot},
                )
                rooms.append(room)

            walls = self._build_walls(rooms, envelope, level_index)
            staircases = self._build_stairs(rooms, level_index)
            levels.append(
                Level(
                    index=level_index,
                    elevation=level_index * 3.15,
                    floor_to_floor=3.15,
                    rooms=rooms,
                    walls=walls,
                    staircases=staircases,
                )
            )

        plan = FloorPlan(
            name="Generated Scheme",
            site=site,
            levels=levels,
            structural_system=StructuralSystem.RCC_FRAME,
            style=self.brief.style.primary.value,
        )
        plan.column_grid = self._build_column_grid(envelope)
        self._place_openings(plan, envelope)
        return plan

    # ------------------------------------------------------------- walls ---

    def _build_walls(self, rooms: list[Room], envelope: BoundingBox, level_index: int) -> list[Wall]:
        """Derive the wall set from room rectangles, merging shared boundaries."""
        walls: list[Wall] = []
        seen: dict[tuple, Wall] = {}

        for room in rooms:
            box = room.bbox
            edges = [
                (Vec2(box.min_x, box.min_y), Vec2(box.max_x, box.min_y)),
                (Vec2(box.max_x, box.min_y), Vec2(box.max_x, box.max_y)),
                (Vec2(box.max_x, box.max_y), Vec2(box.min_x, box.max_y)),
                (Vec2(box.min_x, box.max_y), Vec2(box.min_x, box.min_y)),
            ]
            for start, end in edges:
                key = _edge_key(start, end)
                existing = seen.get(key)
                if existing is not None:
                    # Two rooms share this edge: it is an internal partition.
                    if room.id not in existing.rooms:
                        existing.rooms.append(room.id)
                    existing.kind = WallKind.INTERIOR
                    existing.thickness = WALL_THICKNESS_INTERIOR
                    continue

                on_envelope = _is_on_envelope(start, end, envelope)
                wall = Wall(
                    start=start,
                    end=end,
                    thickness=WALL_THICKNESS_EXTERIOR if on_envelope else WALL_THICKNESS_INTERIOR,
                    height=3.0,
                    kind=WallKind.EXTERIOR if on_envelope else WallKind.INTERIOR,
                    rooms=[room.id],
                )
                seen[key] = wall
                walls.append(wall)

        # A wall bounding exactly one room and not on the envelope is a stub -
        # it means the neighbouring cell was degenerate. Treat it as a partition.
        for wall in walls:
            if wall.kind is WallKind.INTERIOR and len(wall.rooms) == 1:
                wall.kind = WallKind.PARTITION
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

    def _place_openings(self, plan: FloorPlan, envelope: BoundingBox) -> None:
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
                if not exterior:
                    continue

                # Two statutory requirements govern the aperture:
                #   light  - glazed area >= 1/10 of the floor area
                #   air    - *openable* area >= 1/6 of the floor area
                # Only a fraction of a window actually opens, so the ventilation
                # requirement has to be divided by that fraction before sizing.
                # Skipping that division is the classic under-glazing error.
                kind = OpeningKind.VENTILATOR if room.type.is_wet else OpeningKind.WINDOW
                openable_fraction = OPENABLE_FRACTION.get(kind, 0.7)
                required = max(room.area * 0.11, (room.area / 6) / openable_fraction)
                if room.type.is_wet:
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

                share = required / len(chosen)
                for wall in chosen:
                    usable_length = max(0.6, wall.length - 0.6)
                    height = 0.75 if room.type.is_wet else 1.35
                    width = min(usable_length, max(0.6, share / height))
                    wall.openings.append(
                        Opening(
                            kind=kind,
                            wall_id=wall.id,
                            position=0.5,
                            width=round(width, 3),
                            height=height,
                            sill_height=1.8 if room.type.is_wet else 0.9,
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

    def _legally_reachable(self, level: Level, adjacency: dict[str, set[str]]) -> set[str]:
        """Rooms a legal door tree can reach from the entrance.

        The same walk the door placer performs, without cutting anything: grow
        only out of through-rooms, enter only where the programme allows.
        Whatever it cannot reach, the placer will only reach by breaching.
        """
        from aip.engines.architecture.programme import is_through, may_enter

        rooms = {r.id: r for r in level.rooms}
        root = next((r.id for r in level.rooms if r.type in _ENTRY_ROOMS), None)
        if root is None:
            root = next((r.id for r in level.rooms if r.type is RoomType.LIVING), None)
        if root is None:
            return set(rooms)
        seen = {root}
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
            reached = self._legally_reachable(level, adjacency)
            return [r.id for r in rooms if r.id not in reached]

        stuck = unreachable()
        attempts = 0
        while stuck and attempts < 12:
            attempts += 1
            improved = False
            for stuck_id in stuck:
                a = by_id[stuck_id]
                # Candidates: rooms whose area is close enough that the swap
                # does not wreck either programme entry.
                candidates = sorted(
                    (b for b in rooms if b.id != a.id and a.type is not b.type
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

        rooms = {r.id: r for r in level.rooms}
        if not rooms:
            return
        adjacency = self._door_adjacency(plan, level)

        # Root at the foyer, else the living room, else the largest room.
        root = next((r.id for r in level.rooms if r.type is RoomType.FOYER), None)
        if root is None:
            root = next((r.id for r in level.rooms if r.type is RoomType.LIVING), None)
        if root is None:
            root = max(level.rooms, key=lambda r: r.area).id

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

        def push(node: str, *, strict: bool = True) -> None:
            if strict and not may_expand_from(node):
                return
            for neighbour in adjacency.get(node, set()):
                if neighbour in connected:
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

                # Everything else comes from the declared programme rather than
                # from heuristics maintained separately here, so the doors the
                # plan ends up with cannot contradict the adjacency rules the
                # same plan is scored against.
                cost *= door_cost_factor(a.type, b.type, self.brief.kind)
                frontier.append((cost, node, neighbour))

        # Attached rooms hang off their host regardless of the through-rule.
        def push_attached(node: str) -> None:
            for neighbour in adjacency.get(node, set()):
                if neighbour in connected:
                    continue
                hosts = PRIVATE_HOST.get(rooms[neighbour].type, ())
                if rooms[node].type in hosts:
                    frontier.append((0.05, node, neighbour))
                # An attached bathroom: a bathroom whose host asked for one.
                if rooms[neighbour].type is RoomType.BATHROOM and self._wants_attached(rooms[node]):
                    frontier.append((0.05, node, neighbour))

        push(root)
        while frontier and len(connected) < len(rooms):
            frontier.sort()
            _cost, source, target = frontier.pop(0)
            if target in connected:
                continue
            wall = _wall_between(level, source, target)
            if wall is not None:
                edge = shared_edge(rooms[source].polygon, rooms[target].polygon)
                width = 0.9
                if edge is not None:
                    width = min(1.05, max(0.75, edge[0].distance_to(edge[1]) - 0.4))
                wall.openings.append(
                    Opening(
                        kind=OpeningKind.DOOR,
                        wall_id=wall.id,
                        position=0.5,
                        width=round(width, 3),
                        height=2.1,
                        sill_height=0.0,
                        connects=(source, target),
                    )
                )
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

        # The main entrance goes on the exterior wall of the root room, facing
        # the road wherever the site tells us where the road is.
        self._place_main_door(plan, level, rooms[root])

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
            for index, (score, _breakdown, plan) in enumerate(pool):
                similarity = max(
                    self._similarity(plan, picked[2]) for picked in chosen
                )
                value = score - 0.45 * similarity
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
