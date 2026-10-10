"""The client brief.

This is the input to the whole platform. An architect (or a client, through the
embedded widget) describes what they want; every downstream agent reads this
object. It is deliberately expressive - preferences captured here are what the
RAG layer matches against past projects, and what the critics score designs
against.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from aip.domain.geometry import Direction
from aip.domain.plan import RoomType, Site


class ProjectKind(str, Enum):
    RESIDENCE = "residence"
    APARTMENT = "apartment"
    VILLA = "villa"
    DUPLEX = "duplex"
    FARMHOUSE = "farmhouse"
    OFFICE = "office"
    RETAIL = "retail"
    RESTAURANT = "restaurant"
    CLINIC = "clinic"
    SCHOOL = "school"
    HOTEL = "hotel"
    MIXED_USE = "mixed_use"
    RENOVATION = "renovation"
    INTERIOR_ONLY = "interior_only"


class DesignStyle(str, Enum):
    """Styles the interior and architecture engines can reason about.

    The engine understands a style as a bundle of retrievable evidence - palette,
    materials, proportion rules, lighting temperature, characteristic furniture -
    rather than as a prompt keyword, which is why the list is explicit.
    """

    CONTEMPORARY = "contemporary"
    MODERN_MINIMAL = "modern_minimal"
    SCANDINAVIAN = "scandinavian"
    INDUSTRIAL = "industrial"
    MID_CENTURY_MODERN = "mid_century_modern"
    TRADITIONAL_INDIAN = "traditional_indian"
    KERALA_VERNACULAR = "kerala_vernacular"
    CHETTINAD = "chettinad"
    INDO_SARACENIC = "indo_saracenic"
    RAJASTHANI_HAVELI = "rajasthani_haveli"
    JAPANDI = "japandi"
    WABI_SABI = "wabi_sabi"
    BOHEMIAN = "bohemian"
    ART_DECO = "art_deco"
    BRUTALIST = "brutalist"
    MEDITERRANEAN = "mediterranean"
    COASTAL = "coastal"
    RUSTIC_FARMHOUSE = "rustic_farmhouse"
    LUXURY_CLASSICAL = "luxury_classical"
    BIOPHILIC = "biophilic"
    TROPICAL_MODERN = "tropical_modern"
    TRANSITIONAL = "transitional"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class VastuStance(str, Enum):
    """How strictly the client wants Vastu applied.

    This is the user-facing control over the traditional/modern reconciliation
    that the Vastu engine performs.
    """

    IGNORE = "ignore"
    ADVISORY = "advisory"       # report violations, do not constrain generation
    BALANCED = "balanced"       # trade Vastu off against daylight, cost, function
    STRICT = "strict"           # Vastu is a hard constraint where physically possible
    ORTHODOX = "orthodox"       # classical texts win every conflict

    @property
    def tradition_weight(self) -> float:
        return {
            VastuStance.IGNORE: 0.0,
            VastuStance.ADVISORY: 0.25,
            VastuStance.BALANCED: 0.5,
            VastuStance.STRICT: 0.8,
            VastuStance.ORTHODOX: 1.0,
        }[self]

    @property
    def is_constraining(self) -> bool:
        return self in {VastuStance.BALANCED, VastuStance.STRICT, VastuStance.ORTHODOX}


class AccessibilityLevel(str, Enum):
    NONE = "none"
    BASIC = "basic"                  # step-free entry, wider main door
    WHEELCHAIR = "wheelchair"        # full turning circles, accessible WC
    UNIVERSAL = "universal"          # ageing-in-place throughout


class Occupant(BaseModel):
    """Who lives here. Drives room count, privacy zoning and accessibility."""

    role: str = "adult"              # adult | child | teen | elder | guest | staff
    count: int = Field(default=1, ge=0)
    age_band: str = ""
    needs_accessible: bool = False
    works_from_home: bool = False
    notes: str = ""


class RoomRequirement(BaseModel):
    """One line of the accommodation schedule."""

    type: RoomType
    count: int = Field(default=1, ge=1)
    min_area: float | None = Field(default=None, gt=0, description="m2 per instance")
    preferred_area: float | None = Field(default=None, gt=0)
    preferred_direction: Direction | None = None
    must_be_adjacent_to: list[RoomType] = Field(default_factory=list)
    must_not_be_adjacent_to: list[RoomType] = Field(default_factory=list)
    needs_external_wall: bool = True
    needs_daylight: bool = True
    attached_bathroom: bool = False
    level: int | None = Field(default=None, description="Pin to a level, or None to let the optimiser decide")
    priority: float = Field(default=1.0, ge=0.0, le=2.0)
    notes: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def target_area(self) -> float:
        if self.preferred_area:
            return self.preferred_area
        if self.min_area:
            return self.min_area * 1.15
        return DEFAULT_ROOM_AREAS.get(self.type, 12.0)


# Sensible Indian residential defaults (m2), used when a brief omits sizes.
DEFAULT_ROOM_AREAS: dict[RoomType, float] = {
    RoomType.LIVING: 22.0, RoomType.DRAWING: 18.0, RoomType.FAMILY: 16.0,
    RoomType.DINING: 14.0, RoomType.KITCHEN: 11.0, RoomType.PANTRY: 4.0,
    RoomType.UTILITY: 5.0, RoomType.MASTER_BEDROOM: 18.0, RoomType.BEDROOM: 13.0,
    RoomType.GUEST_BEDROOM: 12.0, RoomType.CHILDREN_BEDROOM: 12.0,
    RoomType.STUDY: 9.0, RoomType.HOME_OFFICE: 10.0, RoomType.BATHROOM: 5.0,
    RoomType.TOILET: 2.6, RoomType.POWDER: 2.0, RoomType.PUJA: 3.5,
    RoomType.STORE: 4.0, RoomType.WARDROBE: 5.0, RoomType.STAIRCASE: 9.0,
    RoomType.CORRIDOR: 6.0, RoomType.FOYER: 5.0, RoomType.LOBBY: 8.0,
    RoomType.BALCONY: 6.0, RoomType.VERANDAH: 9.0, RoomType.TERRACE: 15.0,
    RoomType.COURTYARD: 12.0, RoomType.GARAGE: 18.0, RoomType.SERVANT: 8.0,
    RoomType.GYM: 14.0, RoomType.HOME_THEATRE: 18.0, RoomType.LIBRARY: 12.0,
    RoomType.LAUNDRY: 5.0, RoomType.SHAFT: 1.2, RoomType.OTHER: 10.0,
}

# Statutory minimum areas, National Building Code of India 2016 Part 3.
NBC_MIN_AREAS: dict[RoomType, float] = {
    RoomType.MASTER_BEDROOM: 9.5, RoomType.BEDROOM: 9.5, RoomType.GUEST_BEDROOM: 9.5,
    RoomType.CHILDREN_BEDROOM: 9.5, RoomType.LIVING: 9.5, RoomType.KITCHEN: 5.5,
    RoomType.BATHROOM: 1.8, RoomType.TOILET: 1.1, RoomType.STUDY: 7.5,
}

# NBC 2016 minimum clear dimension (m) for habitable rooms.
NBC_MIN_WIDTH: dict[RoomType, float] = {
    RoomType.MASTER_BEDROOM: 2.4, RoomType.BEDROOM: 2.4, RoomType.GUEST_BEDROOM: 2.4,
    RoomType.CHILDREN_BEDROOM: 2.4, RoomType.LIVING: 2.4, RoomType.KITCHEN: 1.8,
    RoomType.DINING: 2.4, RoomType.STUDY: 2.4, RoomType.HOME_OFFICE: 2.4,
    RoomType.BATHROOM: 1.0, RoomType.TOILET: 0.9,
}


class Budget(BaseModel):
    amount: float = Field(default=0.0, ge=0)
    currency: str = "INR"
    includes_interiors: bool = True
    includes_furniture: bool = False
    contingency_percent: float = Field(default=7.5, ge=0, le=30)
    flexibility_percent: float = Field(default=10.0, ge=0, le=100)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ceiling(self) -> float:
        return round(self.amount * (1 + self.flexibility_percent / 100), 2)

    @property
    def is_specified(self) -> bool:
        return self.amount > 0


class StylePreference(BaseModel):
    """Free-form aesthetic intent, resolved by the RAG layer into concrete specs."""

    styles: list[DesignStyle] = Field(default_factory=lambda: [DesignStyle.CONTEMPORARY])
    palette_keywords: list[str] = Field(default_factory=list)
    materials_liked: list[str] = Field(default_factory=list)
    materials_disliked: list[str] = Field(default_factory=list)
    reference_image_urls: list[str] = Field(default_factory=list)
    free_text: str = ""
    formality: float = Field(default=0.5, ge=0.0, le=1.0, description="0 casual - 1 formal")
    warmth: float = Field(default=0.5, ge=0.0, le=1.0, description="0 cool - 1 warm")
    ornamentation: float = Field(default=0.35, ge=0.0, le=1.0, description="0 minimal - 1 ornate")
    openness: float = Field(default=0.6, ge=0.0, le=1.0, description="0 cellular - 1 open plan")

    @property
    def primary(self) -> DesignStyle:
        return self.styles[0] if self.styles else DesignStyle.CONTEMPORARY


class ClientBrief(BaseModel):
    """Everything the platform needs to design for a specific client."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = ""
    project_name: str = "New Project"
    kind: ProjectKind = ProjectKind.RESIDENCE
    site: Site = Field(default_factory=Site)
    levels: int = Field(default=1, ge=1, le=12)

    requirements: list[RoomRequirement] = Field(default_factory=list)
    occupants: list[Occupant] = Field(default_factory=list)
    style: StylePreference = Field(default_factory=StylePreference)
    budget: Budget = Field(default_factory=Budget)

    vastu: VastuStance = VastuStance.BALANCED
    accessibility: AccessibilityLevel = AccessibilityLevel.BASIC

    # Optimisation priorities, normalised before use. These are the weights the
    # critic ensemble applies when it scores competing designs.
    priority_daylight: float = Field(default=1.0, ge=0.0, le=2.0)
    priority_ventilation: float = Field(default=1.0, ge=0.0, le=2.0)
    priority_privacy: float = Field(default=1.0, ge=0.0, le=2.0)
    priority_circulation: float = Field(default=1.0, ge=0.0, le=2.0)
    priority_cost: float = Field(default=1.0, ge=0.0, le=2.0)
    priority_vastu: float = Field(default=1.0, ge=0.0, le=2.0)

    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    free_text: str = ""
    locale: str = "en-IN"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("requirements")
    @classmethod
    def _dedupe(cls, value: list[RoomRequirement]) -> list[RoomRequirement]:
        merged: dict[RoomType, RoomRequirement] = {}
        for req in value:
            existing = merged.get(req.type)
            if existing is None:
                merged[req.type] = req
            else:
                existing.count += req.count
        return list(merged.values())

    # ------------------------------------------------------------- derived --

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_rooms(self) -> int:
        return sum(r.count for r in self.requirements)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def target_built_area(self) -> float:
        """Programme area plus a circulation and wall allowance."""
        programme = sum(r.target_area * r.count for r in self.requirements)
        return round(programme * 1.22, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def occupant_count(self) -> int:
        return sum(o.count for o in self.occupants)

    @property
    def needs_accessibility(self) -> bool:
        return self.accessibility is not AccessibilityLevel.NONE or any(
            o.needs_accessible for o in self.occupants
        )

    @property
    def tradition_weight(self) -> float:
        return self.vastu.tradition_weight

    def priority_weights(self) -> dict[str, float]:
        """Normalised objective weights consumed by the optimiser and critics."""
        raw = {
            "daylight": self.priority_daylight,
            "ventilation": self.priority_ventilation,
            "privacy": self.priority_privacy,
            "circulation": self.priority_circulation,
            "cost": self.priority_cost,
            "vastu": self.priority_vastu if self.vastu.is_constraining else 0.0,
        }
        total = sum(raw.values()) or 1.0
        return {k: round(v / total, 4) for k, v in raw.items()}

    def requirement_for(self, room_type: RoomType) -> RoomRequirement | None:
        return next((r for r in self.requirements if r.type is room_type), None)

    def expanded_requirements(self) -> list[RoomRequirement]:
        """One entry per room instance, so the layout engine can place them."""
        out: list[RoomRequirement] = []
        for req in self.requirements:
            for _ in range(req.count):
                out.append(req.model_copy(update={"count": 1}))
        return out

    def summary_text(self) -> str:
        """Compact natural-language digest used as LLM context."""
        rooms = ", ".join(
            f"{r.count}x {r.type.label}" for r in sorted(self.requirements, key=lambda r: -r.priority)
        )
        parts = [
            f"{self.kind.value.replace('_', ' ')} named '{self.project_name}'",
            f"plot {self.site.plot_area:.0f} m2 in {self.site.locality}",
            f"{self.levels} level(s), target built-up {self.target_built_area:.0f} m2",
            f"accommodation: {rooms or 'unspecified'}",
            f"style: {', '.join(s.label for s in self.style.styles)}",
            f"vastu stance: {self.vastu.value}",
        ]
        if self.budget.is_specified:
            parts.append(f"budget {self.budget.amount:,.0f} {self.budget.currency}")
        if self.occupants:
            who = ", ".join(f"{o.count} {o.role}" for o in self.occupants)
            parts.append(f"occupants: {who}")
        if self.must_haves:
            parts.append("must have: " + "; ".join(self.must_haves))
        if self.constraints:
            parts.append("constraints: " + "; ".join(self.constraints))
        if self.free_text:
            parts.append(f"client note: {self.free_text}")
        return ". ".join(parts) + "."


def default_residence_brief(plot_width: float = 12.0, plot_depth: float = 18.0) -> ClientBrief:
    """A realistic 3BHK brief. Used by demos, tests and the onboarding tour."""
    from aip.domain.geometry import Vec2

    site = Site(
        boundary=[
            Vec2(0, 0), Vec2(plot_width, 0),
            Vec2(plot_width, plot_depth), Vec2(0, plot_depth),
        ],
        north_angle=0.0,
        road_directions=[Direction.N],
    )
    return ClientBrief(
        project_name="Sample 3BHK Residence",
        kind=ProjectKind.RESIDENCE,
        site=site,
        levels=1,
        requirements=[
            RoomRequirement(type=RoomType.LIVING, preferred_area=22.0, priority=1.6),
            RoomRequirement(type=RoomType.DINING, preferred_area=13.0, priority=1.2),
            RoomRequirement(type=RoomType.KITCHEN, preferred_area=11.0, priority=1.5),
            RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=18.0, attached_bathroom=True, priority=1.6),
            RoomRequirement(type=RoomType.BEDROOM, count=2, preferred_area=13.0, priority=1.3),
            RoomRequirement(type=RoomType.BATHROOM, count=2, preferred_area=5.0, needs_daylight=False, priority=1.0),
            RoomRequirement(type=RoomType.PUJA, preferred_area=3.5, needs_external_wall=False, priority=0.9),
            RoomRequirement(type=RoomType.UTILITY, preferred_area=5.0, priority=0.7),
            RoomRequirement(type=RoomType.FOYER, preferred_area=5.0, needs_daylight=False, priority=0.6),
        ],
        occupants=[
            Occupant(role="adult", count=2, works_from_home=True),
            Occupant(role="child", count=1),
            Occupant(role="elder", count=1, needs_accessible=True),
        ],
        style=StylePreference(
            styles=[DesignStyle.TROPICAL_MODERN, DesignStyle.CONTEMPORARY],
            materials_liked=["kota stone", "teak", "exposed concrete"],
            free_text="Warm, airy, lots of cross ventilation; low maintenance.",
        ),
        budget=Budget(amount=6_500_000, currency="INR", includes_interiors=True),
        vastu=VastuStance.BALANCED,
        accessibility=AccessibilityLevel.BASIC,
        must_haves=["north-facing entrance", "cross ventilation in every bedroom"],
    )
