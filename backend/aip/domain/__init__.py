"""Domain model: geometry primitives, building schema, and the client brief.

Everything downstream - architecture generation, Vastu reasoning, quantity
takeoff, 3D export - reads and writes these types. Keeping one authoritative
representation is what allows a Vastu violation to be traced to a wall, and that
wall to a line item in the bill of quantities.
"""

from aip.domain.brief import (
    Budget,
    ClientBrief,
    Occupant,
    RoomRequirement,
    StylePreference,
)
from aip.domain.geometry import (
    BoundingBox,
    Direction,
    Polygon,
    Vec2,
    bearing_to_direction,
    centroid,
    convex_hull,
    direction_of,
    perimeter,
    point_in_polygon,
    polygon_area,
    rectangle,
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
    Site,
    Staircase,
    Wall,
    WallKind,
)

__all__ = [
    "BoundingBox",
    "Budget",
    "ClientBrief",
    "ColumnGrid",
    "Direction",
    "FloorPlan",
    "Level",
    "Occupant",
    "Opening",
    "OpeningKind",
    "Polygon",
    "Room",
    "RoomRequirement",
    "RoomType",
    "Site",
    "Staircase",
    "StylePreference",
    "Vec2",
    "Wall",
    "WallKind",
    "bearing_to_direction",
    "centroid",
    "convex_hull",
    "direction_of",
    "perimeter",
    "point_in_polygon",
    "polygon_area",
    "rectangle",
    "shrink_polygon",
]
