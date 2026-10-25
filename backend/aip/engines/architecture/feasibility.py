"""Can the programme physically fit the plot? Decided before any search runs.

A slicing-tree search always returns *something*: hand it five bedrooms and a
72 m2 envelope and it will tile that envelope with five rooms, each one
whatever width the arithmetic leaves over. The result scores acceptably on
every proxy and is a floor plan on which a bedroom is 1.5 m wide and a
bathroom passes through the kitchen. The failure is not in the search; it is
that nobody asked whether the question had an answer.

This module asks it first, in the architect's order of preference:

1. **Add a floor** - bedrooms go up, the public rooms stay down, a staircase
   appears - when the plot's FAR and height limit allow.
2. **Drop what is optional**, least important first: study, balcony, utility,
   puja (kept as a wall niche), then bathrooms beyond one per two bedrooms
   plus a common one.
3. **Draw every room smaller**, toward - never below - its minimum.
4. **Say no.** If even that does not fit, raise `InfeasibleBriefError` with
   the numbers, instead of drawing a plan that lies about what is possible.

Each step is written down as a plain-English advisory, because a plan that
quietly differs from the brief is how a client finds out at the site visit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from aip.domain.brief import NBC_MIN_AREAS, RoomRequirement
from aip.domain.plan import RoomType

#: Floor-to-floor height the generator draws, used by the height rule.
FLOOR_TO_FLOOR = 3.15

#: Fraction of the buildable envelope that rooms can actually occupy. A slicing
#: partition cannot give every room exactly its minimum shape, so a programme
#: that needs 100% of the envelope at minimum sizes is not buildable, it merely
#: has no arithmetic objection.
PACKING_EFFICIENCY = 0.93

#: Fraction of the envelope a programme may occupy and still be called
#: comfortable. A plan at 93% density has the arithmetic and none of the slack
#: the partition needs to give every room its proportions; measured on the
#: sweep, plans above about 86% almost never come out clean.
COMFORT_PACKING = 0.78

#: A programme "fits comfortably" when every room can be drawn at this fraction
#: of the size asked for. Below it, the plan is a squeeze and the architect
#: would change the programme rather than the room sizes.
COMFORT_FRACTION = 0.72

#: Aspect a room is assumed to be drawn at when its smallest legal area is
#: derived from its minimum clear width.
SENSIBLE_ASPECT: dict[RoomType, float] = {
    RoomType.BATHROOM: 1.7, RoomType.TOILET: 1.8, RoomType.POWDER: 1.8,
    RoomType.UTILITY: 1.8, RoomType.STORE: 1.6, RoomType.PUJA: 1.4,
    RoomType.PANTRY: 1.8, RoomType.LAUNDRY: 1.8, RoomType.KITCHEN: 1.8,
    RoomType.FOYER: 1.6, RoomType.GARAGE: 2.0,
}
DEFAULT_ASPECT = 1.4

#: Smallest areas a practice will draw, where the code is more lenient than
#: sense. NBC allows a 9.5 m2 living room; nobody offers one to a client.
PRACTICAL_MIN_AREA: dict[RoomType, float] = {
    RoomType.LIVING: 12.0, RoomType.DRAWING: 10.0, RoomType.FAMILY: 10.0,
    RoomType.DINING: 7.5, RoomType.KITCHEN: 6.0,
    RoomType.MASTER_BEDROOM: 11.0, RoomType.BEDROOM: 9.5,
    RoomType.GUEST_BEDROOM: 9.5, RoomType.CHILDREN_BEDROOM: 9.5,
    RoomType.STUDY: 7.5, RoomType.HOME_OFFICE: 7.5,
    RoomType.PUJA: 1.8, RoomType.STORE: 2.0, RoomType.UTILITY: 2.4,
    RoomType.FOYER: 3.0, RoomType.GARAGE: 13.0, RoomType.BATHROOM: 3.0,
    RoomType.TOILET: 1.8, RoomType.POWDER: 1.8, RoomType.PANTRY: 2.4,
    RoomType.LAUNDRY: 2.4, RoomType.WARDROBE: 2.4, RoomType.SERVANT: 7.5,
}

#: The smallest rectangle (short side, long side) in which a room's essential
#: furniture and its clearances fit: a double bed with a person either side of
#: it, a sofa facing a wall, a table with chairs pulled out. Below this a room
#: has the right area and the wrong shape - a 1.4 x 3.9 bathroom is 5.5 m2 and
#: cannot take a WC, a basin and a door swing.
FURNISH_MIN: dict[RoomType, tuple[float, float]] = {
    RoomType.MASTER_BEDROOM: (3.3, 3.6), RoomType.BEDROOM: (3.0, 3.0),
    RoomType.GUEST_BEDROOM: (3.0, 3.0), RoomType.CHILDREN_BEDROOM: (3.0, 3.0),
    RoomType.LIVING: (3.6, 4.2), RoomType.DINING: (2.7, 3.0),
    RoomType.KITCHEN: (2.1, 2.7), RoomType.BATHROOM: (1.5, 2.1),
    RoomType.STAIRCASE: (2.3, 3.8), RoomType.UTILITY: (1.2, 1.8),
    RoomType.PUJA: (1.2, 1.2), RoomType.FOYER: (1.5, 1.8),
}

#: What may be given up, in the order it goes. Puja is not lost: it becomes a
#: wall niche in the living room, which is what a compact plot does.
OPTIONAL_ORDER: tuple[RoomType, ...] = (
    RoomType.STUDY, RoomType.BALCONY, RoomType.UTILITY, RoomType.PUJA,
)

BEDROOM_TYPES = frozenset({
    RoomType.MASTER_BEDROOM, RoomType.BEDROOM,
    RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM,
})


class InfeasibleBriefError(ValueError):
    """The programme cannot be drawn on this plot at any size the code allows.

    Typed, rather than a bare `ValueError`, so the API and the design stream
    can turn it into a message the client can act on instead of a 500.
    """

    def __init__(
        self,
        message: str,
        *,
        needed_area: float = 0.0,
        available_area: float = 0.0,
        levels: int = 1,
        advisories: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.needed_area = needed_area
        self.available_area = available_area
        self.levels = levels
        self.advisories = list(advisories or [])

    def to_dict(self) -> dict[str, object]:
        return {
            "code": "infeasible_brief",
            "message": str(self),
            "needed_area_m2": round(self.needed_area, 1),
            "available_area_m2": round(self.available_area, 1),
            "levels": self.levels,
            "advisories": self.advisories,
        }


def minimum_area(req: RoomRequirement, clear_width: float) -> float:
    """The smallest this room may be drawn: the larger of its area and width rules.

    `max(min_area(type), min_clear_width(type)^2 x sensible aspect)`. The first
    term is the code and the client's own stated minimum; the second is what
    makes a 1.5 m-wide bathroom at least 1.5 x 2.5 and not 1.5 x 1.2. Never more
    than the room was asked for: a client who wants a 6 m2 bedroom has been told
    about the code by the compliance critic, not by an infeasibility error.
    """
    aspect = SENSIBLE_ASPECT.get(req.type, DEFAULT_ASPECT)
    furnish = FURNISH_MIN.get(req.type, (0.0, 0.0))
    floor = max(
        furnish[0] * furnish[1],
        req.min_area or 0.0,
        NBC_MIN_AREAS.get(req.type, 0.0),
        PRACTICAL_MIN_AREA.get(req.type, 0.0),
        clear_width * clear_width * aspect,
    )
    return min(floor, req.target_area) if req.target_area > 0 else floor


def comfortable_area(req: RoomRequirement, minimum: float) -> float:
    """What the room is drawn at without anyone calling it a squeeze."""
    return max(minimum, COMFORT_FRACTION * req.target_area)


def bedrooms_in(requirements: list[RoomRequirement]) -> int:
    return sum(1 for r in requirements if r.type in BEDROOM_TYPES)


def allowed_bathrooms(bedrooms: int) -> int:
    """One per two bedrooms plus a common one: the most a tight plot keeps."""
    return math.ceil(bedrooms / 2) + 1


def max_levels(site_max_height: float) -> int:
    """How many floors the height limit allows at the drawn floor-to-floor."""
    return max(1, int(site_max_height // FLOOR_TO_FLOOR))


def storey_word(levels: int) -> str:
    return "single-storey" if levels <= 1 else f"{levels}-storey"


@dataclass(slots=True)
class FeasibilityReport:
    """What the gate decided, kept on the plan for the client and the tests."""

    requested_levels: int
    levels: int
    needed_area: float = 0.0
    available_area: float = 0.0
    dropped: list[str] = field(default_factory=list)
    shrunk: bool = False
    advisories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_levels": self.requested_levels,
            "levels": self.levels,
            "needed_area_m2": round(self.needed_area, 1),
            "available_area_m2": round(self.available_area, 1),
            "dropped": self.dropped,
            "shrunk": self.shrunk,
        }


# ---------------------------------------------------------------------------
# Generous plots
# ---------------------------------------------------------------------------

#: The largest a room is drawn, however large the plot. Past these a room stops
#: being more comfortable and becomes a hall: a 70 m2 living room is a ballroom
#: with a sofa in it. Rooms with no entry have no cap of their own.
LUXURY_MAX: dict[RoomType, float] = {
    RoomType.LIVING: 70.0, RoomType.DINING: 35.0, RoomType.KITCHEN: 30.0,
    RoomType.MASTER_BEDROOM: 40.0, RoomType.BEDROOM: 28.0,
    RoomType.GUEST_BEDROOM: 28.0, RoomType.CHILDREN_BEDROOM: 28.0,
    RoomType.BATHROOM: 12.0, RoomType.STAIRCASE: 20.0,
    RoomType.DRAWING: 50.0, RoomType.FAMILY: 45.0, RoomType.STUDY: 25.0,
    RoomType.HOME_OFFICE: 25.0, RoomType.PUJA: 12.0, RoomType.UTILITY: 12.0,
    RoomType.STORE: 12.0, RoomType.FOYER: 24.0, RoomType.GARAGE: 40.0,
    RoomType.TOILET: 5.0, RoomType.POWDER: 6.0, RoomType.PANTRY: 10.0,
    RoomType.LAUNDRY: 10.0, RoomType.BALCONY: 18.0, RoomType.GYM: 35.0,
    RoomType.HOME_THEATRE: 40.0, RoomType.LIBRARY: 30.0, RoomType.SERVANT: 14.0,
    RoomType.WARDROBE: 12.0,
}

#: Share of the cap a scaled room is aimed at. The search stretches rooms a
#: little either way, so aiming at the cap itself would put half of them over.
CAP_HEADROOM = 0.9

#: The footprint is "reasonably filled" at this fraction of what the plot allows.
FILL_TARGET = 0.75

#: Rooms added, in this order, when every room is at its cap and the footprint
#: is still not full: (type, area m2, what it is called, why it earns its place).
#: Each is something a house with that much plot genuinely has.
EXTRA_ROOMS: tuple[tuple[RoomType, float, str, str], ...] = (
    (RoomType.FAMILY, 20.0, "a family lounge",
     "a second sitting space so the household is not all in the formal living room"),
    (RoomType.STUDY, 11.0, "a study", "a quiet room to work from home"),
    (RoomType.GUEST_BEDROOM, 14.0, "a guest bedroom suite",
     "guests and elders are best kept off the stairs"),
    (RoomType.HOME_THEATRE, 18.0, "a home theatre", "somewhere to watch together"),
    (RoomType.VERANDAH, 12.0, "a covered verandah / sit-out",
     "a shaded outdoor room at the front of the house"),
    (RoomType.COURTYARD, 16.0, "an internal courtyard open to the sky",
     "light, air and a cool centre for a deep plan"),
)


#: What a room of each kind is drawn at most in a house of three bedrooms or
#: fewer. A 44 m2 living room in a 3BHK is a third of the floor with a foyer of
#: 7 m2 beside it; the sizes below are what a practice draws, and a bigger plot
#: is answered with more rooms, not with fatter ones. Larger houses scale these
#: up (see `comfort_cap`), and nothing passes `LUXURY_MAX`.
COMFORT_BASE: dict[RoomType, float] = {
    RoomType.LIVING: 26.0, RoomType.DRAWING: 20.0, RoomType.FAMILY: 20.0,
    RoomType.DINING: 16.0, RoomType.KITCHEN: 13.0,
    RoomType.MASTER_BEDROOM: 20.0, RoomType.BEDROOM: 14.0, RoomType.GUEST_BEDROOM: 14.0,
    RoomType.CHILDREN_BEDROOM: 14.0, RoomType.BATHROOM: 6.0, RoomType.TOILET: 3.0,
    RoomType.POWDER: 3.0, RoomType.STAIRCASE: 11.0, RoomType.FOYER: 8.0,
    RoomType.PUJA: 5.5, RoomType.UTILITY: 5.0, RoomType.STORE: 5.0, RoomType.PANTRY: 5.0,
    RoomType.LAUNDRY: 5.0, RoomType.STUDY: 11.0, RoomType.HOME_OFFICE: 11.0,
    RoomType.GARAGE: 18.0, RoomType.BALCONY: 8.0, RoomType.GYM: 16.0,
    RoomType.HOME_THEATRE: 18.0, RoomType.LIBRARY: 14.0, RoomType.SERVANT: 9.0,
    RoomType.WARDROBE: 6.0,
}


def comfort_cap(room_type: RoomType, bedrooms: int) -> float | None:
    """The largest a room of this kind is drawn in a house of this many bedrooms."""
    base = COMFORT_BASE.get(room_type)
    if base is None:
        return None
    grown = base * (1.0 if bedrooms <= 3 else 1.25 if bedrooms == 4 else 1.6 if bedrooms == 5 else 2.0)
    ceiling = LUXURY_MAX.get(room_type)
    return grown if ceiling is None else min(grown, ceiling)


def luxury_max(room_type: RoomType) -> float | None:
    return LUXURY_MAX.get(room_type)
