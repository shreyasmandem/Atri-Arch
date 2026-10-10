"""Phase 4 - Interior design.

Generates furniture layouts, palettes, material and lighting specifications for
each room, and prices the result.

The layout is solved geometrically rather than generated as an image. That is
the difference between a picture of a room and a room: this output carries real
dimensions, real clearances, a real furniture schedule and a real cost, and it
can be checked against the door swings and window positions in the plan. Image
generation is offered on top, as presentation - not as the source of truth.
"""

from aip.engines.interior.catalog import (
    CATALOGUE,
    FurnitureItem,
    StylePalette,
    palette_for,
)
from aip.engines.interior.engine import (
    InteriorScheme,
    PlacedFurniture,
    RoomInterior,
    design_interior,
    design_room,
)

__all__ = [
    "CATALOGUE",
    "FurnitureItem",
    "InteriorScheme",
    "PlacedFurniture",
    "RoomInterior",
    "StylePalette",
    "design_interior",
    "design_room",
    "palette_for",
]
