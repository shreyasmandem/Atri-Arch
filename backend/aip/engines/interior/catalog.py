"""Furniture catalogue and style palettes.

Dimensions are real Indian-market furniture sizes in metres, with the clearance
each item needs to be usable. Clearance is what turns a furniture list into a
layout problem worth solving: a 1.8 m bed in a 3 m room fits geometrically and is
unusable in practice, and only the clearance data reveals that.

Palettes are expressed as concrete specifications - hex values, named materials,
colour temperatures - because they feed a bill of quantities and a render prompt,
not a mood board.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from aip.domain.brief import DesignStyle
from aip.domain.plan import RoomType


class Placement(str, Enum):
    """How an item wants to sit in a room."""

    AGAINST_WALL = "against_wall"      # back to a wall, e.g. a bed or sofa
    CORNER = "corner"
    CENTRE = "centre"                  # freestanding, e.g. a dining table
    FLOATING = "floating"              # anywhere with clearance, e.g. a rug
    COUNTER_RUN = "counter_run"        # continuous along a wall, e.g. kitchen
    BESIDE = "beside"                  # paired to a parent item


@dataclass(frozen=True, slots=True)
class FurnitureItem:
    """One catalogue entry."""

    id: str
    name: str
    width: float                       # m, along its own X
    depth: float                       # m
    height: float                      # m
    placement: Placement
    #: Clear space needed in front (and to the sides) to use the item.
    front_clearance: float = 0.6
    side_clearance: float = 0.0
    #: Indicative supply-and-fit cost in INR at standard specification.
    cost: float = 0.0
    essential: bool = False
    parent: str = ""                   # for BESIDE items
    tags: tuple[str, ...] = ()
    notes: str = ""

    @property
    def footprint(self) -> float:
        return self.width * self.depth

    @property
    def required_area(self) -> float:
        """Footprint plus the clearance that makes it usable."""
        return (self.width + 2 * self.side_clearance) * (self.depth + self.front_clearance)


def _i(*args, **kwargs) -> FurnitureItem:
    return FurnitureItem(*args, **kwargs)


#: Furniture required and optional, per room type, in placement priority order.
CATALOGUE: dict[RoomType, list[FurnitureItem]] = {
    RoomType.MASTER_BEDROOM: [
        _i("bed_king", "King bed", 1.83, 2.03, 1.1, Placement.AGAINST_WALL,
           front_clearance=0.75, side_clearance=0.75, cost=48_000, essential=True,
           tags=("sleeping",), notes="Head to the wall; 750 mm clear both sides."),
        _i("nightstand_l", "Nightstand (left)", 0.45, 0.4, 0.6, Placement.BESIDE,
           front_clearance=0.3, cost=7_500, parent="bed_king"),
        _i("nightstand_r", "Nightstand (right)", 0.45, 0.4, 0.6, Placement.BESIDE,
           front_clearance=0.3, cost=7_500, parent="bed_king"),
        _i("wardrobe_m", "Wardrobe", 2.4, 0.6, 2.1, Placement.AGAINST_WALL,
           front_clearance=0.75, cost=86_000, essential=True, tags=("storage",)),
        _i("dresser", "Dresser with mirror", 1.05, 0.45, 1.6, Placement.AGAINST_WALL,
           front_clearance=0.6, cost=22_000),
        _i("armchair", "Reading chair", 0.75, 0.8, 0.95, Placement.CORNER,
           front_clearance=0.45, cost=16_000),
    ],
    RoomType.BEDROOM: [
        _i("bed_queen", "Queen bed", 1.52, 2.03, 1.1, Placement.AGAINST_WALL,
           front_clearance=0.7, side_clearance=0.6, cost=34_000, essential=True, tags=("sleeping",)),
        _i("nightstand", "Nightstand", 0.45, 0.4, 0.6, Placement.BESIDE,
           front_clearance=0.3, cost=7_500, parent="bed_queen"),
        _i("wardrobe_s", "Wardrobe", 1.8, 0.6, 2.1, Placement.AGAINST_WALL,
           front_clearance=0.75, cost=64_000, essential=True, tags=("storage",)),
        _i("study_desk", "Study desk", 1.2, 0.6, 0.75, Placement.AGAINST_WALL,
           front_clearance=0.8, cost=15_000),
    ],
    RoomType.CHILDREN_BEDROOM: [
        _i("bed_single", "Single bed", 0.99, 1.9, 0.95, Placement.AGAINST_WALL,
           front_clearance=0.7, side_clearance=0.5, cost=22_000, essential=True),
        _i("wardrobe_c", "Wardrobe", 1.5, 0.6, 2.1, Placement.AGAINST_WALL,
           front_clearance=0.7, cost=52_000, essential=True),
        _i("study_desk_c", "Study desk", 1.05, 0.55, 0.72, Placement.AGAINST_WALL,
           front_clearance=0.8, cost=13_000, essential=True),
        _i("bookshelf", "Bookshelf", 0.8, 0.32, 1.8, Placement.AGAINST_WALL,
           front_clearance=0.55, cost=11_000),
    ],
    RoomType.GUEST_BEDROOM: [
        _i("bed_queen_g", "Queen bed", 1.52, 2.03, 1.1, Placement.AGAINST_WALL,
           front_clearance=0.7, side_clearance=0.6, cost=30_000, essential=True),
        _i("wardrobe_g", "Wardrobe", 1.5, 0.6, 2.1, Placement.AGAINST_WALL,
           front_clearance=0.7, cost=52_000, essential=True),
        _i("luggage_bench", "Luggage bench", 0.9, 0.4, 0.45, Placement.AGAINST_WALL,
           front_clearance=0.5, cost=8_000),
    ],
    RoomType.LIVING: [
        _i("sofa_3", "Three-seat sofa", 2.1, 0.9, 0.85, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=68_000, essential=True, tags=("seating",)),
        _i("coffee_table", "Coffee table", 1.1, 0.6, 0.42, Placement.CENTRE,
           front_clearance=0.45, cost=18_000, essential=True),
        _i("sofa_2", "Two-seat sofa", 1.5, 0.9, 0.85, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=48_000),
        _i("tv_unit", "Television unit", 1.8, 0.45, 0.55, Placement.AGAINST_WALL,
           front_clearance=2.4, cost=32_000, essential=True,
           notes="Needs 2.4 m viewing distance for a 55 inch screen."),
        _i("accent_chair", "Accent chair", 0.75, 0.78, 0.9, Placement.CORNER,
           front_clearance=0.45, cost=17_000),
        _i("console", "Console table", 1.2, 0.35, 0.8, Placement.AGAINST_WALL,
           front_clearance=0.5, cost=14_000),
    ],
    RoomType.DRAWING: [
        _i("sofa_formal", "Formal sofa", 2.1, 0.9, 0.9, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=86_000, essential=True),
        _i("centre_table", "Centre table", 1.2, 0.7, 0.45, Placement.CENTRE,
           front_clearance=0.45, cost=26_000, essential=True),
        _i("wing_chair_a", "Wing chair", 0.78, 0.8, 1.05, Placement.CORNER,
           front_clearance=0.5, cost=24_000),
        _i("wing_chair_b", "Wing chair", 0.78, 0.8, 1.05, Placement.CORNER,
           front_clearance=0.5, cost=24_000),
    ],
    RoomType.DINING: [
        _i("dining_6", "Six-seat dining table", 1.8, 0.9, 0.76, Placement.CENTRE,
           front_clearance=0.9, side_clearance=0.9, cost=52_000, essential=True,
           notes="900 mm clear all round for chairs to pull out."),
        _i("crockery_unit", "Crockery unit", 1.2, 0.45, 1.9, Placement.AGAINST_WALL,
           front_clearance=0.7, cost=38_000),
        _i("sideboard", "Sideboard", 1.4, 0.4, 0.85, Placement.AGAINST_WALL,
           front_clearance=0.6, cost=26_000),
    ],
    RoomType.KITCHEN: [
        _i("counter_run", "Base counter run", 3.0, 0.6, 0.9, Placement.COUNTER_RUN,
           front_clearance=1.05, cost=0, essential=True,
           notes="Priced in the modular kitchen package, not per item."),
        _i("tall_unit", "Tall unit / larder", 0.6, 0.6, 2.1, Placement.CORNER,
           front_clearance=0.9, cost=42_000),
        _i("fridge", "Refrigerator", 0.7, 0.7, 1.8, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=38_000, essential=True),
    ],
    RoomType.STUDY: [
        _i("desk_l", "Work desk", 1.5, 0.7, 0.75, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=24_000, essential=True,
           notes="Prefer a north window in front to avoid screen glare."),
        _i("task_chair", "Task chair", 0.62, 0.62, 1.1, Placement.BESIDE,
           front_clearance=0.4, cost=14_000, essential=True, parent="desk_l"),
        _i("shelving", "Shelving unit", 0.9, 0.35, 2.0, Placement.AGAINST_WALL,
           front_clearance=0.6, cost=19_000),
    ],
    RoomType.HOME_OFFICE: [
        _i("desk_office", "Work desk", 1.5, 0.7, 0.75, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=26_000, essential=True),
        _i("task_chair_o", "Ergonomic chair", 0.66, 0.66, 1.15, Placement.BESIDE,
           front_clearance=0.4, cost=22_000, essential=True, parent="desk_office"),
        _i("storage_office", "Filing storage", 0.8, 0.45, 1.4, Placement.AGAINST_WALL,
           front_clearance=0.6, cost=16_000),
    ],
    RoomType.PUJA: [
        _i("mandir", "Mandir unit", 0.9, 0.45, 1.8, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=45_000, essential=True,
           notes="Faces west so the worshipper faces east."),
    ],
    RoomType.BATHROOM: [
        _i("wc", "Water closet", 0.38, 0.68, 0.78, Placement.AGAINST_WALL,
           front_clearance=0.6, side_clearance=0.23, cost=18_000, essential=True),
        _i("basin", "Wash basin with counter", 0.9, 0.5, 0.85, Placement.AGAINST_WALL,
           front_clearance=0.55, cost=16_000, essential=True),
        _i("shower", "Shower enclosure", 0.9, 0.9, 2.0, Placement.CORNER,
           front_clearance=0.4, cost=28_000, essential=True),
    ],
    RoomType.TOILET: [
        _i("wc_only", "Water closet", 0.38, 0.68, 0.78, Placement.AGAINST_WALL,
           front_clearance=0.6, side_clearance=0.23, cost=15_000, essential=True),
        _i("basin_small", "Corner basin", 0.5, 0.4, 0.85, Placement.CORNER,
           front_clearance=0.5, cost=9_000, essential=True),
    ],
    RoomType.FOYER: [
        _i("shoe_unit", "Shoe cabinet", 1.0, 0.35, 1.1, Placement.AGAINST_WALL,
           front_clearance=0.7, cost=18_000, essential=True),
        _i("mirror_console", "Console with mirror", 0.9, 0.32, 0.85, Placement.AGAINST_WALL,
           front_clearance=0.6, cost=14_000),
    ],
    RoomType.FAMILY: [
        _i("sectional", "Sectional sofa", 2.6, 1.6, 0.85, Placement.CORNER,
           front_clearance=0.9, cost=92_000, essential=True),
        _i("family_tv", "Media unit", 1.8, 0.45, 0.55, Placement.AGAINST_WALL,
           front_clearance=2.4, cost=30_000, essential=True),
        _i("family_table", "Coffee table", 1.0, 0.6, 0.4, Placement.CENTRE,
           front_clearance=0.45, cost=16_000),
    ],
    RoomType.HOME_THEATRE: [
        _i("recliner_row", "Recliner row", 2.4, 1.0, 1.1, Placement.CENTRE,
           front_clearance=1.2, cost=145_000, essential=True),
        _i("screen_wall", "Screen and acoustic wall", 2.6, 0.25, 1.8, Placement.AGAINST_WALL,
           front_clearance=3.0, cost=180_000, essential=True),
    ],
    RoomType.UTILITY: [
        _i("washer", "Washing machine", 0.6, 0.6, 0.85, Placement.AGAINST_WALL,
           front_clearance=0.75, cost=32_000, essential=True),
        _i("utility_sink", "Utility sink", 0.6, 0.5, 0.9, Placement.AGAINST_WALL,
           front_clearance=0.7, cost=9_000),
    ],
    RoomType.LIBRARY: [
        _i("bookwall", "Bookshelf wall", 2.4, 0.35, 2.2, Placement.AGAINST_WALL,
           front_clearance=0.9, cost=78_000, essential=True),
        _i("reading_chair", "Reading chair and lamp", 0.85, 0.9, 1.0, Placement.CORNER,
           front_clearance=0.5, cost=28_000, essential=True),
    ],
    RoomType.GYM: [
        _i("treadmill", "Treadmill", 0.9, 1.9, 1.4, Placement.AGAINST_WALL,
           front_clearance=0.6, cost=85_000, essential=True),
        _i("weight_rack", "Weight rack", 1.2, 0.6, 1.8, Placement.AGAINST_WALL,
           front_clearance=1.0, cost=45_000),
        _i("mat_area", "Floor mat area", 2.0, 1.5, 0.02, Placement.FLOATING,
           front_clearance=0.0, cost=12_000),
    ],
}


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StylePalette:
    """Concrete finish specification for a style."""

    style: DesignStyle
    wall: str
    wall_accent: str
    ceiling: str
    floor: str
    floor_material: str
    joinery: str
    joinery_material: str
    upholstery: str
    metal: str
    accent: str
    lighting_kelvin: int
    lighting_strategy: str
    materials: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    character: str = ""

    def swatches(self) -> list[dict[str, str]]:
        return [
            {"role": "Wall", "hex": self.wall},
            {"role": "Accent wall", "hex": self.wall_accent},
            {"role": "Ceiling", "hex": self.ceiling},
            {"role": "Floor", "hex": self.floor},
            {"role": "Joinery", "hex": self.joinery},
            {"role": "Upholstery", "hex": self.upholstery},
            {"role": "Metal", "hex": self.metal},
            {"role": "Accent", "hex": self.accent},
        ]


PALETTES: dict[DesignStyle, StylePalette] = {
    DesignStyle.TROPICAL_MODERN: StylePalette(
        DesignStyle.TROPICAL_MODERN,
        wall="#F4F1EA", wall_accent="#8C9A8E", ceiling="#FBFAF7",
        floor="#8A8F86", floor_material="Kota stone, honed",
        joinery="#7A5A3C", joinery_material="Teak veneer, matte",
        upholstery="#C9C2B2", metal="#3A3A38", accent="#C2603A",
        lighting_kelvin=3000, lighting_strategy="Warm cove lighting with wide overhangs; minimal downlights",
        materials=("kota stone", "teak", "lime plaster", "cane", "board-marked concrete"),
        avoid=("high-gloss laminate", "dark carpet"),
        character="Airy, shaded, breeze-led. Surfaces that improve as they weather.",
    ),
    DesignStyle.MODERN_MINIMAL: StylePalette(
        DesignStyle.MODERN_MINIMAL,
        wall="#FAFAF8", wall_accent="#E8E6E1", ceiling="#FFFFFF",
        floor="#D8D4CE", floor_material="Large-format vitrified tile, matte",
        joinery="#EDEBE7", joinery_material="Handleless matte lacquer",
        upholstery="#BFBAB2", metal="#1C1C1C", accent="#2E2E2E",
        lighting_kelvin=3500, lighting_strategy="Entirely concealed: cove, linear recessed, wall-wash",
        materials=("matte lacquer", "microtopping", "honed stone"),
        avoid=("visible hardware", "ornate mouldings", "open shelving"),
        character="Reduction to essentials. Demands high build quality; flaws have nowhere to hide.",
    ),
    DesignStyle.CONTEMPORARY: StylePalette(
        DesignStyle.CONTEMPORARY,
        wall="#F2F0EC", wall_accent="#5A6570", ceiling="#FCFBF9",
        floor="#C4BFB6", floor_material="Vitrified tile, 800x800",
        joinery="#8A6A4A", joinery_material="Walnut veneer with matte PU",
        upholstery="#9AA3AB", metal="#B8925A", accent="#C77B4E",
        lighting_kelvin=3000, lighting_strategy="Layered: cove, spots on art, table lamps",
        materials=("vitrified tile", "walnut veneer", "brass", "textured paint"),
        avoid=("cluttered pattern", "cold white light"),
        character="Clean lines with warmth. The default for Indian urban residential.",
    ),
    DesignStyle.SCANDINAVIAN: StylePalette(
        DesignStyle.SCANDINAVIAN,
        wall="#FBFAF8", wall_accent="#DCE3E0", ceiling="#FFFFFF",
        floor="#D7C3A5", floor_material="Light oak engineered board",
        joinery="#E8DFD2", joinery_material="Pale oak, oiled",
        upholstery="#C7CFCB", metal="#9A9A96", accent="#7A9A88",
        lighting_kelvin=2700, lighting_strategy="Many low-level warm sources; no single ceiling fixture",
        materials=("pale oak", "wool", "linen", "matte ceramic"),
        avoid=("dark timber", "heavy ornament"),
        character="Light, soft and functional. Built for long dark evenings.",
    ),
    DesignStyle.JAPANDI: StylePalette(
        DesignStyle.JAPANDI,
        wall="#F0EDE6", wall_accent="#C8BEB0", ceiling="#FAF8F4",
        floor="#B99C74", floor_material="Ash engineered board, brushed",
        joinery="#3E3A34", joinery_material="Stained ash, ebonised detail",
        upholstery="#B6AE9E", metal="#2B2B2B", accent="#8A7355",
        lighting_kelvin=2700, lighting_strategy="Warm, indirect, paper-diffused; deep shadow retained",
        materials=("ash", "paper", "linen", "clay plaster", "stone"),
        avoid=("gloss", "chrome", "visible clutter"),
        character="Scandinavian restraint with Japanese proportion. Negative space is the material.",
    ),
    DesignStyle.INDUSTRIAL: StylePalette(
        DesignStyle.INDUSTRIAL,
        wall="#B8B4AE", wall_accent="#7A4A3A", ceiling="#9A9691",
        floor="#8E8B86", floor_material="Polished concrete, waxed",
        joinery="#4A4744", joinery_material="Blackened steel and reclaimed timber",
        upholstery="#6B5A4A", metal="#2A2A2A", accent="#C05A2A",
        lighting_kelvin=2700, lighting_strategy="Track spots and cage pendants; fittings are the ornament",
        materials=("exposed concrete", "brick", "blackened steel", "leather"),
        avoid=("false ceiling", "pastel colour"),
        character="Structure as finish. Needs ceiling heights above 3.3 m to read as deliberate.",
    ),
    DesignStyle.TRADITIONAL_INDIAN: StylePalette(
        DesignStyle.TRADITIONAL_INDIAN,
        wall="#F5EDDC", wall_accent="#9C3A2E", ceiling="#FAF4E8",
        floor="#A8613C", floor_material="Red oxide or Athangudi tile",
        joinery="#5A3A22", joinery_material="Seasoned teak with carved detail",
        upholstery="#C8963C", metal="#B08D3A", accent="#1E4D5A",
        lighting_kelvin=2700, lighting_strategy="Warm pools of light; brass fixtures; no flat ambient wash",
        materials=("teak", "brass", "red oxide", "handmade tile", "lime plaster"),
        avoid=("cool white light", "high-gloss surfaces"),
        character="Ornament concentrated at thresholds, columns and ceilings.",
    ),
    DesignStyle.BIOPHILIC: StylePalette(
        DesignStyle.BIOPHILIC,
        wall="#F3F1E8", wall_accent="#6E8564", ceiling="#FAFAF5",
        floor="#9A8A70", floor_material="Timber-look tile or cork",
        joinery="#7A6A50", joinery_material="Rattan-fronted oak",
        upholstery="#A8B49A", metal="#6E6A60", accent="#4A6E4A",
        lighting_kelvin=3000, lighting_strategy="Daylight-first; circadian tuning where artificial light is used",
        materials=("rattan", "cork", "lime plaster", "living plants", "unfilled travertine"),
        avoid=("synthetic laminate", "sealed windows"),
        character="Every habitable room sees planting. Daylight is the primary light source.",
    ),
}

_DEFAULT_PALETTE = PALETTES[DesignStyle.CONTEMPORARY]


def palette_for(style: DesignStyle) -> StylePalette:
    """Palette for a style, falling back to contemporary for unmapped ones."""
    return PALETTES.get(style, _DEFAULT_PALETTE)


def items_for(room_type: RoomType) -> list[FurnitureItem]:
    return CATALOGUE.get(room_type, [])


def catalogue_summary() -> dict[str, object]:
    return {
        "room_types_covered": len(CATALOGUE),
        "total_items": sum(len(v) for v in CATALOGUE.values()),
        "styles_with_palettes": len(PALETTES),
    }
