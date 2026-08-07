"""The building schema.

A `FloorPlan` is the single source of truth that every engine reads and writes.
The Vastu engine scores it, the cost engine takes quantities off it, the 3D
exporter extrudes it, and the interior engine paints it. Because they share one
model, a Vastu violation can name the exact wall to move, and moving that wall
immediately re-prices the project.

Coordinates are metres in a right-handed plan coordinate system with +Y toward
the top of the sheet. `Site.north_angle` records where true north actually is.
"""

from __future__ import annotations

import math
import uuid
from enum import Enum
from typing import Annotated, Any, Iterable

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, computed_field

from aip.domain.geometry import (
    BoundingBox,
    Direction,
    Vec2,
    aspect_ratio,
    bounding_box,
    centroid,
    compactness,
    direction_of,
    largest_inscribed_square,
    perimeter,
    point_in_polygon,
    polygon_area,
    shared_edge,
)


def _to_vec2(value: Any) -> Vec2:
    if isinstance(value, Vec2):
        return value
    if isinstance(value, dict):
        return Vec2(float(value["x"]), float(value["y"]))
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return Vec2(float(value[0]), float(value[1]))
    raise ValueError(f"cannot interpret {value!r} as a 2D point")


Point = Annotated[
    Vec2,
    BeforeValidator(_to_vec2),
    PlainSerializer(lambda v: [round(v.x, 4), round(v.y, 4)], return_type=list),
]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RoomType(str, Enum):
    """Programmatic room classification.

    Drives Vastu rules, daylight targets, furniture catalogues, finish schedules
    and cost rates, so the list is intentionally granular.
    """

    LIVING = "living"
    DRAWING = "drawing"
    FAMILY = "family"
    DINING = "dining"
    KITCHEN = "kitchen"
    PANTRY = "pantry"
    UTILITY = "utility"
    MASTER_BEDROOM = "master_bedroom"
    BEDROOM = "bedroom"
    GUEST_BEDROOM = "guest_bedroom"
    CHILDREN_BEDROOM = "children_bedroom"
    STUDY = "study"
    HOME_OFFICE = "home_office"
    BATHROOM = "bathroom"
    TOILET = "toilet"
    POWDER = "powder"
    PUJA = "puja"
    STORE = "store"
    WARDROBE = "wardrobe"
    STAIRCASE = "staircase"
    CORRIDOR = "corridor"
    FOYER = "foyer"
    LOBBY = "lobby"
    BALCONY = "balcony"
    VERANDAH = "verandah"
    TERRACE = "terrace"
    COURTYARD = "courtyard"
    GARAGE = "garage"
    SERVANT = "servant"
    GYM = "gym"
    HOME_THEATRE = "home_theatre"
    LIBRARY = "library"
    LAUNDRY = "laundry"
    SHAFT = "shaft"
    OTHER = "other"

    @property
    def is_wet(self) -> bool:
        return self in _WET_ROOMS

    @property
    def is_habitable(self) -> bool:
        """Habitable rooms carry statutory light/ventilation minimums."""
        return self in _HABITABLE

    @property
    def is_circulation(self) -> bool:
        return self in {RoomType.CORRIDOR, RoomType.FOYER, RoomType.LOBBY, RoomType.STAIRCASE}

    @property
    def is_outdoor(self) -> bool:
        return self in {
            RoomType.BALCONY, RoomType.TERRACE, RoomType.COURTYARD, RoomType.VERANDAH
        }

    @property
    def is_private(self) -> bool:
        return self in {
            RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
            RoomType.CHILDREN_BEDROOM, RoomType.BATHROOM, RoomType.TOILET, RoomType.WARDROBE,
        }

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


_WET_ROOMS = {
    RoomType.KITCHEN, RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER,
    RoomType.UTILITY, RoomType.LAUNDRY, RoomType.PANTRY,
}

_HABITABLE = {
    RoomType.LIVING, RoomType.DRAWING, RoomType.FAMILY, RoomType.DINING, RoomType.KITCHEN,
    RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM,
    RoomType.CHILDREN_BEDROOM, RoomType.STUDY, RoomType.HOME_OFFICE, RoomType.GYM,
    RoomType.LIBRARY, RoomType.HOME_THEATRE,
}


class WallKind(str, Enum):
    EXTERIOR = "exterior"
    INTERIOR = "interior"
    PARTITION = "partition"
    SHEAR = "shear"
    PARAPET = "parapet"
    RETAINING = "retaining"


class OpeningKind(str, Enum):
    DOOR = "door"
    MAIN_DOOR = "main_door"
    SLIDING_DOOR = "sliding_door"
    WINDOW = "window"
    FRENCH_WINDOW = "french_window"
    VENTILATOR = "ventilator"
    ARCH = "arch"
    SKYLIGHT = "skylight"

    @property
    def is_door(self) -> bool:
        return self in {OpeningKind.DOOR, OpeningKind.MAIN_DOOR, OpeningKind.SLIDING_DOOR, OpeningKind.ARCH}

    @property
    def is_glazed(self) -> bool:
        return self in {
            OpeningKind.WINDOW, OpeningKind.FRENCH_WINDOW,
            OpeningKind.VENTILATOR, OpeningKind.SKYLIGHT,
        }


class StructuralSystem(str, Enum):
    RCC_FRAME = "rcc_frame"
    LOAD_BEARING = "load_bearing"
    STEEL_FRAME = "steel_frame"
    COMPOSITE = "composite"
    PRECAST = "precast"


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


class Opening(BaseModel):
    """A door, window or ventilator hosted by a wall."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: _new_id("opn"))
    kind: OpeningKind = OpeningKind.WINDOW
    wall_id: str = ""
    position: float = Field(default=0.5, ge=0.0, le=1.0, description="Normalised offset along the wall")
    width: float = Field(default=1.2, gt=0)
    height: float = Field(default=1.5, gt=0)
    sill_height: float = Field(default=0.9, ge=0.0)
    connects: tuple[str, str] | None = Field(default=None, description="(room_a_id, room_b_id) for doors")
    glazing: str = "clear_single"
    notes: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area(self) -> float:
        return round(self.width * self.height, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def head_height(self) -> float:
        return round(self.sill_height + self.height, 4)


class Wall(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: _new_id("wal"))
    start: Point
    end: Point
    thickness: float = Field(default=0.23, gt=0)
    height: float = Field(default=3.0, gt=0)
    kind: WallKind = WallKind.INTERIOR
    material: str = "burnt_clay_brick"
    rooms: list[str] = Field(default_factory=list, description="Room ids this wall bounds")
    openings: list[Opening] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def length(self) -> float:
        return round(self.start.distance_to(self.end), 4)

    @property
    def direction_vector(self) -> Vec2:
        return (self.end - self.start).normalised()

    @property
    def midpoint(self) -> Vec2:
        return (self.start + self.end) * 0.5

    def point_at(self, t: float) -> Vec2:
        return self.start + (self.end - self.start) * max(0.0, min(1.0, t))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def opening_area(self) -> float:
        return round(sum(o.area for o in self.openings), 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def net_area(self) -> float:
        """Wall face area minus openings - the masonry quantity."""
        return round(max(0.0, self.length * self.height - self.opening_area), 4)

    def outward_normal(self, reference: Vec2) -> Vec2:
        """Unit normal pointing away from `reference` (usually the plan centre)."""
        normal = self.direction_vector.perpendicular()
        if (self.midpoint - reference).dot(normal) < 0:
            normal = normal * -1
        return normal


class Room(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: _new_id("rm"))
    name: str = ""
    type: RoomType = RoomType.OTHER
    polygon: list[Point] = Field(default_factory=list)
    level: int = 0
    ceiling_height: float = Field(default=3.0, gt=0)
    floor_finish: str = "vitrified_tile"
    wall_finish: str = "putty_emulsion"
    ceiling_finish: str = "pop_false_ceiling"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area(self) -> float:
        return round(polygon_area(self.polygon), 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def perimeter_length(self) -> float:
        return round(perimeter(self.polygon), 4)

    @property
    def centre(self) -> Vec2:
        return centroid(self.polygon)

    @property
    def bbox(self) -> BoundingBox:
        return bounding_box(self.polygon)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def aspect(self) -> float:
        return round(aspect_ratio(self.polygon), 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def compactness_score(self) -> float:
        return round(compactness(self.polygon), 3)

    @property
    def volume(self) -> float:
        return self.area * self.ceiling_height

    def contains(self, point: Vec2) -> bool:
        return point_in_polygon(point, self.polygon)

    def usable_square(self) -> float:
        return round(largest_inscribed_square(self.polygon), 3)

    def display_name(self) -> str:
        return self.name or self.type.label


class Staircase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: _new_id("stair"))
    polygon: list[Point] = Field(default_factory=list)
    from_level: int = 0
    to_level: int = 1
    kind: str = "dog_leg"           # straight | dog_leg | open_well | spiral
    tread: float = Field(default=0.28, gt=0)
    riser: float = Field(default=0.165, gt=0)
    width: float = Field(default=1.0, gt=0)
    rise_total: float = Field(default=3.15, gt=0)
    direction: str = "clockwise"    # ascent handedness; Vastu-relevant
    headroom: float = 2.1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def step_count(self) -> int:
        return max(1, round(self.rise_total / self.riser))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def going(self) -> float:
        return round((self.step_count - 1) * self.tread, 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def comfort_rule(self) -> float:
        """2R + T. Comfortable stairs land in roughly 0.58-0.65 m."""
        return round(2 * self.riser + self.tread, 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pitch_degrees(self) -> float:
        return round(math.degrees(math.atan2(self.riser, self.tread)), 2)


class ColumnGrid(BaseModel):
    """Structural grid. Column positions drive both buildability and cost."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: _new_id("grid"))
    system: StructuralSystem = StructuralSystem.RCC_FRAME
    x_spacings: list[float] = Field(default_factory=list)
    y_spacings: list[float] = Field(default_factory=list)
    origin: Point = Field(default_factory=lambda: Vec2(0.0, 0.0))
    column_size: tuple[float, float] = (0.23, 0.45)
    beam_depth: float = 0.45
    slab_thickness: float = 0.125

    @property
    def positions(self) -> list[Vec2]:
        xs, ys = [self.origin.x], [self.origin.y]
        for dx in self.x_spacings:
            xs.append(xs[-1] + dx)
        for dy in self.y_spacings:
            ys.append(ys[-1] + dy)
        return [Vec2(x, y) for x in xs for y in ys]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def column_count(self) -> int:
        return (len(self.x_spacings) + 1) * (len(self.y_spacings) + 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_span(self) -> float:
        return round(max([*self.x_spacings, *self.y_spacings], default=0.0), 3)


class Level(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    index: int = 0
    name: str = ""
    elevation: float = 0.0
    floor_to_floor: float = Field(default=3.15, gt=0)
    rooms: list[Room] = Field(default_factory=list)
    walls: list[Wall] = Field(default_factory=list)
    staircases: list[Staircase] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def built_area(self) -> float:
        return round(sum(r.area for r in self.rooms if not r.type.is_outdoor), 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def carpet_area(self) -> float:
        """Built area net of walls - the number clients actually care about."""
        wall_footprint = sum(w.length * w.thickness for w in self.walls) * 0.5
        return round(max(0.0, self.built_area - wall_footprint), 3)

    def display_name(self) -> str:
        if self.name:
            return self.name
        return "Ground Floor" if self.index == 0 else f"Floor {self.index}"

    def room_by_id(self, room_id: str) -> Room | None:
        return next((r for r in self.rooms if r.id == room_id), None)

    def rooms_of(self, *types: RoomType) -> list[Room]:
        wanted = set(types)
        return [r for r in self.rooms if r.type in wanted]

    def envelope(self) -> BoundingBox:
        pts = [p for r in self.rooms for p in r.polygon]
        return bounding_box(pts)

    def exterior_walls(self) -> list[Wall]:
        return [w for w in self.walls if w.kind is WallKind.EXTERIOR]

    def openings(self) -> list[Opening]:
        return [o for w in self.walls for o in w.openings]


class Site(BaseModel):
    """The plot, its orientation and its statutory constraints."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: _new_id("site"))
    boundary: list[Point] = Field(default_factory=list)
    north_angle: float = Field(
        default=0.0,
        description="Compass bearing of the plan's +Y axis, degrees clockwise from true north",
    )
    latitude: float = 13.0827
    longitude: float = 80.2707
    locality: str = "Chennai, Tamil Nadu"
    road_directions: list[Direction] = Field(default_factory=lambda: [Direction.N])
    setback_front: float = 3.0
    setback_rear: float = 1.5
    setback_left: float = 1.2
    setback_right: float = 1.2
    max_far: float = Field(default=1.5, description="Floor area ratio permitted")
    max_ground_coverage: float = Field(default=0.6, ge=0.0, le=1.0)
    max_height: float = 11.5
    slope_percent: float = 0.0
    soil_bearing_kn_m2: float = 150.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def plot_area(self) -> float:
        return round(polygon_area(self.boundary), 3)

    @property
    def centre(self) -> Vec2:
        return centroid(self.boundary)

    @property
    def bbox(self) -> BoundingBox:
        return bounding_box(self.boundary)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_built_area(self) -> float:
        return round(self.plot_area * self.max_far, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_footprint(self) -> float:
        return round(self.plot_area * self.max_ground_coverage, 2)

    def is_northern_hemisphere(self) -> bool:
        return self.latitude >= 0


class FloorPlan(BaseModel):
    """A complete, multi-level building proposal."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: _new_id("plan"))
    name: str = "Untitled Scheme"
    description: str = ""
    site: Site = Field(default_factory=Site)
    levels: list[Level] = Field(default_factory=list)
    column_grid: ColumnGrid | None = None
    structural_system: StructuralSystem = StructuralSystem.RCC_FRAME
    style: str = "contemporary"
    variant_of: str | None = None
    generation: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    # ---------------------------------------------------------------- views --

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_built_area(self) -> float:
        return round(sum(level.built_area for level in self.levels), 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_carpet_area(self) -> float:
        return round(sum(level.carpet_area for level in self.levels), 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def footprint_area(self) -> float:
        return round(self.levels[0].built_area, 3) if self.levels else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def achieved_far(self) -> float:
        if self.site.plot_area < 1e-6:
            return 0.0
        return round(self.total_built_area / self.site.plot_area, 4)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def building_height(self) -> float:
        return round(sum(level.floor_to_floor for level in self.levels), 3)

    @property
    def all_rooms(self) -> list[Room]:
        return [room for level in self.levels for room in level.rooms]

    @property
    def all_walls(self) -> list[Wall]:
        return [wall for level in self.levels for wall in level.walls]

    @property
    def all_openings(self) -> list[Opening]:
        return [o for w in self.all_walls for o in w.openings]

    @property
    def centre(self) -> Vec2:
        """Plan centroid - the origin for all directional (Vastu/solar) reasoning."""
        if self.site.boundary:
            return self.site.centre
        pts = [p for r in self.all_rooms for p in r.polygon]
        return centroid(pts) if pts else Vec2(0.0, 0.0)

    # ------------------------------------------------------------ lookups ---

    def level_at(self, index: int) -> Level | None:
        return next((lv for lv in self.levels if lv.index == index), None)

    def room_by_id(self, room_id: str) -> Room | None:
        return next((r for r in self.all_rooms if r.id == room_id), None)

    def wall_by_id(self, wall_id: str) -> Wall | None:
        return next((w for w in self.all_walls if w.id == wall_id), None)

    def rooms_of(self, *types: RoomType) -> list[Room]:
        wanted = set(types)
        return [r for r in self.all_rooms if r.type in wanted]

    def first_room_of(self, *types: RoomType) -> Room | None:
        rooms = self.rooms_of(*types)
        return max(rooms, key=lambda r: r.area) if rooms else None

    # ---------------------------------------------------------- semantics ---

    def direction_of_room(self, room: Room, centre_fraction: float = 0.18) -> Direction:
        """Compass zone a room occupies, honouring the site's north angle.

        `centre_fraction` sizes the Brahmasthan: the central portion of the plan
        that Vastu requires to remain unbuilt. It is expressed as a fraction of
        the plan's mean half-dimension so it scales with the building.
        """
        envelope = self.envelope()
        radius = centre_fraction * (envelope.width + envelope.height) / 4.0
        return direction_of(room.centre, self.centre, self.site.north_angle, centre_radius=radius)

    def envelope(self) -> BoundingBox:
        pts = [p for r in self.all_rooms for p in r.polygon]
        if not pts and self.site.boundary:
            return self.site.bbox
        return bounding_box(pts)

    def brahmasthan_polygon(self, fraction: float = 0.111) -> list[Vec2]:
        """The central zone (classically 1/9 of the plan area, 3x3 pada grid)."""
        env = self.envelope()
        side = math.sqrt(max(env.area, 0.0) * fraction)
        c = self.centre
        half = side / 2
        return [
            Vec2(c.x - half, c.y - half), Vec2(c.x + half, c.y - half),
            Vec2(c.x + half, c.y + half), Vec2(c.x - half, c.y + half),
        ]

    def adjacency(self, level_index: int = 0, tolerance: float = 0.06) -> dict[str, set[str]]:
        """Room adjacency graph derived from genuinely shared wall segments."""
        level = self.level_at(level_index)
        graph: dict[str, set[str]] = {}
        if level is None:
            return graph
        for room in level.rooms:
            graph[room.id] = set()
        rooms = level.rooms
        for i, a in enumerate(rooms):
            for b in rooms[i + 1 :]:
                if shared_edge(a.polygon, b.polygon, tolerance) is not None:
                    graph[a.id].add(b.id)
                    graph[b.id].add(a.id)
        return graph

    def connectivity(self, level_index: int = 0) -> dict[str, set[str]]:
        """Graph of rooms actually connected by a door (not merely adjacent)."""
        level = self.level_at(level_index)
        graph: dict[str, set[str]] = {}
        if level is None:
            return graph
        for room in level.rooms:
            graph[room.id] = set()
        for wall in level.walls:
            for opening in wall.openings:
                if opening.kind.is_door and opening.connects:
                    a, b = opening.connects
                    if a in graph and b in graph:
                        graph[a].add(b)
                        graph[b].add(a)
        return graph

    def total_glazing_area(self) -> float:
        return round(sum(o.area for o in self.all_openings if o.kind.is_glazed), 3)

    def room_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "id": r.id,
                "name": r.display_name(),
                "type": r.type.value,
                "level": r.level,
                "area_m2": r.area,
                "direction": self.direction_of_room(r).value,
            }
            for r in self.all_rooms
        ]

    def clone(self, **overrides: Any) -> FloorPlan:
        data = self.model_dump()
        data.update(overrides)
        data.pop("id", None)
        data["variant_of"] = self.id
        data["generation"] = self.generation + 1
        for key in (
            "total_built_area", "total_carpet_area", "footprint_area",
            "achieved_far", "building_height",
        ):
            data.pop(key, None)
        return FloorPlan.model_validate(data)


def make_level(index: int, rooms: Iterable[Room], walls: Iterable[Wall] | None = None, **kw: Any) -> Level:
    """Convenience constructor used by the generators and the test-suite."""
    return Level(index=index, rooms=list(rooms), walls=list(walls or []), **kw)
