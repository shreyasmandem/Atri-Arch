"""Request and response models for the HTTP API.

Kept separate from the domain model on purpose. The domain `ClientBrief` is rich
and expects an architect's vocabulary; a client filling in a form on a practice's
website does not have that vocabulary. `SimpleBriefRequest` is the reduced,
forgiving shape the embedded widget posts, and it expands into a full brief with
sensible professional defaults.
"""

from __future__ import annotations

import math

from typing import Any

from pydantic import BaseModel, Field, field_validator

from aip.domain.brief import (
    AccessibilityLevel,
    Budget,
    ClientBrief,
    DesignStyle,
    Occupant,
    ProjectKind,
    RoomRequirement,
    StylePreference,
    VastuStance,
)
from aip.domain.geometry import Direction, Vec2
from aip.domain.plan import RoomType, Site


def byelaw_limits(area: float) -> tuple[float, float]:
    """(ground coverage, FAR) a plot this size is usually allowed: the small plots of a
    town may cover and build more than a large one."""
    if area < 60:
        return 0.80, 2.0
    if area < 150:
        return 0.75, 2.0
    if area < 300:
        return 0.65, 1.75
    return 0.60, 1.5


def auto_setbacks(
    area: float, given: tuple[float | None, ...] = (None, None, None, None), short_side: float | None = None,
) -> tuple[float, float, float, float]:
    """(front, rear, left, right) in metres: what was stated, else what a plot this size takes.

    Small urban plots take byelaw relaxations (about 1.5 m front and 0.9 m sides
    for a 30 x 40 ft plot); large plots keep the full 2.5 / 1.5 / 1.2."""
    if short_side is not None and short_side <= 7.0:
        # A row-house plot (23 ft or less across): the side walls are shared with the neighbours.
        base = (1.2, 0.8, 0.0, 0.0) if area < 60 else (1.5, 1.0, 0.0, 0.0)
    elif area < 60:
        base = (1.0, 0.8, 0.6, 0.6)
    elif area < 150:
        base = (1.5, 1.0, 0.9, 0.9)
    elif area < 300:
        base = (2.0, 1.2, 1.0, 1.0)
    else:
        base = (2.5, 1.5, 1.2, 1.2)
    return tuple(g if g is not None else b for g, b in zip(given, base))  # type: ignore[return-value]


class RoomRequest(BaseModel):
    type: RoomType
    count: int = Field(default=1, ge=1, le=20)
    area: float | None = Field(default=None, gt=0, le=500)
    direction: Direction | None = None
    attached_bathroom: bool = False
    level: int | None = Field(default=None, ge=0, le=5, description="Pin to a floor (0 = ground)")
    scale: float | None = Field(default=None, gt=0.3, le=3.0, description="Grow or shrink a room the programme already has")
    attach_to: RoomType | None = Field(default=None, description="For a balcony: the room it opens off")
    label: str | None = Field(default=None, max_length=40, description="The client's own name for it: Gaming Room, Sauna")


class SimpleBriefRequest(BaseModel):
    """What the embedded widget posts. Deliberately small and forgiving."""

    project_name: str = Field(default="New Project", max_length=200)
    kind: ProjectKind = ProjectKind.RESIDENCE

    plot_width: float = Field(default=12.0, gt=2, le=300, description="metres")
    plot_depth: float = Field(default=18.0, gt=2, le=300, description="metres")
    north_angle: float = Field(default=0.0, ge=-360, le=360)
    road_direction: Direction = Direction.N
    locality: str = Field(default="Chennai, Tamil Nadu", max_length=160)
    latitude: float = Field(default=13.0827, ge=-90, le=90)
    longitude: float = Field(default=80.2707, ge=-180, le=180)

    levels: int = Field(default=1, ge=1, le=6)
    bedrooms: int = Field(default=3, ge=0, le=12)
    bathrooms: int = Field(default=2, ge=0, le=12)
    rooms: list[RoomRequest] = Field(default_factory=list)
    #: Requests on top of the default programme - from the chat or a revision:
    #: a room pinned to a floor or a quarter, resized, added, or removed.
    extra_rooms: list[RoomRequest] = Field(default_factory=list)
    remove_rooms: list[RoomType] = Field(default_factory=list)
    #: May the studio add rooms nobody asked for (a family lounge, a theatre,
    #: a courtyard) to fill a generous plot? Off: only what was asked is drawn.
    auto_extras: bool = False

    styles: list[DesignStyle] = Field(default_factory=lambda: [DesignStyle.MODERN_INDIAN])
    materials_liked: list[str] = Field(default_factory=list)
    budget: float = Field(default=0.0, ge=0)
    currency: str = Field(default="INR", max_length=8)

    vastu: VastuStance = VastuStance.BALANCED
    accessibility: AccessibilityLevel = AccessibilityLevel.BASIC

    occupant_adults: int = Field(default=2, ge=0, le=20)
    occupant_children: int = Field(default=0, ge=0, le=20)
    occupant_elders: int = Field(default=0, ge=0, le=20)

    finish_tier: str = Field(default="premium", max_length=50)
    kitchen_type: str = Field(default="open_modular", max_length=50)
    amenities: list[str] = Field(default_factory=list)

    must_haves: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=4000)

    # Left out, the byelaw for a plot this size applies (small urban plots may cover and build more).
    max_far: float | None = Field(default=None, gt=0, le=15)
    max_ground_coverage: float | None = Field(default=None, gt=0, le=1)
    setback_front: float | None = Field(default=None, ge=0, le=30)
    setback_rear: float | None = Field(default=None, ge=0, le=30)
    setback_left: float | None = Field(default=None, ge=0, le=30)
    setback_right: float | None = Field(default=None, ge=0, le=30)
    #: Outdoors: a share of the plot kept as lawn (or the lawn's size in m2),
    #: and a pool. Both hold the house's footprint down so the space is left.
    lawn_share: float | None = Field(default=None, ge=0, le=0.7, description="Share of the plot kept as lawn")
    lawn_area: float | None = Field(default=None, ge=0, le=20000, description="Lawn wanted, m2 (instead of a share)")
    pool: str = Field(default="", pattern=r"^(|none|plunge|family|lap)$", description="A pool: plunge, family or lap")

    @field_validator("must_haves", "materials_liked")
    @classmethod
    def _trim(cls, value: list[str]) -> list[str]:
        return [item.strip()[:200] for item in value if item.strip()][:20]

    def _apply_extras(self, reqs: list[RoomRequirement]) -> list[RoomRequirement]:
        """Fold the chat's room requests into the programme."""
        reqs = [r for r in reqs if r.type not in set(self.remove_rooms)]
        mark = "Requested by the client."
        claimed: set[int] = set()
        # A pool chosen for the garden is not also a room inside the house.
        garden_pool = self.pool not in ("", "none")
        for x in self.extra_rooms:
            if garden_pool and x.label and "pool" in x.label.lower():
                continue
            notes = mark + (f" Opens off the {x.attach_to.value.replace('_', ' ')}." if x.attach_to else "")
            # A room the programme already has, not yet claimed by an earlier
            # request, takes this request's floor, size and side. A second
            # request of the same kind ("a kitchen on the second floor too")
            # adds a room rather than moving the first.
            # A room with its own name (a gaming room drawn as a media room) is
            # always a room of its own, never the programme's room of that kind.
            free = [] if x.label else [r for r in reqs if r.type is x.type and id(r) not in claimed]
            if free:
                r = free[0]
                if r.count > 1:
                    r.count -= 1
                    r = RoomRequirement(type=r.type, priority=r.priority, attached_bathroom=r.attached_bathroom,
                                        needs_external_wall=r.needs_external_wall)
                    reqs.append(r)
                if x.area:
                    r.preferred_area = x.area
                elif x.scale:
                    r.preferred_area = round(r.target_area * x.scale, 2)
                if x.level is not None:
                    r.level = x.level
                if x.direction:
                    r.preferred_direction = x.direction
                if x.attached_bathroom:
                    r.attached_bathroom = True
                claimed.add(id(r))
                if mark not in (r.notes or ""):
                    r.notes = (notes + " " + (r.notes or "")).strip()
                elif x.attach_to and "Opens off" not in r.notes:
                    r.notes += notes[len(mark):]
                if x.count > 1:
                    reqs.append(extra := RoomRequirement(type=x.type, count=x.count - 1, level=x.level, notes=notes,
                                                preferred_direction=x.direction, attached_bathroom=x.attached_bathroom,
                                                needs_external_wall=x.type.is_outdoor))
                    claimed.add(id(extra))
                continue
            if x.scale and not x.label and not free and any(r.type is x.type for r in reqs):
                continue        # "make the kitchen bigger" twice: once is enough
            new = RoomRequirement(
                type=x.type, count=x.count, preferred_area=x.area, preferred_direction=x.direction,
                attached_bathroom=x.attached_bathroom, level=x.level, notes=notes, label=x.label,
                needs_external_wall=x.type.is_outdoor or x.type in {RoomType.STUDY, RoomType.GYM},
            )
            claimed.add(id(new))
            reqs.append(new)
        return reqs

    def _garden_share(self) -> float:
        area = self.plot_width * self.plot_depth
        if self.lawn_area and area:
            return round(min(0.7, self.lawn_area / area), 3)
        return round(self.lawn_share or 0.0, 3)

    def _coverage(self) -> float:
        """The ground the house may cover: the byelaw's limit, less the lawn
        and the pool the client asked for and room for the paths round them."""
        from aip.engines.experience.landscape import pool_area

        area = self.plot_width * self.plot_depth
        cap = self.max_ground_coverage if self.max_ground_coverage is not None else byelaw_limits(area)[0]
        pool = pool_area("" if self.pool == "none" else self.pool)
        garden = self._garden_share()
        if (garden or pool) and area:
            # Never below a quarter of the plot: a house still has to stand.
            # The lawn asked for is kept exactly; a pool keeps its deck too. No
            # other ground is held back: the rest of the plot is house.
            cap = min(cap, max(0.25, 1.0 - garden - pool / area - (0.08 if pool else 0.0)))
        return math.floor(cap * 1000) / 1000          # rounded down: the lawn is never shaved

    def to_brief(self) -> ClientBrief:
        """Expand into a full professional brief.

        The defaults matter: a client asking for "3 bedrooms" is also asking for
        a kitchen, a living room and circulation, and would be baffled to receive
        a house without them. Filling those in is what an architect does at the
        first meeting, so the platform does it too rather than producing a
        literal but useless reading of the request.
        """
        # Setbacks not stated follow the plot: a 20 x 30 ft plot cannot give
        # 2.5 m to the road and 1.2 m to each side and still hold a house.
        sb = auto_setbacks(self.plot_width * self.plot_depth,
                           (self.setback_front, self.setback_rear, self.setback_left, self.setback_right),
                           min(self.plot_width, self.plot_depth))
        # Width runs along the road and depth away from it, the way a plot is
        # named: "40 x 60, facing east" is 40 ft on the east road and 60 ft deep,
        # not a 60 ft frontage 40 ft deep. North and south roads run along x.
        along_x = Direction(self.road_direction).value not in ("E", "W")
        sx, sy = (self.plot_width, self.plot_depth) if along_x else (self.plot_depth, self.plot_width)
        site = Site(
            boundary=[
                Vec2(0.0, 0.0),
                Vec2(sx, 0.0),
                Vec2(sx, sy),
                Vec2(0.0, sy),
            ],
            north_angle=self.north_angle,
            latitude=self.latitude,
            longitude=self.longitude,
            locality=self.locality,
            road_directions=[self.road_direction],
            setback_front=sb[0],
            setback_rear=sb[1],
            setback_left=sb[2],
            setback_right=sb[3],
            max_far=self.max_far if self.max_far is not None else byelaw_limits(self.plot_width * self.plot_depth)[1],
            max_ground_coverage=self._coverage(),
            garden_share=self._garden_share(),
            pool="" if self.pool == "none" else self.pool,
        )

        requirements: list[RoomRequirement] = []
        if self.rooms:
            requirements = [
                RoomRequirement(
                    type=r.type,
                    count=r.count,
                    preferred_area=r.area,
                    preferred_direction=r.direction,
                    attached_bathroom=r.attached_bathroom,
                )
                for r in self.rooms
            ]
        else:
            requirements.append(RoomRequirement(type=RoomType.LIVING, priority=1.6))
            requirements.append(RoomRequirement(type=RoomType.KITCHEN, priority=1.5))
            if "no dining" not in self.amenities:
                requirements.append(RoomRequirement(type=RoomType.DINING, priority=1.2))
            if self.bedrooms >= 1:
                requirements.append(
                    RoomRequirement(
                        type=RoomType.MASTER_BEDROOM, attached_bathroom=True, priority=1.6
                    )
                )
            if self.bedrooms > 1:
                requirements.append(
                    RoomRequirement(type=RoomType.BEDROOM, count=self.bedrooms - 1, priority=1.3)
                )
            if self.bathrooms:
                requirements.append(
                    RoomRequirement(
                        type=RoomType.BATHROOM, count=self.bathrooms,
                        needs_daylight=False, priority=1.0,
                    )
                )
            requirements.append(
                RoomRequirement(type=RoomType.FOYER, needs_daylight=False, priority=0.6)
            )
            if "pooja" in self.amenities or "puja" in self.amenities or self.vastu.is_constraining:
                requirements.append(
                    RoomRequirement(
                        type=RoomType.PUJA, preferred_area=3.5,
                        needs_external_wall=False, priority=1.1 if "pooja" in self.amenities else 0.9,
                    )
                )
            if "study" in self.amenities:
                requirements.append(
                    RoomRequirement(
                        type=RoomType.STUDY, preferred_area=9.0, priority=1.0,
                    )
                )
            if "no utility" not in self.amenities:
                requirements.append(RoomRequirement(type=RoomType.UTILITY, priority=0.8))
            # A balcony is outdoors and a garage is a shed: neither needs a
            # window, and marking them as daylit made each one claim one of
            # the two lit positions in its band, squeezing a bedroom or the
            # kitchen into the dark middle.
            if "balcony" in self.amenities:
                requirements.append(
                    RoomRequirement(
                        type=RoomType.BALCONY, preferred_area=5.0, priority=0.9,
                        needs_daylight=False,
                    )
                )
            if "parking" in self.amenities or "garage" in self.amenities:
                requirements.append(
                    RoomRequirement(
                        type=RoomType.GARAGE, preferred_area=15.0, priority=1.1,
                        needs_daylight=False,
                    )
                )

        occupants: list[Occupant] = []
        if self.occupant_adults:
            occupants.append(Occupant(role="adult", count=self.occupant_adults))
        if self.occupant_children:
            occupants.append(Occupant(role="child", count=self.occupant_children))
        if self.occupant_elders:
            occupants.append(
                Occupant(role="elder", count=self.occupant_elders, needs_accessible=True)
            )

        materials = list(self.materials_liked)
        if self.finish_tier == "luxury" and "italian_marble" not in materials:
            materials.extend(["italian_marble", "engineered_teak", "low_e_glazing"])
        elif self.finish_tier == "premium" and "vitrified_tiles" not in materials:
            materials.extend(["vitrified_tiles", "granite", "teak_wood"])

        # Amenities the client named become rooms, marked as asked for so no
        # stage of the design lets go of them.
        named = {"courtyard": RoomType.COURTYARD, "verandah": RoomType.VERANDAH, "sit-out": RoomType.VERANDAH,
                 "gym": RoomType.GYM, "home theatre": RoomType.HOME_THEATRE, "theatre": RoomType.HOME_THEATRE,
                 "terrace": RoomType.TERRACE, "family lounge": RoomType.FAMILY, "library": RoomType.LIBRARY,
                 "servant room": RoomType.SERVANT, "store": RoomType.STORE}
        for am in self.amenities:
            kind = named.get(am.lower())
            if kind and not any(r.type is kind for r in requirements):
                requirements.append(RoomRequirement(type=kind, priority=1.0, notes="Requested by the client.",
                                                    needs_external_wall=kind is not RoomType.COURTYARD,
                                                    needs_daylight=kind not in (RoomType.STORE, RoomType.COURTYARD)))
        for r in requirements:
            if r.type in {RoomType.STUDY, RoomType.BALCONY, RoomType.GARAGE, RoomType.PUJA} and not r.notes:
                r.notes = "Requested by the client."
        requirements = self._apply_extras(requirements)
        # A car porch, a verandah and a courtyard open to the sky belong on the ground.
        for r in requirements:
            if r.type in {RoomType.GARAGE, RoomType.VERANDAH, RoomType.COURTYARD} and r.level is None and self.levels > 1:
                r.level = 0
        must_haves = list(self.must_haves)
        if self.kitchen_type and f"kitchen:{self.kitchen_type}" not in must_haves:
            must_haves.append(f"kitchen:{self.kitchen_type}")
        for am in self.amenities:
            if am not in must_haves:
                must_haves.append(am)

        metadata: dict[str, Any] = {
            "auto_extras": self.auto_extras,
            "finish_tier": self.finish_tier,
            "kitchen_type": self.kitchen_type,
            "amenities": self.amenities,
        }

        return ClientBrief(
            project_name=self.project_name,
            kind=self.kind,
            site=site,
            levels=self.levels,
            requirements=requirements,
            occupants=occupants,
            style=StylePreference(
                styles=self.styles or [DesignStyle.CONTEMPORARY],
                materials_liked=materials,
                free_text=self.notes,
            ),
            budget=Budget(amount=self.budget, currency=self.currency),
            vastu=self.vastu,
            accessibility=self.accessibility,
            must_haves=must_haves,
            free_text=self.notes,
            metadata=metadata,
        )


class DesignRequest(BaseModel):
    """Full-fidelity request used by the architect studio."""

    brief: ClientBrief | None = None
    simple: SimpleBriefRequest | None = None

    candidates: int = Field(default=3, ge=1, le=6)
    include_generative_critics: bool = True
    enable_refinement: bool = True
    seed: int | None = None
    project_id: str | None = None
    client_name: str = ""
    client_email: str = ""

    def resolved_brief(self) -> ClientBrief:
        if self.brief is not None:
            return self.brief
        if self.simple is not None:
            return self.simple.to_brief()
        raise ValueError("either 'brief' or 'simple' must be provided")


class DesignResponse(BaseModel):
    session_id: str
    project_id: str
    trace_id: str
    plan_ids: list[str] = Field(default_factory=list)

    #: The scheme the committee voted for.
    selected_candidate_id: str = ""
    #: The plan actually returned. Refinement and negotiation each produce a new
    #: revision, so this differs from `selected_candidate_id` whenever the design
    #: was improved after the vote - which is the normal case, not an anomaly.
    winner_plan_id: str = ""
    plan: dict[str, Any] = Field(default_factory=dict)
    consensus: dict[str, Any] = Field(default_factory=dict)
    vastu: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    #: Where the plan departs from the brief, in plain English: a floor added,
    #: a room left out, rooms drawn smaller, a house grown to fill its plot.
    advisories: list[str] = Field(default_factory=list)
    explanation: str = ""
    recommendations: list[str] = Field(default_factory=list)
    committee: list[dict[str, Any]] = Field(default_factory=list)
    voices: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)

    #: Manager-worker negotiation record: which constraints were open, which
    #: agent proposed what, and whether re-measurement accepted it.
    negotiation: dict[str, Any] | None = None
    negotiation_outcome: str = ""

    duration_ms: float = 0.0
    model_cost_usd: float = 0.0
    degraded: bool = False
    degraded_reason: str = ""
    drawing_urls: dict[str, str] = Field(default_factory=dict)
    #: Downloadable editable formats: DXF per level, GLB and OBJ.
    export_urls: dict[str, str] = Field(default_factory=dict)
    model_url: str = ""


class VastuRequest(BaseModel):
    plan_id: str | None = None
    plan: dict[str, Any] | None = None
    tradition_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    #: The plan this one was edited from: the report then says what the edit changed.
    compare_to: str | None = Field(default=None, max_length=64)


class CostRequest(BaseModel):
    plan_id: str | None = None
    plan: dict[str, Any] | None = None
    region: str | None = None
    finish_tier: str | None = None
    budget: float = Field(default=0.0, ge=0)
    currency: str = "INR"


class FeedbackRequest(BaseModel):
    project_id: str
    session_id: str = ""
    plan_id: str = ""
    accepted: bool
    rating: float | None = Field(default=None, ge=0.0, le=1.0)
    axis_ratings: dict[str, float] = Field(default_factory=dict)
    comment: str = Field(default="", max_length=4000)
    author_role: str = Field(default="architect", max_length=24)
    evidence_ids: list[str] = Field(default_factory=list)


class ActualsRequest(BaseModel):
    """Delivered outcome, used to calibrate the cost model."""

    project_id: str
    actual_cost: float = Field(gt=0)
    actual_duration_months: float | None = Field(default=None, gt=0)
    notes: str = Field(default="", max_length=2000)


class FirmCreateRequest(BaseModel):
    name: str = Field(max_length=200)
    slug: str = Field(max_length=80, pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")
    contact_email: str = Field(default="", max_length=200)
    region: str = Field(default="IN-TN", max_length=16)
    allowed_origins: list[str] = Field(default_factory=list)


class ApiKeyResponse(BaseModel):
    id: str
    #: Shown once at creation and never retrievable again.
    key: str = ""
    prefix: str
    scope: str
    label: str
    created_at: str


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    providers_configured: list[str] = Field(default_factory=list)
    degraded_mode: bool = False
    corpus: dict[str, Any] = Field(default_factory=dict)
    total_model_cost_usd: float = 0.0
