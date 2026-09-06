"""Functional programme: what has to sit next to what, and why.

A floorplan can satisfy every metric this system measures - daylight, area,
ventilation, code, even Vastu - and still be an unusable building, because none
of those metrics ask the only question an architect asks first: *can you live in
it?* A kitchen in one corner and a dining room in the opposite corner passes
every numeric check and fails as a house.

That knowledge is missing from a client brief because no client thinks to write
it down. Nobody says "the kitchen should be near where we eat" any more than
they specify that doors should open. It is the architect's programme, and it
belongs in the tool.

The relationships below are the standard functional adjacencies of Indian
residential planning. Three ideas drive them:

**Sequence.** A house is entered and traversed in an order: arrive, receive,
gather, eat, retire. Rooms adjacent in that sequence should be adjacent in plan,
because every break in the sequence becomes a corridor or a walk through
somewhere private.

**Zoning.** Public (receive and gather), private (sleep), and service (cook,
wash, store) want to be grouped, not interleaved. A bedroom wedged between the
kitchen and the living room has no acoustic or visual privacy no matter how
large it is or how well it is lit.

**Separation.** Some pairs must be kept apart: a WC opening onto the dining
room, a bedroom door off the kitchen, a bathroom facing the front door. These
are the failures a client notices immediately and forgives never.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from aip.domain.brief import ClientBrief, ProjectKind, RoomRequirement
from aip.domain.plan import FloorPlan, RoomType


class Zone(str, Enum):
    """Which part of the house a room belongs to."""

    PUBLIC = "public"        # received guests reach these
    PRIVATE = "private"      # the household only
    SERVICE = "service"      # cooking, washing, storage
    CIRCULATION = "circulation"


ZONE_OF: dict[RoomType, Zone] = {
    RoomType.FOYER: Zone.CIRCULATION,
    RoomType.LOBBY: Zone.CIRCULATION,
    RoomType.CORRIDOR: Zone.CIRCULATION,
    RoomType.STAIRCASE: Zone.CIRCULATION,

    RoomType.LIVING: Zone.PUBLIC,
    RoomType.DRAWING: Zone.PUBLIC,
    RoomType.DINING: Zone.PUBLIC,
    RoomType.FAMILY: Zone.PUBLIC,
    RoomType.PUJA: Zone.PUBLIC,
    RoomType.VERANDAH: Zone.PUBLIC,
    RoomType.HOME_THEATRE: Zone.PUBLIC,
    RoomType.LIBRARY: Zone.PUBLIC,

    RoomType.MASTER_BEDROOM: Zone.PRIVATE,
    RoomType.BEDROOM: Zone.PRIVATE,
    RoomType.GUEST_BEDROOM: Zone.PRIVATE,
    RoomType.CHILDREN_BEDROOM: Zone.PRIVATE,
    RoomType.STUDY: Zone.PRIVATE,
    RoomType.HOME_OFFICE: Zone.PRIVATE,
    RoomType.WARDROBE: Zone.PRIVATE,
    RoomType.SERVANT: Zone.PRIVATE,

    RoomType.KITCHEN: Zone.SERVICE,
    RoomType.PANTRY: Zone.SERVICE,
    RoomType.UTILITY: Zone.SERVICE,
    RoomType.LAUNDRY: Zone.SERVICE,
    RoomType.STORE: Zone.SERVICE,
    RoomType.BATHROOM: Zone.SERVICE,
    RoomType.TOILET: Zone.SERVICE,
    RoomType.POWDER: Zone.SERVICE,
    RoomType.GARAGE: Zone.SERVICE,
}


@dataclass(frozen=True, slots=True)
class Relation:
    """One functional relationship between two room types."""

    a: RoomType
    b: RoomType
    #: Positive = they should touch. Negative = they must not.
    weight: float
    reason: str
    #: What the rule actually governs.
    #:
    #: ``"wall"``  - sharing a wall is itself the problem (plumbing against a
    #:               shrine, a WC backing onto the cooking counter).
    #: ``"door"``  - the wall is fine and usually unavoidable on a compact plot;
    #:               it is a *door* between them that is the defect. Applying
    #:               these at wall level condemns plans that are perfectly
    #:               normal, which is how a rule set stops being believable.
    #: ``"both"``  - governs adjacency and connection alike.
    scope: str = "both"

    @property
    def required(self) -> bool:
        return self.weight > 0

    def governs_wall(self) -> bool:
        return self.scope in ("wall", "both")

    def governs_door(self) -> bool:
        return self.scope in ("door", "both")


#: The residential programme. Weights are relative importance, not probabilities:
#: kitchen-to-dining at 1.0 is the relationship whose absence makes a plan wrong,
#: while puja-to-living at 0.4 is a preference worth having and worth trading.
RESIDENCE: tuple[Relation, ...] = (
    # -- the sequence ----------------------------------------------------
    Relation(RoomType.FOYER, RoomType.LIVING, 1.0,
             "You arrive into the living room; a foyer that leads anywhere else "
             "forces guests through the house to be received."),
    Relation(RoomType.LIVING, RoomType.DINING, 0.9,
             "Gathering and eating are one continuous activity in an Indian "
             "household, and the two rooms are usually opened into each other."),
    Relation(RoomType.DINING, RoomType.KITCHEN, 1.0,
             "Food is carried from one to the other several times a meal. This "
             "is the single relationship whose absence most obviously marks a "
             "plan as machine-generated."),
    Relation(RoomType.KITCHEN, RoomType.UTILITY, 0.8,
             "Washing-up, the sink and the service yard are one workflow."),
    Relation(RoomType.KITCHEN, RoomType.STORE, 0.6,
             "Dry goods are stored beside where they are cooked."),
    Relation(RoomType.KITCHEN, RoomType.PANTRY, 0.8,
             "A pantry that is not beside the kitchen is a cupboard in the wrong room."),

    # -- sanitation serves sleeping --------------------------------------
    Relation(RoomType.MASTER_BEDROOM, RoomType.BATHROOM, 0.9,
             "The master bedroom's bathroom must be reachable without crossing "
             "a public room in the night."),
    Relation(RoomType.BEDROOM, RoomType.BATHROOM, 0.7,
             "A bathroom should serve the bedrooms it is provided for."),
    Relation(RoomType.MASTER_BEDROOM, RoomType.WARDROBE, 0.5,
             "Dressing belongs with sleeping."),

    # -- quiet wants quiet -----------------------------------------------
    Relation(RoomType.PUJA, RoomType.LIVING, 0.4,
             "A shrine is used by the household together, so it opens off the "
             "shared room rather than off a bedroom."),
    Relation(RoomType.STUDY, RoomType.BEDROOM, 0.3,
             "Study and sleep sit in the same quiet zone."),

    # -- what must be kept apart -----------------------------------------
    Relation(RoomType.KITCHEN, RoomType.TOILET, -1.0,
             "A WC sharing a wall with a kitchen is a hygiene failure, and every "
             "Vastu authority prohibits it independently."),
    Relation(RoomType.KITCHEN, RoomType.BATHROOM, -0.7,
             "Same objection, softened: a bathroom is less objectionable than a "
             "WC but still does not belong against the cooking wall."),
    Relation(RoomType.DINING, RoomType.TOILET, -0.9,
             "A lavatory door opening onto the table is the complaint clients "
             "raise first and forgive last.",
             scope="door"),
    Relation(RoomType.FOYER, RoomType.TOILET, -0.8,
             "A WC facing the entrance is the first thing a visitor sees.",
             scope="door"),
    Relation(RoomType.FOYER, RoomType.BATHROOM, -0.6,
             "As above, and it wastes the frontage on a windowless room.",
             scope="door"),
    Relation(RoomType.FOYER, RoomType.MASTER_BEDROOM, -0.7,
             "Entering directly into the household's own bedroom destroys the "
             "privacy gradient the plan exists to create.",
             scope="door"),
    Relation(RoomType.FOYER, RoomType.BEDROOM, -0.5,
             "A bedroom door onto the entrance has no privacy buffer.",
             scope="door"),
    Relation(RoomType.KITCHEN, RoomType.MASTER_BEDROOM, -0.5,
             "Cooking noise and smell against the head of the bed.",
             scope="door"),
    Relation(RoomType.KITCHEN, RoomType.BEDROOM, -0.4,
             "As above, for the secondary bedrooms.",
             scope="door"),
    Relation(RoomType.PUJA, RoomType.TOILET, -1.0,
             "Sanitation against a shrine wall defiles it - the one objection "
             "that is doctrinal rather than functional, and absolute."),
    Relation(RoomType.PUJA, RoomType.BATHROOM, -0.8,
             "The same objection at slightly lower force."),
    Relation(RoomType.PUJA, RoomType.KITCHEN, -0.3,
             "Cooking smoke is mildly polluting to a shrine."),
)


#: Apartments compress the same programme; the relationships do not change, only
#: the tolerance for missing them, which the caller expresses through weighting.
PROGRAMMES: dict[ProjectKind, tuple[Relation, ...]] = {
    ProjectKind.RESIDENCE: RESIDENCE,
}


def programme_for(kind: ProjectKind) -> tuple[Relation, ...]:
    """The functional programme for a project kind.

    Kinds without a specific programme fall back to the residential one, which
    is a reasonable default for anything domestic in scale, rather than to no
    programme at all - having no opinion is how the generator produced kitchens
    across the house from the dining room.
    """
    return PROGRAMMES.get(kind, RESIDENCE)


# ---------------------------------------------------------------------------
# Applying the programme to a brief
# ---------------------------------------------------------------------------


def apply_defaults(brief: ClientBrief) -> ClientBrief:
    """Fill in adjacency the client never thought to state.

    A requirement that already names its own relationships is left completely
    alone: an explicit brief is a decision, and silently adding to it would
    override the architect. Only silence is filled.
    """
    programme = programme_for(brief.kind)
    present = {req.type for req in brief.requirements}

    wanted: dict[RoomType, list[RoomType]] = {}
    unwanted: dict[RoomType, list[RoomType]] = {}
    for rel in programme:
        if rel.a not in present or rel.b not in present:
            continue
        target = wanted if rel.required else unwanted
        target.setdefault(rel.a, []).append(rel.b)
        target.setdefault(rel.b, []).append(rel.a)

    updated: list[RoomRequirement] = []
    for req in brief.requirements:
        if req.must_be_adjacent_to or req.must_not_be_adjacent_to:
            updated.append(req)
            continue
        copy = req.model_copy(deep=True)
        copy.must_be_adjacent_to = list(dict.fromkeys(wanted.get(req.type, [])))
        copy.must_not_be_adjacent_to = list(dict.fromkeys(unwanted.get(req.type, [])))
        updated.append(copy)

    out = brief.model_copy(deep=True)
    out.requirements = updated
    return out


# ---------------------------------------------------------------------------
# Scoring a realised plan
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProgrammeReport:
    """How well a plan satisfies its functional programme."""

    score: float = 0.0
    adjacency: float = 0.0
    zoning: float = 0.0
    honoured: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "adjacency": round(self.adjacency, 4),
            "zoning": round(self.zoning, 4),
            "honoured": self.honoured,
            "broken": self.broken,
        }


def score_pairs(
    touching: set[tuple[RoomType, RoomType]],
    present: set[RoomType],
    kind: ProjectKind,
) -> tuple[float, list[str], list[str]]:
    """Score a set of touching room-type pairs against the programme.

    Shared by the cheap surrogate (which knows only rectangles) and the exact
    evaluation (which knows walls), so both optimise the same thing. When they
    disagree the search converges on something the final ranking then rejects,
    which is how a surrogate quietly stops helping.

    Relationships are weighted by importance rather than counted. Treating
    kitchen-to-dining as worth the same as study-to-bedroom is why a plan could
    satisfy most of its programme and still get the one relationship wrong that
    everybody notices.
    """
    earned = possible = 0.0
    honoured: list[str] = []
    broken: list[str] = []

    for rel in programme_for(kind):
        if rel.a not in present or rel.b not in present:
            continue
        if not rel.governs_wall():
            continue
        magnitude = abs(rel.weight)
        possible += magnitude
        met = (rel.a, rel.b) in touching
        if met if rel.required else not met:
            earned += magnitude
            honoured.append(f"{rel.a.label} / {rel.b.label}")
        else:
            verb = "should adjoin" if rel.required else "must not adjoin"
            broken.append(f"{rel.a.label} {verb} {rel.b.label} - {rel.reason}")

    return (earned / possible if possible else 1.0), honoured, broken


def door_cost_factor(a: RoomType, b: RoomType, kind: ProjectKind) -> float:
    """How reluctant the plan should be to put a door between two room types.

    Returned as a multiplier on the spanning-tree edge cost that decides which
    adjacencies become doors. Below 1.0 the connection is wanted; above 1.0 it
    is tolerated only when nothing else reaches the room.

    Driving this from the same programme that scores adjacency keeps one source
    of truth. Hand-written door heuristics drift away from the stated programme
    over time, and then the plan's circulation quietly contradicts its own
    design rules.
    """
    factor = 1.0
    for rel in programme_for(kind):
        if {rel.a, rel.b} != {a, b} or not rel.governs_door():
            continue
        # A wanted pair gets a discount proportional to how much it is wanted;
        # an unwanted pair gets a penalty that grows with the objection.
        factor *= (1.0 - 0.45 * rel.weight) if rel.required else (1.0 + 4.0 * abs(rel.weight))
    return factor


def evaluate(plan: FloorPlan, brief: ClientBrief, level_index: int = 0) -> ProgrammeReport:
    """Score a plan against the functional programme.

    Two components. **Adjacency** asks whether the relationships that matter are
    realised, weighted by how much each one matters. **Zoning** asks whether the
    private rooms cluster instead of being scattered through the public ones -
    a plan can satisfy every pairwise rule and still interleave the zones.
    """
    report = ProgrammeReport()
    level = plan.level_at(level_index)
    if level is None or len(level.rooms) < 2:
        return report

    by_id = {room.id: room for room in level.rooms}
    graph = plan.adjacency(level_index)
    touching: set[tuple[RoomType, RoomType]] = set()
    for room_id, neighbours in graph.items():
        for other in neighbours:
            a, b = by_id[room_id].type, by_id[other].type
            touching.add((a, b))
            touching.add((b, a))

    present = {room.type for room in level.rooms}
    report.adjacency, report.honoured, report.broken = score_pairs(
        touching, present, brief.kind
    )

    # Door-scoped separations are judged on what was actually connected, not on
    # what happens to share a wall.
    connected: set[tuple[RoomType, RoomType]] = set()
    for wall in level.walls:
        for opening in wall.openings:
            pair = getattr(opening, "connects", None)
            if not pair or not opening.kind.is_door:
                continue
            first, second = pair
            if first in by_id and second in by_id:
                x, y = by_id[first].type, by_id[second].type
                connected.add((x, y))
                connected.add((y, x))

    for rel in programme_for(brief.kind):
        if rel.scope != "door" or rel.required:
            continue
        if rel.a not in present or rel.b not in present:
            continue
        if (rel.a, rel.b) in connected:
            report.broken.append(
                f"{rel.a.label} must not open into {rel.b.label} - {rel.reason}"
            )
    report.zoning = _zoning_score(level, graph, by_id)
    # Adjacency carries the weight: a broken pair is a concrete defect a client
    # can point at, while poor zoning is a diffuse quality of the plan.
    report.score = round(0.7 * report.adjacency + 0.3 * report.zoning, 5)
    return report


def _zoning_score(level, graph: dict[str, set[str]], by_id: dict) -> float:
    """Fraction of each private room's neighbours that are not public rooms.

    A bedroom surrounded by living and dining has no buffer. Circulation and
    other private rooms are neutral neighbours - a corridor is exactly what
    should separate the zones - so only genuinely public neighbours count
    against it.
    """
    scores: list[float] = []
    for room in level.rooms:
        if ZONE_OF.get(room.type) is not Zone.PRIVATE:
            continue
        neighbours = graph.get(room.id, set())
        if not neighbours:
            continue
        public = sum(
            1 for n in neighbours
            if ZONE_OF.get(by_id[n].type) is Zone.PUBLIC
        )
        scores.append(1.0 - public / len(neighbours))
    return sum(scores) / len(scores) if scores else 1.0
