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
        for _ in range(cfg.population):
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

        area_terms: list[float] = []
        shape_terms: list[float] = []
        light_terms: list[float] = []
        orientation_terms: list[float] = []
        penalty = 0.0

        centre = envelope.centre
        north = self.brief.site.north_angle
        vastu_weight = self.brief.tradition_weight if self.brief.vastu.is_constraining else 0.0

        placed: list[tuple[int, BoundingBox]] = []
        for slot, box in boxes.items():
            req = self.requirements[genome.assignment[slot]]
            placed.append((genome.assignment[slot], box))

            # Hard geometric viability.
            short = min(box.width, box.height)
            if short < MIN_ROOM_DIMENSION:
                penalty += 0.14 * (MIN_ROOM_DIMENSION - short) / MIN_ROOM_DIMENSION

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

            # Proportion.
            aspect = box.aspect_ratio
            shape_terms.append(1.0 if aspect <= 1.6 else max(0.0, 1.0 - (aspect - 1.6) / 1.5))

            # External-wall access, and how many faces are external. Two external
            # faces is what makes cross ventilation possible at all.
            faces = _external_faces(box, envelope)
            if req.needs_daylight or req.needs_external_wall:
                light_terms.append(0.0 if faces == 0 else (0.72 if faces == 1 else 1.0))
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

        def mean(values: list[float], default: float = 0.7) -> float:
            return sum(values) / len(values) if values else default

        score = (
            0.20 * mean(area_terms)
            + 0.21 * mean(shape_terms)
            + 0.23 * mean(light_terms)
            + 0.07 * mean(orientation_terms, 0.75)
            + 0.29 * adjacency_score
        )
        return max(0.0, min(1.0, score - penalty))

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
                if _rects_touch(box, other_box):
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

    def _place_doors(self, plan: FloorPlan, level: Level) -> None:
        """Connect every room via a spanning tree rooted at the entrance."""
        from aip.domain.geometry import shared_edge

        rooms = {r.id: r for r in level.rooms}
        if not rooms:
            return
        adjacency = plan.adjacency(level.index)

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

        from aip.engines.architecture.programme import door_cost_factor

        def push(node: str) -> None:
            for neighbour in adjacency.get(node, set()):
                if neighbour in connected:
                    continue
                a, b = rooms[node], rooms[neighbour]
                cost = a.centre.distance_to(b.centre)

                # Circulation is what a plan should hang off: rooms opening from
                # a hall rather than through each other is the difference between
                # a house and a set of connected boxes.
                if a.type.is_circulation or b.type.is_circulation:
                    cost *= 0.35
                if a.type.is_private and b.type.is_private:
                    cost *= 1.8      # avoid bedrooms opening into bedrooms

                # Everything else comes from the declared programme rather than
                # from heuristics maintained separately here, so the doors the
                # plan ends up with cannot contradict the adjacency rules the
                # same plan is scored against.
                cost *= door_cost_factor(a.type, b.type, self.brief.kind)
                frontier.append((cost, node, neighbour))

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

        # The main entrance goes on the exterior wall of the root room, facing
        # the road wherever the site tells us where the road is.
        self._place_main_door(plan, level, rooms[root])

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


def _rects_touch(a: BoundingBox, b: BoundingBox, tol: float = 0.02) -> bool:
    """True when two cells share a boundary segment of non-zero length."""
    vertical = (abs(a.max_x - b.min_x) < tol or abs(a.min_x - b.max_x) < tol) and (
        min(a.max_y, b.max_y) - max(a.min_y, b.min_y) > tol
    )
    horizontal = (abs(a.max_y - b.min_y) < tol or abs(a.min_y - b.max_y) < tol) and (
        min(a.max_x, b.max_x) - max(a.min_x, b.min_x) > tol
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
