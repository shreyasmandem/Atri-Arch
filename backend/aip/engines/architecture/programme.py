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
from aip.domain.plan import FloorPlan, OpeningKind, RoomType


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


#: Where each room belongs along the road-to-rear axis, as a fraction of the
#: plot depth: 0.0 is the road frontage, 1.0 the back boundary.
#:
#: This is the gradient every residential plan has whether or not anyone draws
#: it: you are received at the front, you sleep at the back, and the kitchen
#: sits between so that food reaches the table without crossing a bedroom. On a
#: rectangular Indian plot it is the single strongest determinant of whether a
#: plan reads as a house or as a set of rooms someone packed into a box. Pairwise
#: adjacency cannot express it - a bedroom can touch the living room at the
#: front of the plot just as easily as at the back - which is why it is a
#: separate term rather than more relationships.
DEPTH_BAND: dict[RoomType, tuple[float, float]] = {
    RoomType.VERANDAH: (0.00, 0.22),
    RoomType.FOYER: (0.00, 0.28),
    RoomType.LOBBY: (0.00, 0.30),
    RoomType.LIVING: (0.00, 0.48),
    RoomType.DRAWING: (0.00, 0.45),
    RoomType.PUJA: (0.00, 0.55),
    RoomType.HOME_OFFICE: (0.00, 0.50),   # clients may call without entering the house
    RoomType.CORRIDOR: (0.40, 0.66),   # the seam between public and private
    RoomType.STUDY: (0.20, 0.80),
    RoomType.DINING: (0.15, 0.52),     # open to the living room, at its rear edge
    RoomType.FAMILY: (0.30, 0.80),
    RoomType.KITCHEN: (0.35, 0.68),    # directly behind the dining room
    RoomType.PANTRY: (0.35, 0.90),
    RoomType.STORE: (0.40, 0.75),
    RoomType.BATHROOM: (0.30, 1.00),
    RoomType.TOILET: (0.20, 1.00),
    RoomType.GUEST_BEDROOM: (0.40, 1.00),
    RoomType.BEDROOM: (0.48, 1.00),
    RoomType.CHILDREN_BEDROOM: (0.48, 1.00),
    RoomType.MASTER_BEDROOM: (0.58, 1.00),
    RoomType.UTILITY: (0.38, 0.72),    # off the kitchen, not among the bedrooms
    RoomType.LAUNDRY: (0.38, 0.72),
    RoomType.SERVANT: (0.70, 1.00),
    RoomType.GARAGE: (0.00, 0.30),
    RoomType.BALCONY: (0.45, 1.00),
    RoomType.TERRACE: (0.45, 1.00),
}


def depth_fit(room_type: RoomType, depth: float) -> float:
    """How well a room's position along the plot suits what it is for.

    1.0 inside its band; falling off linearly outside, reaching zero half a plot
    away. A room with no band is unconstrained, which is the honest default for
    a balcony or a shaft rather than an arbitrary preference.
    """
    band = DEPTH_BAND.get(room_type)
    if band is None:
        return 1.0
    low, high = band
    if low <= depth <= high:
        return 1.0
    distance = low - depth if depth < low else depth - high
    return max(0.0, 1.0 - distance / 0.5)


#: Rooms you walk *through* to reach somewhere else. Everything not listed is a
#: dead end: you walk into it and back out, and nobody's route to anywhere
#: else passes through it.
#:
#: This is the distinction that makes a plan walkable, and it is stronger than
#: adjacency. Two rooms can share a wall and still be wrongly connected: a
#: kitchen that touches the master bedroom must not have its door there. The
#: rule that follows is the one every residential plan obeys - each dead-end
#: room opens off a through-room, and through-rooms chain back to the
#: entrance - and with two or more bedrooms it forces a passage to exist,
#: because bedrooms cannot all open off the living room.
THROUGH_ROOMS: frozenset[RoomType] = frozenset({
    RoomType.FOYER, RoomType.LOBBY, RoomType.CORRIDOR, RoomType.STAIRCASE,
    RoomType.LIVING, RoomType.DINING, RoomType.FAMILY, RoomType.DRAWING,
    RoomType.VERANDAH,
})


def is_through(room_type: RoomType) -> bool:
    return room_type in THROUGH_ROOMS


#: Dead-end rooms that may be entered only from their own private host, never
#: from circulation: an attached bathroom from its bedroom, a wardrobe from the
#: bedroom it serves. Listed so the door placer knows the host is the correct
#: door, not a circulation failure.
PRIVATE_HOST: dict[RoomType, tuple[RoomType, ...]] = {
    RoomType.WARDROBE: (RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM),
    # The wash area, pantry and dry store open off the kitchen. Reaching them
    # through the kitchen is the correct route, not a breach.
    RoomType.UTILITY: (RoomType.KITCHEN,),
    RoomType.PANTRY: (RoomType.KITCHEN,),
    RoomType.BALCONY: (RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
                       RoomType.LIVING, RoomType.DINING, RoomType.FAMILY),
    RoomType.TERRACE: (RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.LIVING,
                       RoomType.FAMILY, RoomType.STAIRCASE),
    RoomType.GARAGE: (RoomType.FOYER, RoomType.UTILITY, RoomType.LOBBY),
    RoomType.STORE: (RoomType.KITCHEN, RoomType.UTILITY),
    RoomType.LAUNDRY: (RoomType.KITCHEN, RoomType.UTILITY),
}


#: Which rooms a door into each room may come from. This is the question
#: "where must the door lead to" answered per room type, and it is stricter
#: than the through-room rule: the foyer is a through-room, and a bedroom
#: door opening straight off the entrance vestibule is still wrong.
#:
#: Rooms not listed are unconstrained beyond the through-room rule.
ENTERED_FROM: dict[RoomType, frozenset[RoomType]] = {
    RoomType.MASTER_BEDROOM: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.LIVING,
                                        RoomType.FAMILY}),
    RoomType.BEDROOM: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.LIVING,
                                 RoomType.FAMILY}),
    RoomType.GUEST_BEDROOM: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.LIVING,
                                       RoomType.FAMILY, RoomType.FOYER}),
    RoomType.CHILDREN_BEDROOM: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.LIVING,
                                          RoomType.FAMILY}),
    RoomType.STUDY: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.LIVING,
                               RoomType.MASTER_BEDROOM, RoomType.BEDROOM}),
    RoomType.KITCHEN: frozenset({RoomType.DINING, RoomType.CORRIDOR, RoomType.LIVING,
                                 RoomType.FAMILY, RoomType.UTILITY}),
    RoomType.DINING: frozenset({RoomType.LIVING, RoomType.CORRIDOR, RoomType.FOYER,
                                RoomType.FAMILY, RoomType.KITCHEN}),
    RoomType.PUJA: frozenset({RoomType.LIVING, RoomType.CORRIDOR, RoomType.FOYER,
                              RoomType.DINING, RoomType.FAMILY}),
    RoomType.UTILITY: frozenset({RoomType.KITCHEN, RoomType.CORRIDOR}),
    RoomType.BALCONY: frozenset({RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
                                 RoomType.CHILDREN_BEDROOM, RoomType.LIVING, RoomType.DINING,
                                 RoomType.FAMILY}),
    RoomType.TERRACE: frozenset({RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.LIVING,
                                 RoomType.FAMILY, RoomType.STAIRCASE, RoomType.CORRIDOR}),
    RoomType.GARAGE: frozenset({RoomType.FOYER, RoomType.UTILITY, RoomType.LOBBY,
                                RoomType.CORRIDOR}),
    RoomType.STORE: frozenset({RoomType.KITCHEN, RoomType.UTILITY, RoomType.CORRIDOR}),
    RoomType.TOILET: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.FOYER}),
    RoomType.POWDER: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.FOYER,
                                RoomType.LIVING}),
    # A bathroom is entered from the passage, or from the bedroom it is
    # attached to. Never from the dining room, the kitchen or the entrance.
    RoomType.BATHROOM: frozenset({RoomType.CORRIDOR, RoomType.LOBBY, RoomType.MASTER_BEDROOM,
                                  RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
                                  RoomType.CHILDREN_BEDROOM}),
}


def may_enter(room: RoomType, from_room: RoomType) -> bool:
    """May a door into `room` come from `from_room`?"""
    allowed = ENTERED_FROM.get(room)
    if allowed is None:
        return is_through(from_room) or from_room in PRIVATE_HOST.get(room, ())
    return from_room in allowed


@dataclass(slots=True)
class Route:
    """How you get from the front door to one room."""

    room: str
    path: list[str]
    legal: bool
    reason: str = ""


def walkability(plan: FloorPlan, level_index: int = 0) -> list[Route]:
    """Trace the route from the entrance to every room, and judge each one.

    A route is legal when every room it passes *through* is a through-room, or
    is the private host of the destination (an attached bathroom from its
    bedroom, the utility from the kitchen). Anything else - a kitchen reached
    through the master bedroom, a bedroom through a bathroom - is the failure a
    client finds on their first reading of the plan, before any number.

    This is the question "can I live in it" made computable, and it is what
    the adjacency score was standing in for and could not answer: two rooms
    can share a wall and still be connected through the wrong door.
    """
    from collections import deque

    level = plan.level_at(level_index)
    if level is None:
        return []
    rooms = {r.id: r for r in level.rooms}
    doors: dict[str, set[str]] = {}
    entry: str | None = None
    for wall in level.walls:
        for opening in wall.openings:
            if not opening.kind.is_door or not opening.connects:
                continue
            a, b = opening.connects
            if opening.kind is OpeningKind.MAIN_DOOR:
                entry = entry or a
                continue
            if a in rooms and b in rooms:
                doors.setdefault(a, set()).add(b)
                doors.setdefault(b, set()).add(a)
    if (entry is None or entry not in rooms) and level_index > 0:
        # An upper floor has no front door: you arrive by the stair, or on
        # the landing it opens onto.
        for kind in (RoomType.STAIRCASE, RoomType.LOBBY, RoomType.CORRIDOR):
            entry = next((r.id for r in level.rooms if r.type is kind), None)
            if entry is not None:
                break
    if entry is None or entry not in rooms:
        return [Route(r.display_name(), [], False, "no entrance") for r in level.rooms]

    previous: dict[str, str | None] = {entry: None}
    queue = deque([entry])
    while queue:
        node = queue.popleft()
        for nxt in doors.get(node, ()):
            if nxt not in previous:
                previous[nxt] = node
                queue.append(nxt)

    out: list[Route] = []
    for room_id, room in rooms.items():
        if room_id not in previous:
            out.append(Route(room.display_name(), [], False, "not reachable by any door"))
            continue
        chain: list[str] = []
        node: str | None = room_id
        while node is not None:
            chain.append(node)
            node = previous[node]
        chain.reverse()

        legal, reason = True, ""
        # Everything before the last hop must be a through-room.
        for mid in chain[1:-1]:
            if not is_through(rooms[mid].type):
                legal = False
                reason = f"passes through {rooms[mid].display_name()}"
                break
        # And the door itself must come from somewhere this room may be
        # entered from: a bedroom from the passage, not the front door.
        if legal and len(chain) >= 2:
            came_from = rooms[chain[-2]].type
            if not may_enter(room.type, came_from):
                legal = False
                reason = f"entered from {rooms[chain[-2]].display_name()}"
        # The hop *before* an attached room is the host, which is not a
        # through-room; allow it when it is the legitimate host.
        if not legal and len(chain) >= 3 and reason.startswith("passes through"):
            host = rooms[chain[-2]].type
            through_ok = all(is_through(rooms[m].type) for m in chain[1:-2])
            if through_ok and may_enter(room.type, host):
                legal, reason = True, ""
        out.append(Route(room.display_name(), [rooms[c].display_name() for c in chain], legal, reason))
    return out


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

    # -- the passage serves the private rooms ------------------------------
    Relation(RoomType.CORRIDOR, RoomType.MASTER_BEDROOM, 0.9,
             "The master bedroom opens off the passage, not off a public room."),
    Relation(RoomType.CORRIDOR, RoomType.BEDROOM, 0.9,
             "Each bedroom opens off the passage."),
    Relation(RoomType.CORRIDOR, RoomType.BATHROOM, 0.8,
             "The common bathroom opens off the passage, so no one crosses a "
             "bedroom or the dining room to reach it."),
    Relation(RoomType.CORRIDOR, RoomType.LIVING, 0.6,
             "The passage begins at the public rooms."),
    Relation(RoomType.CORRIDOR, RoomType.DINING, 0.6,
             "As above; either public room may be the passage's origin."),

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

    # With two or more bedrooms a passage exists in every real plan, because
    # they cannot all open off the living room and the alternative is a
    # bedroom reached through another bedroom. Inject one when the client has
    # not thought to ask; it is the architect's decision, not theirs.
    private_count = sum(
        req.count for req in updated
        if req.type in (RoomType.MASTER_BEDROOM, RoomType.BEDROOM,
                        RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM)
    )
    has_passage = any(req.type in (RoomType.CORRIDOR, RoomType.LOBBY) for req in updated)
    if private_count >= 2 and not has_passage:
        # A passage runs the full width of the house at a walkable width, so
        # its area is fixed by the plot, not by a fraction of the programme.
        # Sized as a fraction it comes out at half a metre wide, which draws
        # as a line and walks as a gap.
        site = brief.site
        box = site.bbox
        if site.road_directions and site.road_directions[0].value in ("E", "W"):
            span = box.height - site.setback_front - site.setback_rear
        else:
            span = box.width - site.setback_left - site.setback_right
        passage_width = 1.1
        updated.append(RoomRequirement(
            type=RoomType.CORRIDOR,
            preferred_area=round(max(3.5, span * passage_width), 1),
            needs_daylight=False,
            needs_external_wall=False,
            priority=1.2,
            notes="Passage serving the bedrooms; added by the programme.",
        ))

    # The entrance faces the road. Stated here as an orientation preference on
    # whichever room receives the front door, because the door placer can only
    # choose among the walls that room actually has: a foyer packed at the rear
    # of the plot has no road-facing wall to give it, and the entrance ends up
    # opening onto the back garden.
    if brief.site.road_directions:
        road = brief.site.road_directions[0]
        for req in updated:
            if req.type in (RoomType.FOYER, RoomType.LOBBY, RoomType.VERANDAH)                     and req.preferred_direction is None:
                req.preferred_direction = road

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
    walkable: float = 1.0
    routes: list[Route] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "adjacency": round(self.adjacency, 4),
            "zoning": round(self.zoning, 4),
            "walkable": round(self.walkable, 4),
            "honoured": self.honoured,
            "broken": self.broken,
            "routes": [
                {"room": r.room, "path": r.path, "legal": r.legal, "reason": r.reason}
                for r in self.routes
            ],
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
    # The door placer records every room it could only reach by going
    # through a dead end. Each is a walkability failure a client will find on
    # the first read of the plan, and it costs more than a missing adjacency.
    breaches = list(plan.metadata.get("circulation_breaches", []))
    for breach in breaches:
        report.broken.append(
            f"{breach} - a bedroom, bathroom or kitchen must open off a hall, "
            f"passage or public room, never through another private room."
        )
    if breaches:
        report.adjacency = round(
            report.adjacency * max(0.0, 1.0 - 0.25 * len(breaches)), 5
        )

    neighbourhood = _zoning_score(level, graph, by_id)
    depth = _depth_score(plan, level)
    # Depth is weighted above neighbourhood: which rooms touch which is a local
    # question, whereas front-to-back is the organising idea of the whole plan.
    report.zoning = round(0.4 * neighbourhood + 0.6 * depth, 5)

    # Walk to every room. This is the check that adjacency could never make:
    # two rooms may share a wall and still be joined by the wrong door.
    report.routes = walkability(plan, level_index)
    illegal = [r for r in report.routes if not r.legal]
    report.walkable = 1.0 - len(illegal) / max(len(report.routes), 1)
    for r in illegal:
        report.broken.append(
            f"{r.room} is reached {r.reason or 'illegally'} "
            f"({' > '.join(r.path) if r.path else 'no route'}) - a room is entered "
            f"from a hall, passage or public room, never through another private one."
        )

    # Walkability dominates. A plan you cannot move through correctly is not
    # improved by good adjacency; it is a plan whose adjacencies are connected
    # by the wrong doors.
    report.score = round(
        0.45 * report.walkable + 0.35 * report.adjacency + 0.20 * report.zoning, 5
    )
    return report


def _depth_score(plan: FloorPlan, level) -> float:
    """Area-weighted depth fit across the level."""
    if not plan.site.road_directions:
        return 1.0
    road = plan.site.road_directions[0]
    env = level.envelope()
    bearing = (road.bearing + plan.site.north_angle) % 360

    def depth_of(room) -> float:
        c = room.centre
        if 45 <= bearing < 135:
            return (env.max_x - c.x) / max(env.width, 1e-6)
        if 225 <= bearing < 315:
            return (c.x - env.min_x) / max(env.width, 1e-6)
        if bearing >= 315 or bearing < 45:
            return (env.max_y - c.y) / max(env.height, 1e-6)
        return (c.y - env.min_y) / max(env.height, 1e-6)

    weighted = total = 0.0
    for room in level.rooms:
        if room.type not in DEPTH_BAND:
            continue
        w = max(room.area, 1.0)
        weighted += depth_fit(room.type, depth_of(room)) * w
        total += w
    return weighted / total if total else 1.0


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
