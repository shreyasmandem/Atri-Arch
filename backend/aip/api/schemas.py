"""Request and response models for the HTTP API.

Kept separate from the domain model on purpose. The domain `ClientBrief` is rich
and expects an architect's vocabulary; a client filling in a form on a practice's
website does not have that vocabulary. `SimpleBriefRequest` is the reduced,
forgiving shape the embedded widget posts, and it expands into a full brief with
sensible professional defaults.
"""

from __future__ import annotations

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


class RoomRequest(BaseModel):
    type: RoomType
    count: int = Field(default=1, ge=1, le=20)
    area: float | None = Field(default=None, gt=0, le=500)
    direction: Direction | None = None
    attached_bathroom: bool = False


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

    styles: list[DesignStyle] = Field(default_factory=lambda: [DesignStyle.CONTEMPORARY])
    materials_liked: list[str] = Field(default_factory=list)
    budget: float = Field(default=0.0, ge=0)
    currency: str = Field(default="INR", max_length=8)

    vastu: VastuStance = VastuStance.BALANCED
    accessibility: AccessibilityLevel = AccessibilityLevel.BASIC

    occupant_adults: int = Field(default=2, ge=0, le=20)
    occupant_children: int = Field(default=0, ge=0, le=20)
    occupant_elders: int = Field(default=0, ge=0, le=20)

    must_haves: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=4000)

    max_far: float = Field(default=1.5, gt=0, le=15)
    max_ground_coverage: float = Field(default=0.6, gt=0, le=1)
    setback_front: float = Field(default=3.0, ge=0, le=30)
    setback_rear: float = Field(default=1.5, ge=0, le=30)
    setback_left: float = Field(default=1.2, ge=0, le=30)
    setback_right: float = Field(default=1.2, ge=0, le=30)

    @field_validator("must_haves", "materials_liked")
    @classmethod
    def _trim(cls, value: list[str]) -> list[str]:
        return [item.strip()[:200] for item in value if item.strip()][:20]

    def to_brief(self) -> ClientBrief:
        """Expand into a full professional brief.

        The defaults matter: a client asking for "3 bedrooms" is also asking for
        a kitchen, a living room and circulation, and would be baffled to receive
        a house without them. Filling those in is what an architect does at the
        first meeting, so the platform does it too rather than producing a
        literal but useless reading of the request.
        """
        site = Site(
            boundary=[
                Vec2(0.0, 0.0),
                Vec2(self.plot_width, 0.0),
                Vec2(self.plot_width, self.plot_depth),
                Vec2(0.0, self.plot_depth),
            ],
            north_angle=self.north_angle,
            latitude=self.latitude,
            longitude=self.longitude,
            locality=self.locality,
            road_directions=[self.road_direction],
            setback_front=self.setback_front,
            setback_rear=self.setback_rear,
            setback_left=self.setback_left,
            setback_right=self.setback_right,
            max_far=self.max_far,
            max_ground_coverage=self.max_ground_coverage,
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
            if self.vastu.is_constraining:
                requirements.append(
                    RoomRequirement(
                        type=RoomType.PUJA, preferred_area=3.5,
                        needs_external_wall=False, priority=0.9,
                    )
                )
            requirements.append(RoomRequirement(type=RoomType.UTILITY, priority=0.7))

        occupants: list[Occupant] = []
        if self.occupant_adults:
            occupants.append(Occupant(role="adult", count=self.occupant_adults))
        if self.occupant_children:
            occupants.append(Occupant(role="child", count=self.occupant_children))
        if self.occupant_elders:
            occupants.append(
                Occupant(role="elder", count=self.occupant_elders, needs_accessible=True)
            )

        return ClientBrief(
            project_name=self.project_name,
            kind=self.kind,
            site=site,
            levels=self.levels,
            requirements=requirements,
            occupants=occupants,
            style=StylePreference(
                styles=self.styles or [DesignStyle.CONTEMPORARY],
                materials_liked=self.materials_liked,
                free_text=self.notes,
            ),
            budget=Budget(amount=self.budget, currency=self.currency),
            vastu=self.vastu,
            accessibility=self.accessibility,
            must_haves=self.must_haves,
            free_text=self.notes,
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
    winner_plan_id: str = ""
    plan: dict[str, Any] = Field(default_factory=dict)
    consensus: dict[str, Any] = Field(default_factory=dict)
    vastu: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    explanation: str = ""
    recommendations: list[str] = Field(default_factory=list)
    committee: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: float = 0.0
    model_cost_usd: float = 0.0
    degraded: bool = False
    degraded_reason: str = ""
    drawing_urls: dict[str, str] = Field(default_factory=dict)
    model_url: str = ""


class VastuRequest(BaseModel):
    plan_id: str | None = None
    plan: dict[str, Any] | None = None
    tradition_weight: float = Field(default=0.5, ge=0.0, le=1.0)


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
