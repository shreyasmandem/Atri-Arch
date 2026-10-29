"""Room-by-room interior editing: what a room can hold, in which colours, where.

The solver in `engine` furnishes every room on its own. A client then makes a
room theirs: a diwan in place of the sofa, a jhoola by the window, the bed
turned to face east, the wardrobe in walnut, a Kota floor and a terracotta
accent wall. This module is the vocabulary for that - the furniture an Indian
home actually has, at the sizes it is sold in, the finishes it comes in - and
the check that turns what the client did into something the model can build.

An edited room is stored on the plan as a list of placed items and a set of
finishes (`plan.metadata["interior_edits"][room_id]`); the engine then uses it
in place of its own layout, so the drawings, the schedule, the cost and the 3D
model all show the room the client made.
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from aip.domain.plan import FloorPlan, Room, RoomType
from aip.engines.interior.catalog import CATALOGUE, FurnitureItem, Placement

T = RoomType
_BEDS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM}
_SITTING = {T.LIVING, T.DRAWING, T.FAMILY}
_ANY_DRY = _BEDS | _SITTING | {T.DINING, T.STUDY, T.HOME_OFFICE, T.LIBRARY, T.FOYER, T.HOME_THEATRE, T.GYM}
_OUTSIDE = {T.BALCONY, T.TERRACE, T.VERANDAH, T.COURTYARD}
_WET = {T.BATHROOM, T.TOILET, T.POWDER}


def _i(*args, **kwargs) -> FurnitureItem:
    return FurnitureItem(*args, **kwargs)


#: What a client may add to a room beyond what the solver chose, by group, and
#: the rooms each belongs in. Sizes are the ones Indian furniture is sold in
#: (a 4-seat dining table about 1.2 x 0.75 m, a 6-seat 1.6-1.8 x 0.9 m; a queen
#: bed 1.52 x 1.98 m, a king 1.83 x 1.98 m; a sofa 0.8-0.9 m deep).
EXTRAS: list[tuple[str, frozenset[RoomType], FurnitureItem]] = [
    # Seating
    ("Seating", frozenset(_SITTING | {T.VERANDAH}), _i("sofa_l", "L-shaped sofa", 2.4, 1.6, 0.85, Placement.CORNER,
                                                      front_clearance=0.9, cost=82_000)),
    ("Seating", frozenset(_SITTING | _BEDS | {T.STUDY}), _i("diwan", "Diwan with bolsters", 1.9, 0.8, 0.45,
                                                           Placement.AGAINST_WALL, front_clearance=0.6, cost=28_000)),
    ("Seating", frozenset(_SITTING), _i("sofa_bed", "Sofa-cum-bed", 1.9, 0.9, 0.85, Placement.AGAINST_WALL,
                                        front_clearance=1.2, cost=42_000)),
    ("Seating", frozenset(_SITTING | {T.VERANDAH, T.BALCONY, T.COURTYARD, T.TERRACE}),
     _i("jhoola", "Jhoola (swing)", 1.5, 0.8, 2.4, Placement.FLOATING, front_clearance=1.0, cost=38_000)),
    ("Seating", frozenset(_SITTING | _BEDS), _i("baithak", "Floor seating (baithak)", 2.0, 0.8, 0.25,
                                                Placement.AGAINST_WALL, front_clearance=0.6, cost=12_000)),
    ("Seating", frozenset(_ANY_DRY | _OUTSIDE), _i("accent_chair_x", "Accent chair", 0.75, 0.78, 0.9, Placement.CORNER,
                                                    front_clearance=0.45, cost=17_000)),
    ("Seating", frozenset(_SITTING | _BEDS), _i("bean_bag", "Bean bag", 0.85, 0.85, 0.7, Placement.FLOATING,
                                                front_clearance=0.3, cost=5_500)),
    ("Seating", frozenset(_ANY_DRY), _i("pouffe", "Pouffe / moodha", 0.45, 0.45, 0.42, Placement.FLOATING,
                                        front_clearance=0.2, cost=3_500)),
    ("Seating", frozenset(_BEDS | {T.FOYER} | _SITTING), _i("bench", "Upholstered bench", 1.2, 0.4, 0.45,
                                                            Placement.AGAINST_WALL, front_clearance=0.5, cost=9_000)),
    ("Seating", frozenset(_OUTSIDE), _i("outdoor_set", "Cane chairs and table", 1.6, 1.2, 0.8, Placement.FLOATING,
                                        front_clearance=0.4, cost=22_000)),
    # Beds
    ("Beds", frozenset(_BEDS), _i("bed_storage", "Queen bed with hydraulic storage", 1.52, 1.98, 1.1,
                                  Placement.AGAINST_WALL, front_clearance=0.75, side_clearance=0.6, cost=42_000)),
    ("Beds", frozenset(_BEDS), _i("bed_king_x", "King bed", 1.83, 1.98, 1.1, Placement.AGAINST_WALL,
                                  front_clearance=0.75, side_clearance=0.7, cost=48_000)),
    ("Beds", frozenset(_BEDS), _i("bed_palang", "Carved teak palang", 1.83, 2.1, 1.4, Placement.AGAINST_WALL,
                                  front_clearance=0.75, side_clearance=0.7, cost=95_000)),
    ("Beds", frozenset({T.CHILDREN_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM}),
     _i("bed_bunk", "Bunk bed", 0.99, 1.98, 1.7, Placement.AGAINST_WALL, front_clearance=0.7, cost=38_000)),
    ("Beds", frozenset(_BEDS), _i("bed_single_x", "Single bed", 0.99, 1.9, 0.95, Placement.AGAINST_WALL,
                                  front_clearance=0.7, side_clearance=0.4, cost=22_000)),
    # Tables
    ("Tables", frozenset({T.DINING} | _SITTING), _i("dining_4", "Four-seat dining table", 1.2, 0.75, 0.76,
                                                    Placement.CENTRE, front_clearance=0.9, side_clearance=0.9, cost=32_000)),
    ("Tables", frozenset({T.DINING}), _i("dining_8", "Eight-seat dining table", 2.4, 1.0, 0.76, Placement.CENTRE,
                                         front_clearance=0.9, side_clearance=0.9, cost=78_000)),
    ("Tables", frozenset({T.DINING} | _SITTING), _i("dining_round", "Round dining table", 1.2, 1.2, 0.76,
                                                    Placement.CENTRE, front_clearance=0.9, side_clearance=0.9, cost=36_000)),
    ("Tables", frozenset(_SITTING | _BEDS), _i("coffee_table_x", "Coffee table", 1.1, 0.6, 0.42, Placement.CENTRE,
                                               front_clearance=0.45, cost=16_000)),
    ("Tables", frozenset(_ANY_DRY | _OUTSIDE), _i("side_table", "Side table", 0.45, 0.45, 0.55, Placement.FLOATING,
                                                  front_clearance=0.2, cost=6_500)),
    ("Tables", frozenset(_BEDS | {T.STUDY, T.HOME_OFFICE, T.LIBRARY, T.FAMILY}),
     _i("study_desk_x", "Study desk and chair", 1.2, 0.6, 0.75, Placement.AGAINST_WALL, front_clearance=0.8, cost=19_000)),
    ("Tables", frozenset(_BEDS), _i("dressing_table", "Dressing table with mirror", 1.0, 0.45, 1.6,
                                    Placement.AGAINST_WALL, front_clearance=0.6, cost=21_000)),
    # Storage
    ("Storage", frozenset(_BEDS), _i("wardrobe_sliding", "Sliding wardrobe", 2.4, 0.65, 2.4, Placement.AGAINST_WALL,
                                     front_clearance=0.3, cost=98_000)),
    ("Storage", frozenset(_BEDS), _i("wardrobe_hinged", "Hinged wardrobe", 1.8, 0.6, 2.1, Placement.AGAINST_WALL,
                                     front_clearance=0.75, cost=64_000)),
    ("Storage", frozenset(_SITTING | _BEDS | {T.STUDY, T.LIBRARY, T.HOME_OFFICE}),
     _i("bookshelf_x", "Bookshelf", 0.9, 0.32, 1.9, Placement.AGAINST_WALL, front_clearance=0.55, cost=13_000)),
    ("Storage", frozenset({T.DINING} | _SITTING), _i("crockery_x", "Crockery unit", 1.2, 0.45, 1.9,
                                                     Placement.AGAINST_WALL, front_clearance=0.7, cost=38_000)),
    ("Storage", frozenset(_SITTING | {T.DINING, T.FOYER}), _i("console_x", "Console table", 1.2, 0.35, 0.8,
                                                              Placement.AGAINST_WALL, front_clearance=0.5, cost=14_000)),
    ("Storage", frozenset({T.FOYER} | _SITTING), _i("shoe_bench", "Shoe rack with seat", 1.0, 0.38, 0.5,
                                                    Placement.AGAINST_WALL, front_clearance=0.6, cost=11_000)),
    ("Storage", frozenset(_SITTING | {T.FAMILY, T.HOME_THEATRE}), _i("tv_unit_x", "Television unit", 1.8, 0.45, 0.55,
                                                                     Placement.AGAINST_WALL, front_clearance=2.4, cost=32_000)),
    ("Storage", frozenset(_SITTING | {T.DINING}), _i("bar_cabinet", "Bar cabinet", 1.0, 0.45, 1.6,
                                                     Placement.AGAINST_WALL, front_clearance=0.6, cost=34_000)),
    # Puja
    ("Puja", frozenset({T.PUJA}), _i("mandir_floor", "Teak mandir (floor)", 0.9, 0.45, 1.8, Placement.AGAINST_WALL,
                                     front_clearance=0.9, cost=45_000)),
    ("Puja", frozenset({T.PUJA} | _SITTING | {T.DINING, T.KITCHEN, T.FOYER}),
     _i("mandir_wall", "Wall-mounted mandir", 0.75, 0.35, 0.9, Placement.AGAINST_WALL, front_clearance=0.9, cost=24_000)),
    ("Puja", frozenset({T.PUJA}), _i("diya_stand", "Brass diya stand", 0.3, 0.3, 1.2, Placement.CORNER,
                                     front_clearance=0.3, cost=6_000)),
    # Kitchen
    ("Kitchen", frozenset({T.KITCHEN}), _i("counter_l", "L-shaped modular kitchen", 2.4, 2.1, 0.9,
                                           Placement.CORNER, front_clearance=1.05, cost=0)),
    ("Kitchen", frozenset({T.KITCHEN}), _i("counter_parallel", "Parallel counter", 2.4, 0.6, 0.9,
                                           Placement.AGAINST_WALL, front_clearance=1.05, cost=0)),
    ("Kitchen", frozenset({T.KITCHEN, T.DINING}), _i("breakfast_counter", "Breakfast counter and stools", 1.2, 0.5,
                                                     0.9, Placement.FLOATING, front_clearance=0.6, cost=22_000)),
    ("Kitchen", frozenset({T.KITCHEN, T.UTILITY}), _i("fridge_x", "Refrigerator", 0.7, 0.7, 1.8,
                                                      Placement.AGAINST_WALL, front_clearance=0.9, cost=38_000)),
    ("Kitchen", frozenset({T.KITCHEN, T.UTILITY}), _i("tall_unit_x", "Tall larder unit", 0.6, 0.6, 2.1,
                                                      Placement.CORNER, front_clearance=0.9, cost=42_000)),
    # Appliances
    ("Appliances", frozenset({T.KITCHEN, T.DINING}), _i("microwave", "Microwave oven", 0.5, 0.4, 0.3,
                                                       Placement.AGAINST_WALL, front_clearance=0.5, cost=12_000)),
    ("Appliances", frozenset({T.KITCHEN}), _i("chimney", "Kitchen chimney (over the hob)", 0.9, 0.5, 0.6,
                                              Placement.AGAINST_WALL, front_clearance=0.0, cost=22_000)),
    ("Appliances", frozenset({T.KITCHEN, T.DINING, T.UTILITY}), _i("purifier", "Water purifier (RO)", 0.3, 0.15, 0.5,
                                                                   Placement.AGAINST_WALL, front_clearance=0.3, cost=15_000)),
    ("Appliances", frozenset({T.KITCHEN, T.UTILITY}), _i("dishwasher", "Dishwasher", 0.6, 0.6, 0.85,
                                                         Placement.AGAINST_WALL, front_clearance=0.7, cost=38_000)),
    ("Appliances", frozenset({T.UTILITY, T.BATHROOM, T.KITCHEN, T.BALCONY}),
     _i("washer_front", "Front-load washing machine", 0.6, 0.6, 0.85, Placement.AGAINST_WALL, front_clearance=0.7,
        cost=35_000)),
    ("Appliances", frozenset(_ANY_DRY - {T.FOYER, T.GYM}), _i("ac_split", "Split air conditioner", 0.95, 0.22, 0.3,
                                                              Placement.AGAINST_WALL, front_clearance=0.0, cost=42_000)),
    ("Appliances", frozenset(_SITTING | _BEDS | {T.HOME_THEATRE, T.STUDY}),
     _i("tv_wall", "Wall-mounted television", 1.23, 0.08, 0.71, Placement.AGAINST_WALL, front_clearance=0.0,
        cost=55_000)),
    ("Appliances", frozenset(_WET | {T.UTILITY}), _i("geyser", "Water heater (geyser)", 0.4, 0.35, 0.6,
                                                     Placement.AGAINST_WALL, front_clearance=0.0, cost=11_000)),
    # Everyday pieces of a modern Indian home
    ("Storage", frozenset(_SITTING | {T.HOME_THEATRE}), _i("tv_floating", "Floating TV unit, fluted backdrop and LED strip",
                                                           2.4, 0.4, 2.4, Placement.AGAINST_WALL, front_clearance=2.4,
                                                           cost=85_000)),
    ("Tables", frozenset({T.STUDY, T.HOME_OFFICE} | _BEDS | {T.FAMILY}),
     _i("standing_desk", "Standing desk with two monitors (work from home)", 1.4, 0.7, 1.1, Placement.AGAINST_WALL,
        front_clearance=0.9, cost=48_000)),
    ("Storage", frozenset(_BEDS), _i("wardrobe_glass", "Tinted glass sliding wardrobe with sensor lights", 2.4, 0.65,
                                     2.4, Placement.AGAINST_WALL, front_clearance=0.3, cost=165_000)),
    ("Bath", frozenset({T.BATHROOM}), _i("shower_glass", "Glass shower cubicle, matte black frame", 1.0, 1.0, 2.1,
                                         Placement.CORNER, front_clearance=0.6, cost=38_000)),
    ("Puja", frozenset({T.PUJA} | _SITTING | {T.DINING, T.FOYER}), _i("puja_corian", "CNC-carved Corian puja unit with bells",
                                                                     1.0, 0.45, 2.1, Placement.AGAINST_WALL,
                                                                     front_clearance=0.9, cost=72_000)),
    ("Decor", frozenset(_OUTSIDE), _i("deck_turf", "Deck tiles with a turf patch", 2.0, 1.5, 0.03, Placement.FLOATING,
                                      front_clearance=0.0, cost=16_000)),
    ("Appliances", frozenset(_ANY_DRY), _i("robot_vacuum", "Robot vacuum with auto-empty dock", 0.35, 0.45, 0.4,
                                           Placement.AGAINST_WALL, front_clearance=0.3, cost=45_000)),
    ("Appliances", frozenset(_ANY_DRY), _i("air_purifier", "HEPA air purifier", 0.3, 0.3, 0.65, Placement.CORNER,
                                           front_clearance=0.3, cost=18_000)),
    ("Lighting", frozenset(_ANY_DRY), _i("drapes_sheer", "Floor-to-ceiling sheer linen drapes", 2.4, 0.12, 2.8,
                                         Placement.AGAINST_WALL, front_clearance=0.0, cost=14_000)),
    ("Lighting", frozenset(_ANY_DRY | {T.KITCHEN}), _i("blinds_venetian", "Wooden venetian blinds", 1.5, 0.06, 1.5,
                                                        Placement.AGAINST_WALL, front_clearance=0.0, cost=9_000)),
    # More furniture
    ("Storage", frozenset(_BEDS | {T.STUDY}),
     _i("chest_drawers", "Chest of drawers", 0.9, 0.45, 1.0, Placement.AGAINST_WALL, front_clearance=0.6, cost=24_000)),
    ("Storage", frozenset({T.CHILDREN_BEDROOM, T.BEDROOM, T.FAMILY}), _i("toy_chest", "Toy chest", 0.8, 0.4, 0.5,
                                                                        Placement.AGAINST_WALL, front_clearance=0.5,
                                                                        cost=8_000)),
    ("Storage", frozenset(_SITTING | {T.DINING, T.FOYER}), _i("jaali_screen", "Jaali room divider", 1.5, 0.05, 1.9,
                                                              Placement.FLOATING, front_clearance=0.3, cost=26_000)),
    ("Storage", frozenset({T.STUDY, T.HOME_OFFICE}), _i("filing_cabinet", "Filing cabinet", 0.45, 0.6, 1.3,
                                                        Placement.AGAINST_WALL, front_clearance=0.7, cost=14_000)),
    ("Storage", frozenset({T.UTILITY, T.BALCONY, T.TERRACE}), _i("drying_rack", "Clothes drying stand", 1.6, 0.55, 1.0,
                                                                 Placement.FLOATING, front_clearance=0.4, cost=4_000)),
    ("Beds", frozenset(_BEDS), _i("cradle", "Baby cradle (palna)", 0.9, 0.5, 0.9, Placement.FLOATING,
                                  front_clearance=0.5, cost=14_000)),
    ("Beds", frozenset(_BEDS), _i("crib", "Baby cot", 1.25, 0.7, 0.95, Placement.AGAINST_WALL, front_clearance=0.6,
                                  cost=18_000)),
    ("Seating", frozenset(_SITTING | _BEDS), _i("recliner_single", "Recliner", 0.9, 0.95, 1.0, Placement.CORNER,
                                                front_clearance=0.8, cost=36_000)),
    ("Seating", frozenset(_SITTING | _BEDS | {T.BALCONY, T.VERANDAH, T.TERRACE}),
     _i("swing_chair", "Egg swing chair (cane)", 0.9, 0.9, 1.9, Placement.CORNER, front_clearance=0.4, cost=16_000)),
    ("Seating", frozenset(_BEDS | _SITTING), _i("ottoman_storage", "Storage ottoman", 0.8, 0.45, 0.45,
                                                Placement.FLOATING, front_clearance=0.3, cost=9_000)),
    ("Seating", frozenset({T.STUDY, T.HOME_OFFICE} | _BEDS), _i("office_chair", "Office chair", 0.6, 0.6, 1.1,
                                                                Placement.FLOATING, front_clearance=0.3, cost=12_000)),
    ("Seating", frozenset({T.DINING, T.KITCHEN}), _i("bench_dining", "Dining bench", 1.5, 0.4, 0.45,
                                                     Placement.AGAINST_WALL, front_clearance=0.4, cost=12_000)),
    ("Seating", frozenset(_OUTSIDE), _i("garden_bench", "Garden bench", 1.4, 0.6, 0.85, Placement.AGAINST_WALL,
                                        front_clearance=0.5, cost=14_000)),
    ("Tables", frozenset(_SITTING | _BEDS | {T.PUJA, T.VERANDAH}), _i("chowki", "Low chowki table", 0.6, 0.6, 0.35,
                                                                      Placement.FLOATING, front_clearance=0.3,
                                                                      cost=7_000)),
    # Lighting
    ("Lighting", frozenset(_SITTING | {T.DINING, T.FOYER}), _i("chandelier", "Brass chandelier", 0.8, 0.8, 0.8,
                                                               Placement.CENTRE, front_clearance=0.0, cost=32_000)),
    ("Lighting", frozenset(_SITTING | _BEDS | {T.DINING, T.KITCHEN, T.STUDY}),
     _i("pendant_light", "Pendant lamp", 0.6, 0.6, 0.7, Placement.FLOATING, front_clearance=0.0, cost=9_000)),
    ("Lighting", frozenset(_ANY_DRY | {T.PUJA}), _i("candles", "Brass candle stand", 0.35, 0.3, 0.45, Placement.CORNER,
                                                    front_clearance=0.1, cost=4_500)),
    # Bath
    ("Bath", frozenset({T.BATHROOM}), _i("bathtub", "Bathtub", 1.5, 0.75, 0.55, Placement.AGAINST_WALL,
                                         front_clearance=0.6, cost=45_000)),
    ("Bath", frozenset(_WET), _i("mirror_cabinet", "Mirror cabinet", 0.6, 0.15, 0.7, Placement.AGAINST_WALL,
                                 front_clearance=0.0, cost=9_000)),
    # Bath
    ("Bath", frozenset(_WET), _i("basin_vanity", "Vanity with basin", 0.9, 0.5, 0.85, Placement.AGAINST_WALL,
                                 front_clearance=0.7, cost=28_000)),
    ("Bath", frozenset(_WET), _i("bath_cabinet", "Bathroom storage cabinet", 0.45, 0.3, 1.6, Placement.AGAINST_WALL,
                                 front_clearance=0.5, cost=12_000)),
    ("Bath", frozenset(_WET), _i("towel_ladder", "Towel ladder", 0.5, 0.3, 1.5, Placement.AGAINST_WALL,
                                 front_clearance=0.3, cost=4_500)),
    # Decor
    ("Decor", frozenset(_ANY_DRY | _OUTSIDE), _i("rug_dhurrie", "Dhurrie rug", 2.0, 1.4, 0.01, Placement.FLOATING,
                                                 front_clearance=0.0, cost=9_000)),
    ("Decor", frozenset(_ANY_DRY | _OUTSIDE | {T.PUJA}), _i("rug_round", "Round rug", 1.5, 1.5, 0.01, Placement.FLOATING,
                                                            front_clearance=0.0, cost=7_000)),
    ("Decor", frozenset(_ANY_DRY | _OUTSIDE), _i("plant_tall", "Tall plant in planter", 0.5, 0.5, 1.6, Placement.CORNER,
                                                 front_clearance=0.1, cost=4_500)),
    ("Decor", frozenset(_ANY_DRY | _OUTSIDE | _WET), _i("plant_small", "Potted plant", 0.35, 0.35, 0.7, Placement.CORNER,
                                                 front_clearance=0.1, cost=1_800)),
    ("Decor", frozenset(_ANY_DRY | _OUTSIDE), _i("basket", "Wicker basket", 0.45, 0.45, 0.4, Placement.CORNER,
                                                 front_clearance=0.1, cost=2_500)),
    ("Decor", frozenset(_ANY_DRY), _i("floor_lamp", "Floor lamp", 0.4, 0.4, 1.6, Placement.CORNER,
                                      front_clearance=0.1, cost=8_500)),
    ("Decor", frozenset(_ANY_DRY | {T.PUJA}), _i("brass_lamp", "Brass deepam lamp", 0.35, 0.35, 1.3, Placement.CORNER,
                                                 front_clearance=0.1, cost=7_500)),
    ("Decor", frozenset(_ANY_DRY), _i("mirror_full", "Full-length mirror", 0.6, 0.05, 1.7, Placement.AGAINST_WALL,
                                      front_clearance=0.6, cost=7_000)),
    ("Decor", frozenset(_ANY_DRY), _i("wall_art", "Wall art (Madhubani / Pichwai)", 1.2, 0.04, 0.9,
                                      Placement.AGAINST_WALL, front_clearance=0.0, cost=12_000)),
    ("Decor", frozenset(_ANY_DRY), _i("wall_shelf", "Floating wall shelf", 1.2, 0.25, 0.3, Placement.AGAINST_WALL,
                                      front_clearance=0.0, cost=4_000)),
    ("Decor", frozenset(_ANY_DRY | _OUTSIDE), _i("urli", "Brass urli with flowers", 0.6, 0.6, 0.3, Placement.FLOATING,
                                                 front_clearance=0.2, cost=6_500)),
    ("Decor", frozenset(_SITTING | {T.FOYER, T.DINING, T.STUDY}), _i("aquarium", "Aquarium on a stand", 1.0, 0.4, 1.3,
                                                                     Placement.AGAINST_WALL, front_clearance=0.6,
                                                                     cost=28_000)),
    ("Decor", frozenset(_SITTING | {T.PUJA, T.STUDY}), _i("harmonium", "Harmonium on a low stand", 0.6, 0.35, 0.55,
                                                          Placement.FLOATING, front_clearance=0.6, cost=18_000)),
    ("Puja", frozenset({T.PUJA, T.FOYER}), _i("puja_bell", "Brass puja bell", 0.2, 0.2, 0.35, Placement.CORNER,
                                              front_clearance=0.0, cost=2_500)),
    ("Decor", frozenset(_ANY_DRY | {T.KITCHEN}), _i("wall_clock", "Wall clock", 0.35, 0.05, 0.35,
                                                    Placement.AGAINST_WALL, front_clearance=0.0, cost=3_000)),
    ("Decor", frozenset(_ANY_DRY | _WET), _i("mirror_round", "Round wall mirror", 0.7, 0.04, 0.7,
                                             Placement.AGAINST_WALL, front_clearance=0.0, cost=6_500)),
    ("Decor", frozenset(_ANY_DRY), _i("books", "Stack of books", 0.4, 0.25, 0.3, Placement.FLOATING,
                                      front_clearance=0.0, cost=2_000)),
    ("Decor", frozenset(_ANY_DRY | _OUTSIDE | _WET), _i("succulent", "Succulent in a white pot", 0.3, 0.3, 0.3,
                                                        Placement.CORNER, front_clearance=0.0, cost=1_200)),
    ("Decor", frozenset(_SITTING | {T.FOYER, T.DINING}), _i("floor_vase", "Brass floor vase", 0.4, 0.4, 0.6,
                                                            Placement.CORNER, front_clearance=0.1, cost=8_500)),
    ("Decor", frozenset({T.PUJA, T.FOYER} | _SITTING), _i("brass_pot", "Brass kalash", 0.35, 0.35, 0.35,
                                                          Placement.CORNER, front_clearance=0.1, cost=5_000)),
    ("Decor", frozenset({T.PUJA, T.FOYER, T.VERANDAH, T.COURTYARD}), _i("rangoli", "Rangoli", 0.9, 0.9, 0.005,
                                                                         Placement.FLOATING, front_clearance=0.0,
                                                                         cost=1_500)),
    ("Decor", frozenset(_OUTSIDE | _SITTING), _i("planter_box", "Wooden planter box", 0.8, 0.4, 0.5,
                                                 Placement.AGAINST_WALL, front_clearance=0.2, cost=5_500)),
    ("Decor", frozenset(_OUTSIDE), _i("tulsi", "Tulsi planter", 0.5, 0.5, 0.9, Placement.FLOATING,
                                      front_clearance=0.3, cost=5_000)),
]

#: Colours an item may be made in, by what it is made of.
COLOURS: dict[str, list[dict[str, str]]] = {
    "wood": [{"name": n, "hex": h} for n, h in (
        ("Teak", "#7a4b2a"), ("Walnut", "#5a3d2a"), ("Sheesham", "#6b3f22"), ("Light oak", "#b08a62"),
        ("Rosewood", "#4a2a20"), ("Cane natural", "#c9a46a"), ("White lacquer", "#efece6"), ("Charcoal", "#2f2f30"),
        ("Sage lacquer", "#8c9a7e"), ("Indigo lacquer", "#34406e"))],
    "fabric": [{"name": n, "hex": h} for n, h in (
        ("Ivory", "#ece4d4"), ("Beige", "#d6c7a8"), ("Mustard", "#c9952e"), ("Rust", "#a8552e"),
        ("Indigo", "#34406e"), ("Emerald", "#2f6b4f"), ("Maroon", "#6e2430"), ("Peacock", "#1f5a5e"),
        ("Grey", "#8a8a88"), ("Blush", "#d9a8a0"), ("Charcoal", "#3a3a3a"), ("Olive", "#6b6b3a"))],
    "metal": [{"name": n, "hex": h} for n, h in (
        ("Brass", "#b08a3e"), ("Copper", "#b0683c"), ("Black", "#1f1e1d"), ("Antique bronze", "#6e5434"),
        ("Brushed steel", "#a9abad"))],
    # The kitchen's and the utility's machines: steel, black glass, or a colour of the room.
    "appliance": [{"name": n, "hex": h} for n, h in (
        ("Stainless steel", "#a9abad"), ("Black glass", "#232323"), ("Champagne", "#cfc3a8"), ("Ivory", "#e8dccb"),
        ("White", "#efe6dc"), ("Sage", "#9aa58f"), ("Powder blue", "#c9d9e6"), ("Navy", "#2b3550"),
        ("Pastel mint", "#cfe3d4"), ("Retro red", "#a8352e"))],
}

#: Pieces fixed to a wall above the floor, and pieces hung from the ceiling: they
#: may sit over furniture, and are placed on a wall or over a table, not on the floor.
WALL_MOUNTED = {"drapes_sheer", "blinds_venetian", "tv_wall", "ac_split", "microwave", "wall_clock", "mirror_round", "mirror_cabinet", "chimney", "purifier",
                "geyser", "wall_art", "wall_shelf", "mandir_wall"}
CEILING_HUNG = {"chandelier", "pendant_light"}


def _ft(w_ft: float, d_ft: float) -> tuple[float, float]:
    return round(w_ft * 0.3048, 3), round(d_ft * 0.3048, 3)


#: Standard sizes as Indian furniture is sold, so a buyer can check one against
#: the room: (name, width x depth in feet). Width is across the front.
SIZES: list[tuple[tuple[str, ...], list[tuple[str, float, float]]]] = [
    (("bed_bunk",), [("Single bunk", 3.0, 6.25), ("Wide bunk", 3.5, 6.25)]),
    (("bed",), [("Single", 3.0, 6.25), ("Single XL", 3.5, 6.5), ("Double", 4.5, 6.25), ("Queen", 5.0, 6.5),
                ("King", 6.0, 6.5)]),
    (("dining_round",), [("2-seat round", 2.5, 2.5), ("4-seat round", 3.5, 3.5), ("6-seat round", 4.5, 4.5)]),
    (("dining", "family_table"), [("2-seat", 2.5, 2.5), ("4-seat", 4.0, 2.5), ("6-seat", 5.5, 3.0),
                                  ("8-seat", 7.0, 3.25)]),
    (("sofa_l", "sectional"), [("L 7 x 5 ft", 7.0, 5.0), ("L 8 x 5.5 ft", 8.0, 5.5), ("L 9 x 6 ft", 9.0, 6.0)]),
    (("sofa", "sofa_formal", "sofa_bed"), [("2-seater", 5.0, 2.8), ("3-seater", 7.0, 2.9), ("4-seater", 8.0, 3.0)]),
    (("diwan", "baithak", "bench"), [("4 ft", 4.0, 2.0), ("5 ft", 5.0, 2.5), ("6 ft", 6.0, 2.6)]),
    (("wardrobe",), [("2-door, 3 ft", 3.0, 2.0), ("3-door, 4.5 ft", 4.5, 2.0), ("4-door, 6 ft", 6.0, 2.0),
                     ("Sliding, 8 ft", 8.0, 2.15)]),
    (("coffee_table", "centre_table"), [("Small, 3 x 1.5 ft", 3.0, 1.5), ("Standard, 4 x 2 ft", 4.0, 2.0),
                                        ("Large, 4.5 x 2.5 ft", 4.5, 2.5)]),
    (("tv_floating",), [("6 ft", 6.0, 1.3), ("7 ft", 7.0, 1.3), ("8 ft", 8.0, 1.3), ("10 ft", 10.0, 1.3)]),
    (("standing_desk",), [("4 ft", 4.0, 2.25), ("5 ft", 5.0, 2.5), ("6 ft", 6.0, 2.5)]),
    (("wardrobe_glass",), [("6 ft", 6.0, 2.15), ("8 ft", 8.0, 2.15), ("10 ft", 10.0, 2.15)]),
    (("shower_glass",), [("3 x 3 ft", 3.0, 3.0), ("3 x 4 ft", 4.0, 3.0), ("4 x 4 ft", 4.0, 4.0)]),
    (("drapes_sheer",), [("4 ft window", 5.0, 0.4), ("6 ft window", 7.0, 0.4), ("8 ft window", 9.0, 0.4)]),
    (("blinds_venetian",), [("3 ft", 3.0, 0.2), ("4 ft", 4.0, 0.2), ("5 ft", 5.0, 0.2)]),
    (("tv_wall",), [("43 inch", 3.18, 0.26), ("55 inch", 4.04, 0.26), ("65 inch", 4.77, 0.26), ("75 inch", 5.5, 0.3)]),
    (("ac_split",), [("1 ton", 2.62, 0.72), ("1.5 ton", 3.12, 0.72), ("2 ton", 3.51, 0.8)]),
    (("bathtub",), [("5 ft", 5.0, 2.5), ("5.5 ft", 5.5, 2.5), ("6 ft", 6.0, 2.75)]),
    (("chest_drawers",), [("3 drawers, 2.5 ft", 2.5, 1.5), ("4 drawers, 3 ft", 3.0, 1.5), ("6 drawers, 4 ft", 4.0, 1.5)]),
    (("crib",), [("Standard cot", 4.25, 2.3), ("Cot-bed", 4.6, 2.5)]),
    (("bench_dining", "garden_bench"), [("4 ft", 4.0, 1.3), ("5 ft", 5.0, 1.3), ("6 ft", 6.0, 1.4)]),
    (("chowki",), [("1.5 ft", 1.5, 1.5), ("2 ft", 2.0, 2.0), ("2.5 ft", 2.5, 2.5)]),
    (("aquarium",), [("3 ft", 3.0, 1.25), ("4 ft", 4.0, 1.5)]),
    (("chandelier",), [("Small, 2 ft", 2.0, 2.0), ("Medium, 2.5 ft", 2.5, 2.5), ("Large, 3 ft", 3.0, 3.0)]),
    (("tv_unit", "family_tv"), [("5 ft", 5.0, 1.3), ("6 ft", 6.0, 1.5), ("7 ft", 7.0, 1.5), ("8 ft", 8.0, 1.5)]),
    (("study_desk", "desk", "desk_l", "desk_office"), [("3 ft", 3.0, 2.0), ("4 ft", 4.0, 2.0), ("5 ft", 5.0, 2.25)]),
    (("bookshelf", "shelving", "bookwall"), [("2.5 ft", 2.5, 1.0), ("3 ft", 3.0, 1.0), ("4 ft", 4.0, 1.1)]),
    (("crockery", "sideboard", "console", "bar_cabinet"), [("3 ft", 3.0, 1.25), ("4 ft", 4.0, 1.5),
                                                            ("5 ft", 5.0, 1.5)]),
    (("nightstand", "side_table"), [("1.5 ft", 1.5, 1.25), ("2 ft", 2.0, 1.5)]),
    (("dresser", "dressing_table", "mirror_console"), [("3 ft", 3.0, 1.5), ("4 ft", 4.0, 1.5)]),
    (("shoe",), [("3 ft", 3.0, 1.25), ("4 ft", 4.0, 1.25)]),
    (("rug",), [("4 x 6 ft", 6.0, 4.0), ("5 x 8 ft", 8.0, 5.0), ("6 x 9 ft", 9.0, 6.0), ("8 x 10 ft", 10.0, 8.0)]),
    (("counter_run", "counter_parallel"), [("6 ft", 6.0, 2.0), ("8 ft", 8.0, 2.0), ("10 ft", 10.0, 2.0)]),
    (("accent_chair", "armchair", "wing_chair", "reading_chair"), [("Compact", 2.25, 2.4), ("Standard", 2.5, 2.6),
                                                                   ("Lounge", 2.8, 2.8)]),
]


def sizes_for(item_id: str) -> list[dict[str, Any]]:
    """The standard sizes a piece comes in, in metres and feet."""
    for prefixes, sizes in SIZES:
        if item_id.startswith(prefixes):
            out = []
            for name, w_ft, d_ft in sizes:
                w, d = _ft(w_ft, d_ft)
                out.append({"name": name, "w": w, "d": d, "ft": f"{w_ft:g} x {d_ft:g} ft",
                            "m": f"{w:.2f} x {d:.2f} m"})
            return out
    return []


#: Whole-room colour schemes: walls, accent wall, floor, and the wood, cloth and
#: metal of every piece, chosen to go together.
LOOKS: list[dict[str, str]] = [
    {"id": "kerala_teak", "name": "Kerala teak", "story": "Lime-washed walls, ochre accent, dark teak and ivory cotton.",
     "wall": "#efe9dc", "accent": "#d9a95b", "floor": "kota", "wood": "#7a4b2a", "fabric": "#ece4d4", "metal": "#b08a3e", "appliance": "#cfc3a8"},
    {"id": "jaipur_pink", "name": "Jaipur pink", "story": "Pink-city plaster, terracotta, sheesham and mustard.",
     "wall": "#e2b8a6", "accent": "#c27b5c", "floor": "marble", "wood": "#6b3f22", "fabric": "#c9952e", "metal": "#b08a3e", "appliance": "#e8dccb"},
    {"id": "chettinad", "name": "Chettinad indigo", "story": "Cream walls, Chettinad blue, Athangudi tiles, rosewood.",
     "wall": "#efe3c8", "accent": "#7f8fb0", "floor": "athangudi", "wood": "#4a2a20", "fabric": "#34406e", "metal": "#b08a3e", "appliance": "#34406e"},
    {"id": "monsoon_sage", "name": "Monsoon sage", "story": "Sage and forest green, light oak, olive linen.",
     "wall": "#c9cfb7", "accent": "#3f4a3c", "floor": "wood", "wood": "#b08a62", "fabric": "#6b6b3a", "metal": "#6e5434", "appliance": "#9aa58f"},
    {"id": "mumbai_modern", "name": "Mumbai modern", "story": "Gallery white, charcoal accent, white lacquer and grey.",
     "wall": "#f6f4f0", "accent": "#4a4846", "floor": "vitrified", "wood": "#efece6", "fabric": "#8a8a88", "metal": "#1f1e1d", "appliance": "#232323"},
    {"id": "haveli_gold", "name": "Haveli gold", "story": "Warm gold walls, Jaisalmer stone, walnut and maroon.",
     "wall": "#e7c48d", "accent": "#b98a6e", "floor": "jaisalmer", "wood": "#5a3d2a", "fabric": "#6e2430", "metal": "#b08a3e", "appliance": "#cfc3a8"},
    {"id": "goa_coastal", "name": "Goa coastal", "story": "Sea-washed walls, powder blue, cane and peacock teal.",
     "wall": "#e8eef0", "accent": "#c9d9e6", "floor": "terrazzo", "wood": "#c9a46a", "fabric": "#1f5a5e", "metal": "#a9abad", "appliance": "#c9d9e6"},
    {"id": "peacock_royal", "name": "Peacock royal", "story": "Ivory with indigo, white marble, rosewood and teal.",
     "wall": "#f4efe4", "accent": "#5f6f96", "floor": "marble", "wood": "#4a2a20", "fabric": "#1f5a5e", "metal": "#b08a3e", "appliance": "#2b3550"},
    {"id": "terracotta_earth", "name": "Terracotta earth", "story": "Sand and terracotta, red oxide floor, rust and copper.",
     "wall": "#e3cfa8", "accent": "#c27b5c", "floor": "redoxide", "wood": "#6b3f22", "fabric": "#a8552e", "metal": "#b0683c", "appliance": "#a9abad"},
    {"id": "nordic_calm", "name": "Calm greige", "story": "Greige and taupe, oak floor, light oak and beige.",
     "wall": "#cfc8bd", "accent": "#a39686", "floor": "wood", "wood": "#b08a62", "fabric": "#d6c7a8", "metal": "#1f1e1d", "appliance": "#e9e5dd"},
    {"id": "charcoal_luxe", "name": "Charcoal luxe", "story": "Greige with a charcoal wall, black granite, walnut and brass.",
     "wall": "#cfc8bd", "accent": "#4a4846", "floor": "granite", "wood": "#5a3d2a", "fabric": "#3a3a3a", "metal": "#b08a3e", "appliance": "#232323"},
    {"id": "blush_brass", "name": "Blush and brass", "story": "Blush walls, desert rose, white marble and lacquer.",
     "wall": "#ecd2cc", "accent": "#d9b2a0", "floor": "marble", "wood": "#efece6", "fabric": "#d9a8a0", "metal": "#b08a3e", "appliance": "#efe6dc"},
    {"id": "mint_fresh", "name": "Mint and mustard", "story": "A child's room: mint, mustard, light oak and emerald.",
     "wall": "#cfe3d4", "accent": "#d9a93f", "floor": "wood", "wood": "#b08a62", "fabric": "#2f6b4f", "metal": "#a9abad", "appliance": "#cfe3d4"},
    {"id": "indigo_night", "name": "Indigo night", "story": "A bedroom: powder blue, indigo wall, walnut and indigo.",
     "wall": "#c9d9e6", "accent": "#5f6f96", "floor": "wood", "wood": "#5a3d2a", "fabric": "#34406e", "metal": "#6e5434", "appliance": "#a9abad"},
]

#: Floors a room may be finished in.
FLOORS: list[dict[str, str]] = [
    {"id": "kota", "name": "Kota stone", "hex": "#7f8a7c"},
    {"id": "marble", "name": "White Makrana marble", "hex": "#e9e6df"},
    {"id": "terrazzo", "name": "Terrazzo", "hex": "#cfc6b6"},
    {"id": "athangudi", "name": "Athangudi tiles", "hex": "#a85a3c"},
    {"id": "granite", "name": "Black granite", "hex": "#2e2f31"},
    {"id": "vitrified", "name": "Vitrified tile", "hex": "#d8d3ca"},
    {"id": "wood", "name": "Engineered wood", "hex": "#93673f"},
    {"id": "redoxide", "name": "Red oxide", "hex": "#8e3b2a"},
    {"id": "jaisalmer", "name": "Jaisalmer yellow stone", "hex": "#d8b878"},
    {"id": "statuario", "name": "Italian Statuario marble", "hex": "#eeece8"},
    {"id": "herringbone", "name": "Herringbone oak parquet", "hex": "#a77b4f"},
    {"id": "microcement", "name": "Polished micro-cement", "hex": "#b9b6af"},
    {"id": "moroccan", "name": "Moroccan accent tiles", "hex": "#3f6f8f"},
    {"id": "slate", "name": "Charcoal slate stone", "hex": "#3b3d40"},
    {"id": "checker", "name": "Checkerboard marble", "hex": "#d9d6cf"},
    {"id": "chevron", "name": "Chevron oak", "hex": "#9c7148"},
    {"id": "hexagon", "name": "Hexagon cement tiles", "hex": "#b7b1a6"},
    {"id": "mosaic", "name": "Glass mosaic", "hex": "#5e8c95"},
    {"id": "walnut", "name": "Wide walnut planks", "hex": "#5b3e2b"},
    {"id": "cotto", "name": "Terracotta cotto tiles", "hex": "#b0623f"},
    {"id": "greykota", "name": "Grey Kota stone", "hex": "#8f938c"},
    {"id": "whiteterrazzo", "name": "White terrazzo", "hex": "#e8e3da"},
]

#: Ceiling designs: the false ceiling a room may have.
CEILINGS: list[dict[str, str]] = [
    {"id": "plain", "name": "Plain plastered"},
    {"id": "cove", "name": "Cove with hidden light"},
    {"id": "tray", "name": "Stepped double tray"},
    {"id": "coffered", "name": "Coffered grid"},
    {"id": "beams", "name": "Wooden beams"},
    {"id": "pop", "name": "POP moulding border"},
    {"id": "slats", "name": "Wooden slat ceiling"},
]
CEILING_IDS = {c["id"] for c in CEILINGS}

#: Treatments a wall can take instead of paint, each with its usual colour.
WALL_TREATMENTS: list[dict[str, str]] = [
    {"id": "fluted", "name": "Fluted timber slats", "hex": "#8a5d3b"},
    {"id": "acoustic", "name": "Charcoal acoustic panels", "hex": "#3a3a3c"},
    {"id": "brick", "name": "Exposed wirecut brick", "hex": "#a4553a"},
    {"id": "travertine", "name": "Honed travertine cladding", "hex": "#d8c8ad"},
    {"id": "pichwai", "name": "Botanical Pichwai wallpaper", "hex": "#2f5d50"},
    {"id": "linenpaper", "name": "Textured linen wallpaper", "hex": "#d9cfbf"},
]
TREATMENT_IDS = {t["id"] for t in WALL_TREATMENTS}
LIGHT_PRESETS = [{"k": 2700, "name": "Warm and cosy, 2700K"}, {"k": 4000, "name": "Natural day, 4000K"},
                 {"k": 5500, "name": "Task white, 5500K"}]
FLOOR_IDS = {f["id"] for f in FLOORS}

#: What part of an item takes its colour: its frame and boards, or its cloth.
_FABRIC = ("drapes", "sofa", "sectional", "recliner", "accent_chair", "wing_chair", "armchair", "reading_chair", "diwan",
           "baithak", "bean_bag", "pouffe", "bench", "rug", "sofa_bed", "ottoman", "office_chair")
_METAL = ("brass_lamp", "diya_stand", "urli", "floor_lamp", "mirror_full", "towel_ladder", "filing_cabinet",
          "drying_rack", "chandelier", "candles", "floor_vase", "brass_pot", "puja_bell")


#: The look each room starts in, by the house's style: (public rooms, bedrooms, the master
#: bedroom, a child's room, the kitchen and service rooms). A house reads as designed when
#: its rooms are related but not the same; the client changes any of them in one click.
STYLE_LOOKS: dict[str, tuple[str, str, str, str, str]] = {
    "modern_indian": ("kerala_teak", "monsoon_sage", "charcoal_luxe", "mint_fresh", "nordic_calm"),
    "kerala_vernacular": ("kerala_teak", "monsoon_sage", "haveli_gold", "mint_fresh", "kerala_teak"),
    "traditional_indian": ("haveli_gold", "jaipur_pink", "peacock_royal", "mint_fresh", "terracotta_earth"),
    "rajasthani_haveli": ("haveli_gold", "jaipur_pink", "peacock_royal", "mint_fresh", "terracotta_earth"),
    "indo_saracenic": ("peacock_royal", "jaipur_pink", "haveli_gold", "mint_fresh", "nordic_calm"),
    "chettinad": ("chettinad", "peacock_royal", "haveli_gold", "mint_fresh", "chettinad"),
    "tropical_modern": ("monsoon_sage", "goa_coastal", "charcoal_luxe", "mint_fresh", "nordic_calm"),
    "biophilic": ("monsoon_sage", "goa_coastal", "kerala_teak", "mint_fresh", "monsoon_sage"),
    "industrial": ("charcoal_luxe", "nordic_calm", "charcoal_luxe", "mint_fresh", "mumbai_modern"),
    "brutalist": ("charcoal_luxe", "nordic_calm", "charcoal_luxe", "mint_fresh", "mumbai_modern"),
}
_DEFAULT_LOOKS = ("nordic_calm", "indigo_night", "charcoal_luxe", "mint_fresh", "mumbai_modern")
#: Floors a kitchen, utility or puja room keeps whatever the look: stone, tile and terrazzo, not wood.
_HARD_FLOORS = {"kota", "marble", "terrazzo", "athangudi", "granite", "vitrified", "redoxide", "jaisalmer",
                "statuario", "microcement", "slate", "checker", "hexagon", "greykota", "whiteterrazzo", "cotto"}


def default_look(room_type: RoomType, style: str | None) -> dict[str, str] | None:
    """The look a room is first shown in, before the client chooses one; None for wet rooms."""
    if room_type in (T.BATHROOM, T.TOILET, T.POWDER, T.STAIRCASE, T.CORRIDOR, T.LOBBY, T.SHAFT) or room_type.is_outdoor:
        return None
    looks = STYLE_LOOKS.get(style or "", _DEFAULT_LOOKS)
    if room_type is T.MASTER_BEDROOM:
        pick = looks[2]
    elif room_type is T.CHILDREN_BEDROOM:
        pick = looks[3]
    elif room_type in (T.BEDROOM, T.GUEST_BEDROOM):
        pick = looks[1]
    elif room_type in (T.KITCHEN, T.UTILITY, T.PANTRY, T.LAUNDRY, T.STORE, T.GYM):
        pick = looks[4]
    else:
        pick = looks[0]
    return next((lk for lk in LOOKS if lk["id"] == pick), None)


def default_finishes(room_type: RoomType, style: str | None) -> dict[str, str]:
    """The walls, accent and floor of a room's first look (see `default_look`)."""
    lk = default_look(room_type, style)
    if lk is None:
        return {}
    out = {"wall": lk["wall"], "accent": lk["accent"], "look": lk["id"]}
    if room_type not in (T.KITCHEN, T.UTILITY, T.PANTRY, T.LAUNDRY, T.PUJA, T.STORE) or lk["floor"] in _HARD_FLOORS:
        out["floor"] = lk["floor"]
    return out


def look_colour(lk: dict[str, str] | None, item_id: str) -> str | None:
    """The colour a piece takes in a look: its wood, its fabric, its metal or its machines."""
    if not lk:
        return None
    return {"wood": lk.get("wood"), "fabric": lk.get("fabric"), "metal": lk.get("metal"),
            "appliance": lk.get("appliance")}.get(colour_group(item_id))


def colour_group(item_id: str) -> str:
    """What takes the client's colour: boards ("wood"), cloth ("fabric"), metal, or nothing (sanitaryware)."""
    if item_id.startswith(("fridge", "microwave", "chimney", "dishwasher", "washer")):
        return "appliance"
    if item_id.startswith(("wc", "shower", "purifier",
                           "ac_split", "tv_wall", "geyser", "bathtub", "aquarium", "rangoli", "wall_clock", "books",
                           "succulent", "pendant_light", "plant", "tulsi", "aquarium", "robot_vacuum", "air_purifier",
                           "standing_desk", "deck_turf")):
        return "none"
    if item_id.startswith(_FABRIC):
        return "fabric"
    if item_id.startswith(_METAL):
        return "metal"
    return "wood"


def _all_items() -> dict[str, tuple[str, FurnitureItem]]:
    out: dict[str, tuple[str, FurnitureItem]] = {}
    for room_type, items in CATALOGUE.items():
        for it in items:
            out.setdefault(it.id, (_group_of(it), it))
    for group, _rooms, it in EXTRAS:
        out[it.id] = (group, it)
    return out


def _group_of(it: FurnitureItem) -> str:
    iid = it.id
    if iid.startswith("bed"):
        return "Beds"
    if iid.startswith(("sofa", "sectional", "recliner", "accent", "wing", "armchair", "reading", "task_chair",
                       "luggage")):
        return "Seating"
    if iid.startswith(("dining", "coffee", "centre", "family_table", "desk", "study_desk", "nightstand", "dresser")):
        return "Tables"
    if iid.startswith(("counter", "fridge", "tall_unit")):
        return "Kitchen"
    if iid.startswith(("mandir",)):
        return "Puja"
    if iid.startswith(("wc", "basin", "shower", "washer", "utility_sink")):
        return "Fixtures"
    return "Storage"


ITEMS = _all_items()


def item(item_id: str) -> FurnitureItem | None:
    got = ITEMS.get(item_id)
    return got[1] if got else None


def catalogue_for(room_type: RoomType) -> dict[str, Any]:
    """Everything a client may put in a room of this kind, grouped, with the
    colours each comes in and the finishes the room may take."""
    seen: set[str] = set()
    names: set[str] = set()
    groups: dict[str, list[dict[str, Any]]] = {}

    def add(group: str, it: FurnitureItem) -> None:
        # One of each: an extra the room already has under the same name is not offered twice.
        if it.id in seen or it.name.lower() in names:
            return
        seen.add(it.id)
        names.add(it.name.lower())
        groups.setdefault(group, []).append({
            "id": it.id, "name": it.name, "width": it.width, "depth": it.depth, "height": it.height,
            "colour_group": colour_group(it.id), "sizes": sizes_for(it.id),
            "placement": it.placement.value,
            "mount": "wall" if it.id in WALL_MOUNTED else "ceiling" if it.id in CEILING_HUNG else "",
        })

    for it in CATALOGUE.get(room_type, []):
        add(_group_of(it), it)
    for group, rooms, it in EXTRAS:
        if room_type in rooms:
            add(group, it)
    from aip.engines.experience.exteriors import PAINTS
    from aip.engines.interior.furnish import artworks as _artworks

    return {
        "room_type": room_type.value,
        "groups": [{"name": g, "items": items} for g, items in groups.items()],
        "colours": COLOURS,
        "looks": LOOKS,
        "treatments": WALL_TREATMENTS,
        "lights": LIGHT_PRESETS,
        "ceilings": CEILINGS,
        "floors": FLOORS,
        "paints": [{"name": n, "hex": h} for n, h in PAINTS["wall"]],
        "art": [{"id": a["id"], "title": a["title"], "artist": a["artist"], "aspect": a.get("aspect", 0.8)}
                for a in _artworks()],
    }


def _hex(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip().lstrip("#").lower()
    return f"#{v}" if len(v) == 6 and all(c in "0123456789abcdef" for c in v) else None


def clean_room_edit(plan: FloorPlan, room: Room, items: list[dict[str, Any]],
                    finishes: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """What the client did to a room, made buildable: unknown items dropped,
    every item kept inside the room and turned to a right angle, colours and
    finishes checked. Returns the edit to store and a note per change made."""
    notes: list[str] = []
    box = room.bbox
    out_items: list[dict[str, Any]] = []
    for raw in items[:60]:
        iid = str(raw.get("item_id", ""))
        it = item(iid)
        if it is None:
            notes.append(f"'{iid}' is not in the catalogue and was left out.")
            continue
        rot = (round(float(raw.get("rotation", 0.0)) / 90.0) * 90) % 360
        swapped = rot in (90, 270)
        # A standard size of this piece, if one was chosen; never a made-up one.
        size = next((z for z in sizes_for(iid) if abs(z["w"] - float(raw.get("w") or 0)) < 0.02
                     and abs(z["d"] - float(raw.get("d") or 0)) < 0.02), None)
        iw, idp = (size["w"], size["d"]) if size else (it.width, it.depth)
        w, d = (idp, iw) if swapped else (iw, idp)
        if w > box.width + 0.01 or d > box.height + 0.01:
            notes.append(f"The {it.name.lower()} does not fit in the {room.display_name().lower()} that way round.")
            continue
        x = float(raw.get("x", box.centre.x))
        y = float(raw.get("y", box.centre.y))
        cx = min(max(x, box.min_x + w / 2), box.max_x - w / 2)
        cy = min(max(y, box.min_y + d / 2), box.max_y - d / 2)
        if math.hypot(cx - x, cy - y) > 0.05:
            notes.append(f"The {it.name.lower()} was moved back inside the room.")
        out_items.append({
            "uid": str(raw.get("uid") or uuid.uuid4().hex[:10]), "item_id": iid,
            "x": round(cx, 3), "y": round(cy, 3), "rotation": float(rot),
            "colour": _hex(raw.get("colour")),
            "art": raw.get("art") if raw.get("art") in _art_ids() else None,
            **({"w": size["w"], "d": size["d"], "size": size["name"]} if size else {}),
        })
    fin: dict[str, Any] = {}
    for key in ("wall", "accent"):
        h = _hex((finishes or {}).get(key))
        if h:
            fin[key] = h
    floor = (finishes or {}).get("floor")
    if floor in FLOOR_IDS:
        fin["floor"] = floor
    # One colour per wall, for the walls of this room only.
    own_walls = {w.id for lv in plan.levels for w in lv.walls if room.id in w.rooms}
    per_wall = {wid: h for wid, h in (((finishes or {}).get("walls") or {}).items()) if wid in own_walls}
    per_wall = {wid: (h if h in TREATMENT_IDS else _hex(h)) for wid, h in per_wall.items() if h in TREATMENT_IDS or _hex(h)}
    if per_wall:
        fin["walls"] = per_wall
    ceiling = (finishes or {}).get("ceiling")
    if ceiling in CEILING_IDS and ceiling != "plain":
        fin["ceiling"] = ceiling
    elif (finishes or {}).get("cove") and not ceiling:
        fin["ceiling"] = "cove"
    # The edges of the walls: skirting at the floor, a cornice at the ceiling,
    # wainscot panelling to dado height in a colour.
    for key in ("skirting", "cornice"):
        if (finishes or {}).get(key):
            fin[key] = True
    dado = _hex((finishes or {}).get("dado"))
    if dado:
        fin["dado"] = dado
    kelvin = (finishes or {}).get("kelvin")
    if kelvin in (2700, 4000, 5500):
        fin["kelvin"] = kelvin
    look = (finishes or {}).get("look")
    if any(lk["id"] == look for lk in LOOKS):
        fin["look"] = look
    art = (finishes or {}).get("art")
    if art == "none" or art in _art_ids():
        fin["art"] = art
    return {"items": out_items, "finishes": fin}, notes


def _art_ids() -> set[str]:
    from aip.engines.interior.furnish import artworks

    return {a["id"] for a in artworks()}


def room_edit(plan: FloorPlan, room_id: str) -> dict[str, Any] | None:
    return (plan.metadata or {}).get("interior_edits", {}).get(room_id)


__all__ = ["COLOURS", "EXTRAS", "LOOKS", "SIZES", "sizes_for", "FLOORS", "ITEMS", "catalogue_for", "clean_room_edit", "colour_group", "item", "room_edit"]
