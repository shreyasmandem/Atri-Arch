"""Exterior design grammar: many distinct houses from one plan.

A facade here is a combination of independent decisions an architect makes
for the street face of a house, each a small vocabulary:

* **roof**     - flat behind a parapet, a thin cantilevered slab, a mono-pitch
                 over a clerestory, a butterfly, a hipped tile roof, a gable;
* **base**     - the ground floor: plaster, stone, exposed brick, board-marked
                 concrete, timber boarding, dark metal panels;
* **upper**    - the floors above, from the same six skins;
* **screen**   - what dresses the street face of the upper floor: nothing,
                 vertical fins, horizontal louvres, a deep box frame, a jaali,
                 a perforated metal screen;
* **windows**  - punched openings, or a continuous dark glazing band per floor;
* **planters** - planter boxes along the parapets and sills, or none;
* **accent**   - one colour for the frame, fins or screen;
* **feature**  - the signature element (jharokha, colonnade, chhatri, ...);
* **colours**  - optional exact tints for the walls, the cladding, the roof and
                 the accent metal, over whatever colour scheme is chosen.

A design is serialised into a compact id (`ex:roof.base.upper.screen.windows.
planters.accent.feature[~w:hex,c:hex,r:hex,m:hex]`), so the model URL carries
the whole design and any design can be rebuilt from its id alone. The exterior
agent composes these from the client's words; `generate` gives a varied,
style-aware set without a model, and a fresh `seed` gives a fresh batch.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass
from typing import Any

from aip.domain.geometry import Vec2
from aip.domain.plan import FloorPlan
from aip.engines.experience.facades import Edge, edges, pitch_roof

ROOFS = ("flat", "slab", "mono", "butterfly", "hip", "gable", "vault", "sawtooth")
#: Wall skins. Terracotta tile, ACP (aluminium composite panel) and stacked
#: slate are what Indian elevations layer today beside plaster and stone.
BASES = ("plaster", "stone", "brick", "concrete", "timber", "metal", "terracotta", "acp", "slate", "glass", "corten")
UPPERS = ("plaster", "timber", "metal", "brick", "stone", "concrete", "terracotta", "acp", "slate", "glass", "corten")
#: Skins that carry their own colour: a glass curtain wall and weathering steel are not tinted by the scheme's cladding.
SELF_COLOURED = {"glass", "corten"}
SCREENS = ("none", "fins", "louvres", "frame", "jaali", "perforated", "slats", "bamboo")
WINDOWS = ("punched", "band")
#: The design's signature element: what a passer-by remembers the house by.
FEATURES = ("none", "jharokha", "colonnade", "chhatri", "cornice", "breeze", "greenwall", "balcony",
            "arcade", "portico", "bay", "floatbox", "featurewall", "thinnai", "bangla", "pergolaframe", "cornerglass",
            "brickcurtain", "wavescreen", "moongate", "cantilever", "flutedbands", "brisesoleil", "planterbands",
            "rooftopframe")
ACCENTS = {"bronze": "#8a6a4c", "charcoal": "#2b2a29", "teak": "#7a4b2a", "white": "#efece6",
           "terracotta": "#a8553a", "sage": "#7d8b6a", "navy": "#2b3a52", "brass": "#b08a3e",
           "ochre": "#c08a2e", "indigo": "#34406e", "forest": "#2f4a36", "rose": "#b46a6a",
           "slate": "#59626b", "sand": "#d2b98f", "copper": "#b0683c", "olive": "#6b6b3a",
           "graphite": "#3d3f42", "verdigris": "#5f8a7e"}
#: The four tints a design may fix exactly: id key -> Exterior field.
COLOUR_KEYS = {"w": "wall", "c": "clad", "r": "roof_tint", "m": "metal", "f": "frame", "d": "door"}

#: Every part of the outside a client can pick in 3D and paint, by the 3D
#: model's material key: (label, group, words a client might use for it).
#: Its colour rides in the design id's "z" entry ("z:compound-8a8a8a.gate-7a4b2a"),
#: so the elevations, thumbnails and the registry all see the same house.
PARTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "plaster": ("Wall paint", "Walls", ("wall", "walls", "plaster", "facade", "house colour", "outer walls")),
    "clad": ("Stone cladding", "Walls", ("stone", "stone cladding", "cladding")),
    "ex_brick": ("Brick", "Walls", ("brick", "bricks", "brickwork")),
    "ex_concrete": ("Concrete", "Walls", ("concrete", "exposed concrete")),
    "ex_timber": ("Timber cladding and slats", "Walls", ("timber", "wood", "wooden", "slats", "battens", "wood cladding")),
    "ex_terracotta": ("Terracotta", "Walls", ("terracotta", "jaali", "clay")),
    "ex_acp": ("ACP panels", "Walls", ("acp", "aluminium panels", "metal panels")),
    "ex_slate": ("Slate", "Walls", ("slate",)),
    "ex_curtain": ("Glass curtain wall", "Walls", ("curtain wall", "glass wall", "glass facade", "glazed wall")),
    "ex_corten": ("Corten steel", "Walls", ("corten", "weathering steel", "rusted steel", "rust")),
    "ex_panel": ("Feature panel", "Walls", ("feature panel", "feature wall", "panel")),
    "ex_accent": ("Accent bands and trims", "Trims", ("accent", "bands", "band", "trim", "trims", "frame band")),
    "slab": ("Slab edges and chajjas", "Trims", ("slab", "slabs", "chajja", "chajjas", "sunshade", "sunshades", "ledge")),
    "sill": ("Window sills and copings", "Trims", ("sill", "sills", "coping")),
    "plinth": ("Plinth", "Trims", ("plinth", "base band", "skirting")),
    "ex_metal": ("Metal fins and screens", "Trims", ("fins", "metal", "louvres", "screen", "metal screen")),
    "ex_roof": ("Roof slab", "Roof", ("roof", "roof slab", "roof plate")),
    "roof_tile": ("Roof tiles", "Roof", ("roof tiles", "tiles", "tiled roof")),
    "roof_flat": ("Terrace floor", "Roof", ("terrace", "terrace floor", "roof terrace")),
    "water": ("Water tank", "Roof", ("water tank", "tank", "sintex")),
    "timber": ("Pergola", "Roof", ("pergola",)),
    "frame": ("Window frames", "Windows and doors", ("window frames", "frames", "window frame", "windows")),
    "glass": ("Window glass", "Windows and doors", ("glass", "glazing")),
    "main_door": ("Main door", "Windows and doors", ("main door", "front door", "entrance door")),
    "door": ("Other doors", "Windows and doors", ("doors", "door")),
    "rail_metal": ("Railings", "Windows and doors", ("railing", "railings", "grill", "grille", "balcony railing")),
    "compound": ("Boundary wall", "Outside", ("boundary", "boundary wall", "compound wall", "compound", "fence")),
    "gate": ("Gate", "Outside", ("gate", "main gate", "timber gate")),
    "gate_steel": ("Gate steelwork", "Outside", ("sliding gate", "steel gate", "gate bars")),
    "shutter": ("Garage shutter", "Outside", ("shutter", "garage shutter", "garage door", "rolling shutter")),
    "car": ("Car", "Outside", ("car",)),
    "paving": ("Paving and drive", "Outside", ("paving", "drive", "driveway", "path", "pavers")),
    "lawn": ("Lawn", "Outside", ("lawn", "grass")),
    "pool_tile": ("Pool tiles", "Outside", ("pool tiles", "pool")),
    "bamboo": ("Bamboo", "Outside", ("bamboo",)),
}
#: The site around the house: what the boundary wall is, and what guards balconies and terraces.
BOUNDARIES = ("plaster", "stone", "brick", "hedge", "grille")
RAILINGS = ("glass", "metal", "solid")
SHADES = ("slim", "none", "deep", "box")              # what shades each window: a chajja, nothing, a deep one, a box frame
CANOPIES = ("slab", "glass", "pergola", "none")       # over the main door
GATES = ("none", "sliding", "timber")
PAVINGS = ("stone", "concrete", "gravel", "grass")    # the drive
GARDENS = ("standard", "lush", "minimal", "none")
SOLAR = ("off", "on")
#: A full-height feature panel on the street face in a second material: how
#: an elevation layers stone or wood-look cladding on part of the front.
PANELS = ("none", "stone", "timber", "slate", "terracotta", "acp", "brick", "corten")
PARAPETS = ("plain", "glass", "grooved", "screen", "stepped")   # the crown of a flat-roofed house
DECKS = ("none", "pergola", "garden")                            # what the roof terrace holds
LIGHTS = ("none", "washers", "strips")                           # facade lighting, lit at night
#: A garden feature, placed in its traditional quarter (see landscape.YARD_FEATURES).
YARDS = ("none", "tulsi", "jhoola", "waterwall", "koipond", "gazebo", "rockgarden", "sitout",
         "fountain", "firepit", "lounge", "flowerbeds")
#: The car porch's street face: open under a beam, or closed by a rolling shutter.
GARAGES = ("open", "closed")
#: Discrete extras in the id's tail: id key -> (Exterior field, vocabulary).
#: The first value of each is what the house has when the id leaves it out.
OPTION_KEYS = {"b": ("boundary", BOUNDARIES), "l": ("railing", RAILINGS), "h": ("shade", SHADES),
               "e": ("canopy", CANOPIES), "g": ("gate", GATES), "v": ("paving", PAVINGS),
               "t": ("garden", GARDENS), "s": ("solar", SOLAR), "x": ("panel", PANELS), "q": ("parapet", PARAPETS),
               "k": ("deck", DECKS), "i": ("lights", LIGHTS), "y": ("yard", YARDS), "a": ("garage", GARAGES)}
#: Named paints per surface, for picking colours one surface at a time.
PAINTS: dict[str, tuple[tuple[str, str], ...]] = {
    "wall": (("Lime white", "#efe9dc"), ("Ivory", "#f4efe4"), ("Gallery white", "#f6f4f0"), ("Warm sand", "#e3cfa8"),
             ("Haveli gold", "#e7c48d"), ("Kerala ochre", "#d9a95b"), ("Jaipur pink", "#e2b8a6"), ("Desert rose", "#d9b2a0"),
             ("Terracotta", "#c27b5c"), ("Clay", "#b98a6e"), ("Sage", "#c9cfb7"), ("Olive mist", "#d8d3b8"),
             ("Monsoon grey", "#d5dadb"), ("Coastal", "#e8eef0"), ("Chettinad blue", "#7f8fb0"), ("Indigo wash", "#5f6f96"),
             ("Raw concrete", "#a9a7a1"), ("Warm grey", "#8f8a82"), ("Charcoal", "#4a4846"), ("Forest", "#3f4a3c"),
             ("Powder blue", "#c9d9e6"), ("Mint", "#cfe3d4"), ("Blush", "#ecd2cc"), ("Pale lemon", "#efe2a6"),
             ("Cream", "#efe3c8"), ("Greige", "#cfc8bd"), ("Taupe", "#a39686"), ("Mustard", "#d9a93f"),
             ("Slate", "#3f454b")),
    "clad": (("Teak", "#7a4b2a"), ("Walnut", "#5a3d2a"), ("Oak", "#8a6a4c"), ("Sandstone", "#b98a5a"), ("Kota grey", "#7f8478"),
             ("Granite", "#59626b"), ("Basalt", "#3a3a38"), ("Red brick", "#8e4a32"), ("Pale brick", "#c49a7a"),
             ("Slate", "#4d5560"), ("Limestone", "#d9d0bd"), ("Cream stone", "#e7d8b8")),
    "roof_tint": (("Mangalore red", "#a8553a"), ("Burnt clay", "#8e3f2a"), ("Brown tile", "#5a3a2a"), ("Charcoal", "#2f3338"),
                  ("Graphite", "#3d3f42"), ("Slate grey", "#59626b"), ("Zinc", "#8c8a84"), ("Copper", "#9c5a34"),
                  ("Forest green", "#2f4a36"), ("Navy", "#2b3a52"), ("Sand", "#c9b28a"), ("White", "#efe9dc")),
    "metal": (("Bronze", "#8a6a4c"), ("Brass", "#b08a3e"), ("Copper", "#b0683c"), ("Black", "#1f1f1f"), ("Charcoal", "#2b2a29"),
              ("Graphite", "#3d3f42"), ("Slate", "#59626b"), ("Teak", "#7a4b2a"), ("Verdigris", "#5f8a7e"),
              ("Forest", "#2f4a36"), ("Navy", "#2b3a52"), ("White", "#efece6")),
    "frame": (("Black", "#1c1b1a"), ("Charcoal", "#2f2f30"), ("Bronze", "#5e4a36"), ("Teak", "#6a4128"), ("White", "#efece6"),
              ("Grey", "#77797b"), ("Green", "#2f4a36"), ("Blue", "#2b3a52")),
    "door": (("Teak", "#55331d"), ("Walnut", "#3e2a1c"), ("Oak", "#8a6a4c"), ("Black", "#1f1e1d"), ("Indigo", "#2b3a6e"),
             ("Peacock", "#1f5a5e"), ("Forest", "#2f4a36"), ("Mustard", "#c08a2e"), ("Vermilion", "#a8352a"), ("Ivory", "#efe9dc")),
}
#: Wall washes and roof tones a fresh batch draws from, so a batch differs in
#: colour as well as form. Each wash sits with the roofs listed beside it.
WALL_TONES = {"lime": ("#efe9dc", ("#a8553a", "#3d3f42", "#8c8a84")), "sand": ("#e3cfa8", ("#8e3f2a", "#5a4632")),
              "ochre": ("#d9a95b", ("#7a3b24", "#3d3f42")), "terracotta": ("#c27b5c", ("#5a3a2a", "#2f2d2b")),
              "pink": ("#e2b8a6", ("#8e3f2a", "#6a5d55")), "sage": ("#c9cfb7", ("#3d3f42", "#6e5236")),
              "mist": ("#d5dadb", ("#2f3338", "#59626b")), "ivory": ("#f4efe4", ("#2b2a29", "#a8553a")),
              "clay": ("#b98a6e", ("#3a2c24", "#59626b")), "charcoal": ("#4a4846", ("#1f1f1f", "#7a4b2a")),
              "indigo": ("#7f8fb0", ("#2b3a52", "#efe9dc")), "haveli": ("#e7c48d", ("#9c5a34", "#c2723f"))}

#: What each style tends towards; a design outside it is still allowed, only less likely.
STYLE_BIAS: dict[str, dict[str, tuple[str, ...]]] = {
    "contemporary": {"roof": ("flat", "slab", "mono", "sawtooth"), "screen": ("fins", "frame", "louvres", "perforated", "slats"),
                     "feature": ("none", "cornice", "breeze", "greenwall", "bay", "portico", "floatbox", "featurewall", "cornerglass", "brickcurtain", "cantilever", "flutedbands", "rooftopframe", "moongate"), "accent": ("bronze", "charcoal", "slate", "teak")},
    "modern_minimal": {"roof": ("slab", "flat"), "screen": ("none", "frame"), "upper": ("plaster", "metal", "glass"),
                       "feature": ("none", "bay", "floatbox", "cornerglass", "cantilever", "flutedbands", "brisesoleil", "rooftopframe"), "accent": ("white", "charcoal", "slate")},
    "tropical_modern": {"roof": ("slab", "mono", "butterfly", "vault"), "upper": ("timber",), "screen": ("louvres", "fins", "slats", "bamboo"),
                        "feature": ("greenwall", "breeze", "none", "pergolaframe", "wavescreen", "planterbands"), "accent": ("teak", "forest", "sage")},
    "kerala_vernacular": {"roof": ("hip", "gable"), "base": ("stone", "plaster"), "upper": ("timber", "plaster"),
                          "feature": ("colonnade", "thinnai", "brickcurtain"), "accent": ("teak", "terracotta", "forest")},
    "traditional_indian": {"roof": ("hip", "flat"), "screen": ("jaali",), "base": ("stone",),
                           "feature": ("jharokha", "colonnade", "cornice", "arcade", "portico", "thinnai", "brickcurtain"), "accent": ("ochre", "terracotta", "teak", "indigo")},
    "chettinad": {"roof": ("hip", "flat"), "screen": ("jaali",), "base": ("stone", "brick"),
                  "feature": ("colonnade", "cornice", "arcade", "thinnai"), "accent": ("ochre", "indigo", "rose", "teak")},
    "rajasthani_haveli": {"roof": ("flat",), "screen": ("jaali",), "base": ("stone",),
                          "feature": ("jharokha", "chhatri", "bangla"), "accent": ("sand", "rose", "ochre", "terracotta")},
    "indo_saracenic": {"roof": ("flat", "vault"), "screen": ("jaali", "frame"), "base": ("stone", "brick"),
                       "feature": ("chhatri", "colonnade", "cornice", "arcade", "bangla", "moongate"), "accent": ("sand", "terracotta", "white")},
    "scandinavian": {"roof": ("gable", "mono"), "upper": ("timber",), "screen": ("none",),
                     "feature": ("none", "cornerglass", "cantilever"), "accent": ("charcoal", "white", "slate")},
    "japandi": {"roof": ("slab", "gable"), "upper": ("timber",), "screen": ("louvres", "none", "slats"),
                "feature": ("none", "greenwall", "pergolaframe", "moongate"), "accent": ("teak", "charcoal", "sand")},
    "industrial": {"base": ("concrete", "brick"), "upper": ("metal", "brick", "corten"), "screen": ("perforated", "frame"),
                   "feature": ("none", "breeze", "featurewall", "brickcurtain", "brisesoleil", "rooftopframe"), "accent": ("charcoal", "slate", "terracotta"), "roof": ("sawtooth",)},
    "biophilic": {"roof": ("slab", "butterfly", "vault"), "upper": ("timber",), "screen": ("louvres", "fins", "bamboo"),
                  "feature": ("greenwall", "pergolaframe", "planterbands", "wavescreen"), "accent": ("forest", "sage", "teak")},
    "mid_century_modern": {"roof": ("butterfly", "mono", "slab", "vault"), "base": ("brick", "stone"), "screen": ("frame", "fins"),
                           "feature": ("breeze", "none", "bay", "featurewall", "floatbox", "brisesoleil", "brickcurtain"), "accent": ("ochre", "teak", "sage", "navy")},
}

NAMES = {
    "fins": "Fin", "louvres": "Louvre", "frame": "Frame", "jaali": "Jaali", "perforated": "Screen", "none": "Plain",
    "flat": "Parapet", "slab": "Slab", "mono": "Skillion", "butterfly": "Butterfly", "hip": "Tiled", "gable": "Gable",
    "vault": "Vault", "sawtooth": "Sawtooth", "slats": "Slat", "bamboo": "Bamboo",
    "arcade": "Arcade", "portico": "Portico", "bay": "Bay-window",
    "floatbox": "Floating-box", "featurewall": "Monolith", "thinnai": "Thinnai", "bangla": "Bangla",
    "pergolaframe": "Pergola", "cornerglass": "Glass-corner", "brickcurtain": "Brick-curtain", "wavescreen": "Wave-screen",
    "moongate": "Moon-gate", "cantilever": "Cantilever", "flutedbands": "Fluted", "brisesoleil": "Brise-soleil",
    "planterbands": "Planter-band", "rooftopframe": "Crown-frame",
    "timber": "Timber", "metal": "Metal", "brick": "Brick", "stone": "Stone", "concrete": "Concrete", "plaster": "Lime",
    "terracotta": "Terracotta", "acp": "Panel", "slate": "Slate", "glass": "Glass", "corten": "Corten",
    "jharokha": "Jharokha", "colonnade": "Colonnade", "chhatri": "Chhatri", "cornice": "Cornice", "breeze": "Breeze-block",
    "greenwall": "Green-wall", "balcony": "Balcony",
}
#: Exterior colour schemes a client picks after the design: walls, cladding,
#: roof and accent metal chosen to sit together, warm and cool, light and dark.
EXTERIOR_SCHEMES: tuple[dict[str, str], ...] = (
    {"id": "lime_teak", "name": "Lime & Teak", "wall": "#efe9dc", "clad": "#7a4b2a", "roof": "#a8553a", "metal": "#7a4b2a"},
    {"id": "jaipur_pink", "name": "Jaipur Pink", "wall": "#e2b8a6", "clad": "#b46a4a", "roof": "#8e3f2a", "metal": "#b08a3e"},
    {"id": "sandstone", "name": "Sandstone", "wall": "#e7c48d", "clad": "#b98a5a", "roof": "#9c5a34", "metal": "#5a4632"},
    {"id": "monsoon_grey", "name": "Monsoon Grey", "wall": "#d5dadb", "clad": "#59626b", "roof": "#2f3338", "metal": "#2b2a29"},
    {"id": "charcoal_brass", "name": "Charcoal & Brass", "wall": "#4a4846", "clad": "#2b2a29", "roof": "#1f1f1f", "metal": "#b08a3e"},
    {"id": "terracotta", "name": "Terracotta Earth", "wall": "#c27b5c", "clad": "#8e4a32", "roof": "#5a3a2a", "metal": "#2f2d2b"},
    {"id": "sage_oak", "name": "Sage & Oak", "wall": "#c9cfb7", "clad": "#8a6a4c", "roof": "#3d3f42", "metal": "#2f4a36"},
    {"id": "chettinad_blue", "name": "Chettinad Blue", "wall": "#7f8fb0", "clad": "#e7d8b8", "roof": "#8e3f2a", "metal": "#efe9dc"},
    {"id": "ochre_kerala", "name": "Kerala Ochre", "wall": "#d9a95b", "clad": "#6e4a2c", "roof": "#7a3b24", "metal": "#3a2c24"},
    {"id": "white_black", "name": "Gallery White", "wall": "#f4f2ee", "clad": "#d9d6cf", "roof": "#2b2a29", "metal": "#1f1f1f"},
    {"id": "clay_copper", "name": "Clay & Copper", "wall": "#b98a6e", "clad": "#6a4a3a", "roof": "#3a2c24", "metal": "#b0683c"},
    {"id": "coastal", "name": "Coastal Mist", "wall": "#e8eef0", "clad": "#9fb3bb", "roof": "#59626b", "metal": "#5f8a7e"},
    {"id": "forest_lodge", "name": "Forest Lodge", "wall": "#3f4a3c", "clad": "#7a5a3a", "roof": "#2a2a26", "metal": "#c08a2e"},
    {"id": "haveli_red", "name": "Haveli Red", "wall": "#a8553a", "clad": "#e7c48d", "roof": "#5a3a2a", "metal": "#b08a3e"},
    {"id": "ivory_navy", "name": "Ivory & Navy", "wall": "#f4efe4", "clad": "#2b3a52", "roof": "#2b3a52", "metal": "#2b3a52"},
    {"id": "concrete_raw", "name": "Raw Concrete", "wall": "#a9a7a1", "clad": "#7f7d78", "roof": "#4a4846", "metal": "#7a4b2a"},
    {"id": "desert_rose", "name": "Desert Rose", "wall": "#d9b2a0", "clad": "#9c6b5a", "roof": "#6a5d55", "metal": "#d2b98f"},
    {"id": "olive_grove", "name": "Olive Grove", "wall": "#d8d3b8", "clad": "#6b6b3a", "roof": "#4a3f2a", "metal": "#6b6b3a"},
    {"id": "nordic", "name": "Nordic Black", "wall": "#2f2f30", "clad": "#8a6a4c", "roof": "#1f1f1f", "metal": "#8a6a4c", "frame": "#1c1b1a"},
    {"id": "goa_villa", "name": "Goa Villa", "wall": "#e9c46a", "clad": "#efe9dc", "roof": "#a8553a", "metal": "#efece6", "frame": "#efece6", "door": "#1f5a5e"},
    {"id": "pondicherry", "name": "Pondicherry", "wall": "#f2d7a0", "clad": "#efe9dc", "roof": "#8e3f2a", "metal": "#2f4a36", "door": "#2f4a36"},
    {"id": "mumbai_deco", "name": "Mumbai Deco", "wall": "#efe3d0", "clad": "#c9b28a", "roof": "#5a3a2a", "metal": "#2b3a52", "frame": "#efece6"},
    {"id": "jodhpur_blue", "name": "Jodhpur Blue", "wall": "#9fb6d6", "clad": "#e7d8b8", "roof": "#efe9dc", "metal": "#2b3a52", "door": "#a8352a"},
    {"id": "kutch_mud", "name": "Kutch Mud", "wall": "#d6b48f", "clad": "#a77a55", "roof": "#6e4a2c", "metal": "#5a3d2a", "door": "#a8352a"},
    {"id": "warm_minimal", "name": "Warm Minimal", "wall": "#ece4d6", "clad": "#c49a7a", "roof": "#8c8a84", "metal": "#5e4a36", "frame": "#5e4a36"},
    {"id": "grey_oak", "name": "Grey & Oak", "wall": "#8f8a82", "clad": "#8a6a4c", "roof": "#3d3f42", "metal": "#1f1f1f", "frame": "#2f2f30"},
    {"id": "emerald", "name": "Emerald Estate", "wall": "#f4efe4", "clad": "#2f4a36", "roof": "#2f4a36", "metal": "#b08a3e", "door": "#2f4a36"},
    {"id": "saffron", "name": "Saffron Courtyard", "wall": "#e8a54b", "clad": "#efe9dc", "roof": "#7a3b24", "metal": "#3a2c24", "door": "#55331d"},
    {"id": "basalt_brass", "name": "Basalt & Brass", "wall": "#3a3a38", "clad": "#59626b", "roof": "#2a2a26", "metal": "#b08a3e", "frame": "#b08a3e"},
    # From what Indian paint makers recommend now: soft pastels against white,
    # cream with brown, beige with dark trims, greige, olive, mustard and clay.
    {"id": "powder_blue", "name": "Powder Blue & White", "wall": "#c9d9e6", "clad": "#f4f2ee", "roof": "#59626b", "metal": "#efece6", "frame": "#efece6"},
    {"id": "mint_white", "name": "Mint & White", "wall": "#cfe3d4", "clad": "#f4f2ee", "roof": "#3d3f42", "metal": "#efece6", "frame": "#efece6"},
    {"id": "blush_white", "name": "Blush & White", "wall": "#ecd2cc", "clad": "#f4f2ee", "roof": "#6a5d55", "metal": "#efece6", "door": "#55331d"},
    {"id": "lemon_white", "name": "Pale Lemon", "wall": "#efe2a6", "clad": "#f4f2ee", "roof": "#7a3b24", "metal": "#3a2c24", "frame": "#efece6"},
    {"id": "cream_brown", "name": "Cream & Brown", "wall": "#efe3c8", "clad": "#6e4a2c", "roof": "#5a3a2a", "metal": "#5a3d2a", "frame": "#5e4a36", "door": "#3e2a1c"},
    {"id": "beige_espresso", "name": "Beige & Espresso", "wall": "#dccbb0", "clad": "#3e2f26", "roof": "#2f2d2b", "metal": "#2b2a29", "frame": "#2f2f30"},
    {"id": "greige", "name": "Greige & Taupe", "wall": "#cfc8bd", "clad": "#8b7f72", "roof": "#4a4846", "metal": "#2b2a29", "frame": "#2f2f30"},
    {"id": "olive_cream", "name": "Olive & Cream", "wall": "#efe6d0", "clad": "#6b6b3a", "roof": "#4a3f2a", "metal": "#4a4a2a", "door": "#4a4a2a"},
    {"id": "mustard_clay", "name": "Mustard & Clay", "wall": "#d9a93f", "clad": "#9c5a34", "roof": "#6a3a24", "metal": "#3a2c24", "door": "#2b3a52"},
    {"id": "slate_modern", "name": "Slate Modern", "wall": "#3f454b", "clad": "#d9d6cf", "roof": "#2a2d31", "metal": "#b08a3e", "frame": "#1c1b1a"},
    {"id": "seaside_white", "name": "Seaside White", "wall": "#f6f4f0", "clad": "#9fb3bb", "roof": "#2b3a52", "metal": "#2b3a52", "frame": "#2b3a52", "door": "#1f5a5e"},
)
#: The rest of each style's identity: how its windows are shaded, how it is
#: entered, what bounds its plot and how it is planted, how often it carries
#: planters or solar, and the colour schemes that belong to it. With
#: STYLE_BIAS this is the whole of a style; a design drawn from it reads as
#: that style from the street to the gate.
STYLE_DNA: dict[str, dict[str, Any]] = {
    "contemporary": {"windows": ("band", "punched"), "shade": ("slim", "box", "deep"), "canopy": ("slab", "glass"),
                     "railing": ("glass", "metal"), "boundary": ("plaster", "grille", "stone"), "gate": ("sliding",),
                     "paving": ("stone", "concrete"), "garden": ("standard", "minimal"), "planters": 0.35, "solar": 0.3,
                     "schemes": ("monsoon_grey", "charcoal_brass", "grey_oak", "warm_minimal", "white_black", "basalt_brass", "greige", "slate_modern")},
    "modern_minimal": {"windows": ("band",), "shade": ("none", "box"), "canopy": ("glass", "slab"), "railing": ("glass",),
                       "boundary": ("plaster", "grille"), "gate": ("sliding",), "paving": ("concrete", "gravel"),
                       "garden": ("minimal",), "planters": 0.15, "solar": 0.3,
                       "schemes": ("white_black", "warm_minimal", "nordic", "seaside_white", "greige", "powder_blue")},
    "tropical_modern": {"windows": ("band", "punched"), "shade": ("deep", "slim"), "canopy": ("pergola", "slab"),
                        "railing": ("metal", "glass"), "boundary": ("hedge", "stone"), "gate": ("timber",),
                        "paving": ("grass", "stone", "gravel"), "garden": ("lush",), "planters": 0.7, "solar": 0.3,
                        "schemes": ("lime_teak", "sage_oak", "forest_lodge", "olive_grove", "coastal", "mint_white", "olive_cream")},
    "kerala_vernacular": {"windows": ("punched",), "shade": ("deep",), "canopy": ("pergola", "slab"), "railing": ("solid", "metal"),
                          "boundary": ("stone", "hedge"), "gate": ("timber",), "paving": ("stone", "gravel", "grass"),
                          "garden": ("lush", "standard"), "planters": 0.5, "solar": 0.15,
                          "schemes": ("ochre_kerala", "lime_teak", "terracotta", "emerald", "cream_brown")},
    "traditional_indian": {"windows": ("punched",), "shade": ("slim", "deep"), "canopy": ("slab", "pergola"),
                           "railing": ("solid", "metal"), "boundary": ("stone", "plaster"), "gate": ("sliding", "timber"),
                           "paving": ("stone",), "garden": ("standard",), "planters": 0.4, "solar": 0.2,
                           "schemes": ("sandstone", "terracotta", "haveli_red", "saffron", "ochre_kerala", "cream_brown", "mustard_clay")},
    "chettinad": {"windows": ("punched",), "shade": ("slim",), "canopy": ("slab",), "railing": ("solid", "metal"),
                  "boundary": ("plaster", "stone"), "gate": ("timber",), "paving": ("stone",), "garden": ("standard",),
                  "planters": 0.3, "solar": 0.15, "schemes": ("chettinad_blue", "saffron", "pondicherry", "haveli_red", "lemon_white", "mustard_clay")},
    "rajasthani_haveli": {"windows": ("punched",), "shade": ("box", "slim"), "canopy": ("slab",), "railing": ("solid",),
                          "boundary": ("stone",), "gate": ("timber", "sliding"), "paving": ("stone",),
                          "garden": ("minimal", "standard"), "planters": 0.25, "solar": 0.2,
                          "schemes": ("jaipur_pink", "sandstone", "haveli_red", "jodhpur_blue", "desert_rose", "blush_white")},
    "indo_saracenic": {"windows": ("punched",), "shade": ("slim", "box"), "canopy": ("slab",), "railing": ("solid", "metal"),
                       "boundary": ("stone", "grille"), "gate": ("sliding",), "paving": ("stone",), "garden": ("standard",),
                       "planters": 0.3, "solar": 0.2, "schemes": ("sandstone", "mumbai_deco", "haveli_red", "desert_rose", "cream_brown")},
    "scandinavian": {"windows": ("punched", "band"), "shade": ("none",), "canopy": ("glass", "none"), "railing": ("metal", "glass"),
                     "boundary": ("hedge", "grille"), "gate": ("timber",), "paving": ("gravel",), "garden": ("minimal", "standard"),
                     "planters": 0.2, "solar": 0.4, "schemes": ("nordic", "white_black", "grey_oak", "seaside_white", "powder_blue", "greige")},
    "japandi": {"windows": ("punched", "band"), "shade": ("slim", "none"), "canopy": ("pergola",), "railing": ("metal",),
                "boundary": ("hedge", "plaster"), "gate": ("timber",), "paving": ("gravel", "stone"), "garden": ("minimal",),
                "planters": 0.3, "solar": 0.3, "schemes": ("warm_minimal", "grey_oak", "olive_grove", "sage_oak", "greige", "beige_espresso")},
    "industrial": {"windows": ("band",), "shade": ("box", "none"), "canopy": ("glass", "slab"), "railing": ("metal",),
                   "boundary": ("grille", "brick"), "gate": ("sliding",), "paving": ("concrete", "gravel"), "garden": ("minimal",),
                   "planters": 0.2, "solar": 0.4,
                   "schemes": ("concrete_raw", "charcoal_brass", "basalt_brass", "grey_oak", "clay_copper", "slate_modern")},
    "biophilic": {"windows": ("band", "punched"), "shade": ("deep",), "canopy": ("pergola",), "railing": ("metal", "glass"),
                  "boundary": ("hedge",), "gate": ("timber",), "paving": ("grass", "gravel"), "garden": ("lush",),
                  "planters": 0.9, "solar": 0.5, "schemes": ("sage_oak", "forest_lodge", "olive_grove", "emerald", "lime_teak", "mint_white")},
    "mid_century_modern": {"windows": ("band", "punched"), "shade": ("box", "slim"), "canopy": ("slab", "glass"),
                           "railing": ("metal",), "boundary": ("brick", "stone", "grille"), "gate": ("timber", "sliding"),
                           "paving": ("concrete", "stone"), "garden": ("standard",), "planters": 0.35, "solar": 0.25,
                           "schemes": ("warm_minimal", "clay_copper", "kutch_mud", "goa_villa", "mustard_clay", "olive_cream")},
}

for _k, _y in {"contemporary": ("sitout", "waterwall", "rockgarden", "lounge", "firepit", "fountain"),
               "modern_minimal": ("rockgarden", "waterwall", "lounge", "none"),
               "tropical_modern": ("koipond", "jhoola", "gazebo", "lounge", "flowerbeds"),
               "kerala_vernacular": ("tulsi", "jhoola", "koipond", "flowerbeds"),
               "traditional_indian": ("tulsi", "jhoola", "waterwall", "fountain", "flowerbeds"), "chettinad": ("tulsi", "jhoola", "flowerbeds"),
               "rajasthani_haveli": ("tulsi", "waterwall", "jhoola", "fountain"), "indo_saracenic": ("waterwall", "gazebo", "tulsi", "fountain"),
               "scandinavian": ("sitout", "rockgarden", "firepit"), "japandi": ("rockgarden", "koipond", "waterwall"),
               "industrial": ("sitout", "rockgarden", "firepit"), "biophilic": ("koipond", "gazebo", "jhoola", "flowerbeds"),
               "mid_century_modern": ("sitout", "koipond", "gazebo", "lounge", "firepit")}.items():
    STYLE_DNA[_k]["yard"] = _y

for _k, _v in {
    "contemporary": {"panel": ("stone", "acp", "timber", "slate"), "parapet": ("glass", "grooved", "plain"), "deck": ("pergola", "none"), "lights": ("strips", "washers")},
    "modern_minimal": {"panel": ("none", "acp", "slate"), "parapet": ("plain", "glass"), "deck": ("none",), "lights": ("strips", "none")},
    "tropical_modern": {"panel": ("timber", "stone", "terracotta"), "parapet": ("screen", "plain"), "deck": ("garden", "pergola"), "lights": ("washers",)},
    "kerala_vernacular": {"panel": ("none", "timber", "terracotta"), "parapet": ("plain",), "deck": ("none",), "lights": ("none", "washers")},
    "traditional_indian": {"panel": ("stone", "terracotta", "none"), "parapet": ("stepped", "screen", "grooved"), "deck": ("pergola", "none"), "lights": ("washers", "none")},
    "chettinad": {"panel": ("none", "terracotta"), "parapet": ("stepped", "grooved"), "deck": ("none",), "lights": ("washers", "none")},
    "rajasthani_haveli": {"panel": ("stone", "none"), "parapet": ("stepped", "screen"), "deck": ("none", "pergola"), "lights": ("washers",)},
    "indo_saracenic": {"panel": ("stone", "brick", "none"), "parapet": ("stepped", "grooved"), "deck": ("none",), "lights": ("washers", "none")},
    "scandinavian": {"panel": ("timber", "none"), "parapet": ("plain",), "deck": ("none",), "lights": ("none", "strips")},
    "japandi": {"panel": ("timber", "slate", "none"), "parapet": ("plain", "screen"), "deck": ("garden", "none"), "lights": ("strips", "none")},
    "industrial": {"panel": ("acp", "slate", "brick"), "parapet": ("plain", "glass"), "deck": ("pergola", "none"), "lights": ("strips",)},
    "biophilic": {"panel": ("timber", "stone", "terracotta"), "parapet": ("screen", "plain"), "deck": ("garden",), "lights": ("washers", "none")},
    "mid_century_modern": {"panel": ("brick", "stone", "timber"), "parapet": ("plain", "grooved"), "deck": ("pergola", "none"), "lights": ("washers", "strips")},
}.items():
    STYLE_DNA[_k].update(_v)

#: The client's own words, steering a batch: a word -> what it asks of the design.
#: A float is a likelihood (planters, solar); a tuple, the values to favour.
WORDS: tuple[tuple[str, dict[str, Any]], ...] = (
    (r"\b(wood|wooden|timber|teak)\b", {"upper": ("timber",), "base": ("timber", "stone"), "accent": ("teak", "bronze")}),
    (r"\bbrick", {"base": ("brick",), "upper": ("brick", "plaster")}),
    (r"\bstone|granite|sandstone", {"base": ("stone",), "boundary": ("stone",)}),
    (r"\bconcrete|brutalis", {"base": ("concrete",), "upper": ("concrete",)}),
    (r"\b(glass|glazing|glazed)\b", {"windows": ("band",), "railing": ("glass",), "canopy": ("glass",)}),
    (r"\b(glass (house|box|facade|walls?)|curtain wall|all glass)", {"upper": ("glass",), "base": ("stone", "concrete", "glass")}),
    (r"\b(corten|weathering steel|rust(ed|y)? steel)", {"upper": ("corten",), "panel": ("corten",), "base": ("concrete",)}),
    (r"\b(tile|tiled|sloped|sloping|pitched)\b", {"roof": ("hip", "gable")}),
    (r"\b(flat roof|terrace|roof garden)\b", {"roof": ("flat", "slab")}),
    (r"\b(minimal|minimalist|simple|clean)\b", {"screen": ("none", "frame"), "feature": ("none",), "shade": ("none", "box")}),
    (r"\b(green|garden|plants|greenery|nature|trees)\b", {"feature": ("greenwall", "none"), "garden": ("lush",), "planters": 0.85}),
    (r"\b(solar|sustainable|eco|green energy)\b", {"solar": 0.9, "roof": ("flat", "slab")}),
    (r"\b(traditional|heritage|classic|vintage)\b", {"feature": ("colonnade", "jharokha", "cornice"), "screen": ("jaali",)}),
    (r"\b(modern|contemporary|sleek)\b", {"roof": ("slab", "flat"), "screen": ("fins", "frame", "louvres")}),
    (r"\b(privacy|private)\b", {"screen": ("jaali", "perforated", "fins"), "boundary": ("stone", "brick", "plaster")}),
    (r"\bbalcon", {"feature": ("balcony",)}),
    (r"\b(white|light)\b", {"tone": ("ivory", "lime")}),
    (r"\b(dark|black|charcoal)\b", {"tone": ("charcoal",), "accent": ("charcoal", "graphite")}),
    (r"\b(earthy|terracotta|mud|clay)\b", {"tone": ("terracotta", "clay", "sand")}),
    (r"\bpink\b", {"tone": ("pink",)}),
    (r"\b(blue|indigo)\b", {"tone": ("indigo", "mist")}),
    (r"\b(yellow|ochre|gold)\b", {"tone": ("ochre", "haveli")}),
    (r"\b(acp|aluminium|aluminum|composite panel)", {"upper": ("acp",), "panel": ("acp",)}),
    (r"\b(hpl|wood finish|wood-look)", {"panel": ("timber",), "upper": ("timber",)}),
    (r"\bterracotta tile|clay tile|cladding tile", {"base": ("terracotta",), "panel": ("terracotta",)}),
    (r"\b(slate|granite)\b", {"panel": ("slate",), "base": ("slate", "stone")}),
    (r"\b(lighting|lights|lit up|glow)\b", {"lights": ("strips", "washers")}),
    (r"\bpergola", {"deck": ("pergola",), "canopy": ("pergola",), "roof": ("flat",)}),
    (r"\b(roof garden|terrace garden|rooftop garden)", {"deck": ("garden",), "roof": ("flat",)}),
    (r"\bglass (parapet|railing)", {"parapet": ("glass",), "railing": ("glass",)}),
    (r"\btulsi", {"yard": ("tulsi",)}),
    (r"\b(swing|jhoola|jhula)", {"yard": ("jhoola",)}),
    (r"\bfountain", {"yard": ("fountain",)}),
    (r"\b(water feature|water wall)", {"yard": ("waterwall",)}),
    (r"\b(fire ?pit|bonfire|fire place outside)", {"yard": ("firepit",)}),
    (r"\b(garden deck|sun ?deck|lounge|loungers|sun ?bath)", {"yard": ("lounge",)}),
    (r"\b(flowers?|flower ?beds?|blooms)\b", {"yard": ("flowerbeds",), "garden": ("lush",)}),
    (r"\b(koi|pond|lily pond)", {"yard": ("koipond",)}),
    (r"\bgazebo", {"yard": ("gazebo",)}),
    (r"\b(rock garden|zen garden|pebble)", {"yard": ("rockgarden",)}),
    (r"\b(sit-?out|garden seating|outdoor seating)", {"yard": ("sitout",)}),
)


def _wall_name(hex6: str) -> str:
    """The name of a wall colour, if it is one of the named paints or schemes."""
    if not hex6:
        return ""
    global _WALL_NAMES
    if not _WALL_NAMES:
        _WALL_NAMES = {h.lstrip("#"): n for n, h in PAINTS["wall"]}
        for sc in EXTERIOR_SCHEMES:
            _WALL_NAMES.setdefault(sc["wall"].lstrip("#"), sc["name"])
        for k, (h, _) in WALL_TONES.items():
            _WALL_NAMES.setdefault(h.lstrip("#"), k.title())
    return _WALL_NAMES.get(hex6, "").title()


_WALL_NAMES: dict[str, str] = {}


def heard(text: str | None) -> list[str]:
    """The words in the client's brief that steer the exterior, as they wrote them."""
    import re

    out: list[str] = []
    for pattern, _ in WORDS:
        m = re.search(pattern, text or "", re.IGNORECASE)
        word = m.group(0).lower() if m else ""
        # "garden" inside "roof garden" was heard once already.
        if word and not any(word in w or w in word for w in out):
            out.append(word)
    return out


def prefer_from_text(text: str | None) -> dict[str, Any]:
    """What the client's words ask of the exterior, as values to favour."""
    import re

    out: dict[str, Any] = {}
    for pattern, ask in WORDS:
        if text and re.search(pattern, text, re.IGNORECASE):
            for k, v in ask.items():
                if isinstance(v, float):
                    out[k] = max(out.get(k, 0.0), v)
                else:
                    out[k] = tuple(dict.fromkeys((*out.get(k, ()), *v)))
    # A roof terrace (a garden or a pergola up there) needs a flat parapet
    # roof, whatever else the words allow.
    if out.get("deck"):
        out["roof"] = ("flat",)
    return out


#: What each style tends towards for wall wash (fresh batches only).
TONE_BIAS = {"contemporary": ("lime", "mist", "charcoal", "ivory"), "modern_minimal": ("ivory", "lime", "charcoal"),
             "tropical_modern": ("lime", "sage", "clay"), "kerala_vernacular": ("lime", "ivory", "ochre"),
             "traditional_indian": ("ochre", "haveli", "terracotta", "pink"), "chettinad": ("ochre", "indigo", "pink"),
             "rajasthani_haveli": ("haveli", "pink", "sand"), "indo_saracenic": ("sand", "terracotta", "haveli"),
             "scandinavian": ("ivory", "charcoal", "mist"), "japandi": ("lime", "ivory", "mist"),
             "industrial": ("charcoal", "mist", "clay"), "biophilic": ("sage", "lime", "clay"),
             "mid_century_modern": ("sand", "ochre", "sage", "ivory")}
_HEX = set("0123456789abcdef")


def _hex6(v: Any) -> str:
    """A tint as 6 lowercase hex digits, or "" if it is not one."""
    v = str(v or "").strip().lstrip("#").lower()
    return v if len(v) == 6 and set(v) <= _HEX else ""


@dataclass(frozen=True, slots=True)
class Exterior:
    roof: str = "flat"
    base: str = "plaster"
    upper: str = "plaster"
    screen: str = "none"
    windows: str = "punched"
    planters: bool = False
    accent: str = "bronze"
    feature: str = "none"
    #: Exact tints (6 hex digits, no #); "" keeps the colour scheme's own.
    wall: str = ""
    clad: str = ""
    roof_tint: str = ""
    metal: str = ""
    frame: str = ""
    door: str = ""
    #: "" keeps the house's own: a plaster boundary wall, glass balustrades.
    boundary: str = ""
    railing: str = ""
    shade: str = ""
    canopy: str = ""
    gate: str = ""
    paving: str = ""
    garden: str = ""
    solar: str = ""
    panel: str = ""
    parapet: str = ""
    deck: str = ""
    lights: str = ""
    yard: str = ""
    garage: str = ""
    #: Colours a client painted on single parts, "key-hex.key-hex" (see PARTS).
    paints: str = ""

    @property
    def id(self) -> str:
        core = "ex:" + ".".join([self.roof, self.base, self.upper, self.screen, self.windows,
                                 "p" if self.planters else "n", self.accent, self.feature])
        tail = [f"{k}:{getattr(self, f)}" for k, f in COLOUR_KEYS.items() if getattr(self, f)]
        tail += [f"{k}:{getattr(self, f)}" for k, (f, _) in OPTION_KEYS.items() if getattr(self, f)]
        if self.paints:
            tail.append(f"z:{self.paints}")
        return f"{core}~{','.join(tail)}" if tail else core

    @property
    def form(self) -> tuple:
        """Everything but the tints: two designs with the same form are the same building."""
        return (self.roof, self.base, self.upper, self.screen, self.windows, self.planters, self.accent, self.feature)

    @classmethod
    def parse(cls, design_id: str | None) -> Exterior | None:
        if not design_id or not design_id.startswith("ex:"):
            return None
        core, _, tail = design_id[3:].partition("~")
        tints: dict[str, str] = {}
        for kv in filter(None, tail.split(",")):
            k, _, v = kv.partition(":")
            if k in COLOUR_KEYS and _hex6(v):
                tints[COLOUR_KEYS[k]] = _hex6(v)
            elif k in OPTION_KEYS and v in OPTION_KEYS[k][1]:
                tints[OPTION_KEYS[k][0]] = v
            elif k == "z":
                tints["paints"] = encode_paints(decode_paints(v))
        parts = core.split(".")
        if len(parts) == 7:
            parts.append("none")              # ids from before the signature element
        if len(parts) != 8:
            return None
        r, b, u, s, w, p, a, f = parts
        if r not in ROOFS or b not in BASES or u not in UPPERS or s not in SCREENS or w not in WINDOWS \
                or a not in ACCENTS or f not in FEATURES:
            return None
        return cls(r, b, u, s, w, p == "p", a, f, **tints)

    def fitted(self, one_floor: bool) -> tuple[Exterior, list[str]]:
        """This design made buildable on the plan, with a note per change: a
        customised design may ask for what the house cannot carry."""
        from dataclasses import replace

        e, notes = self, []
        if one_floor and e.upper != "plaster":
            e = replace(e, upper="plaster")
            notes.append("A single-storey house has no upper floor to clad.")
        if e.feature in ("jharokha", "balcony", "bay", "floatbox", "cornerglass", "cantilever", "planterbands") and one_floor:
            notes.append(f"A {NAMES[e.feature].lower()} needs an upper floor; it is left off.")
            e = replace(e, feature="none")
        if e.deck and e.roof != "flat":
            notes.append("A terrace pergola or garden needs a flat parapet roof; it is left off.")
            e = replace(e, deck="")
        if e.parapet and e.roof != "flat":
            e = replace(e, parapet="")
        if e.solar == "on" and e.roof not in ("flat", "slab"):
            notes.append("Solar panels sit on a flat or slab roof; they are left off this one.")
            e = replace(e, solar="")
        if e.feature == "rooftopframe" and e.roof not in ("flat", "slab"):
            notes.append("A crown frame stands on a flat or slab roof; the roof is set to flat.")
            e = replace(e, roof="flat")
        if e.feature in ("chhatri", "bangla") and e.roof != "flat":
            notes.append(f"A {NAMES[e.feature].lower()} pavilion stands on a flat parapet roof; the roof is set to flat.")
            e = replace(e, roof="flat")
        return e, notes

    def name(self) -> str:
        bits = [NAMES[self.feature] if self.feature != "none" else
                (NAMES[self.upper] if self.upper != "plaster" else NAMES[self.base]),
                NAMES[self.screen] if self.screen != "none" else "", NAMES[self.roof]]
        # A wall in a named colour leads the name and stands in for the roof,
        # so two houses differing in colour do not share one.
        tone = _wall_name(self.wall)
        if tone:
            bits = [tone, *bits[:2]]
        return " ".join(b for b in bits if b) + " House"

    def story(self) -> str:
        roof = {"flat": "a parapet roof terrace", "slab": "a thin cantilevered roof slab", "mono": "a single-pitch roof over a clerestory",
                "butterfly": "a butterfly roof", "hip": "a hipped tile roof on deep eaves", "gable": "a pitched gable roof",
                "vault": "a barrel-vaulted roof", "sawtooth": "a sawtooth roof of north lights"}[self.roof]
        base = {"plaster": "a lime-plaster ground floor", "stone": "a stone-clad ground floor", "brick": "an exposed-brick ground floor",
                "concrete": "a board-marked concrete ground floor", "timber": "a timber-boarded ground floor",
                "metal": "a dark metal-clad ground floor", "terracotta": "a terracotta-tiled ground floor",
                "acp": "an aluminium-panelled ground floor", "slate": "a stacked-slate ground floor",
                "glass": "a glass-walled ground floor", "corten": "a weathering-steel ground floor"}[self.base]
        upper = {"plaster": "plastered floors above", "timber": "timber-boarded floors above", "metal": "dark metal-clad floors above",
                 "brick": "brick floors above", "stone": "stone-clad floors above",
                 "concrete": "board-marked concrete floors above", "terracotta": "terracotta-tiled floors above",
                 "acp": "aluminium-panelled floors above", "slate": "stacked-slate floors above",
                 "glass": "a glass curtain wall above", "corten": "corten-clad floors above"}[self.upper]
        screen = {"none": "", "fins": ", vertical fins shading the street face", "louvres": ", horizontal louvres across the street face",
                  "frame": ", a deep frame around the upper floor", "jaali": ", a jaali screen against the hard sun",
                  "perforated": ", a perforated metal screen", "slats": ", close timber slats veiling the street face",
                  "bamboo": ", a screen of bamboo poles"}[self.screen]
        win = ", glazing in continuous bands" if self.windows == "band" else ""
        plant = ", planters along the edges" if self.planters else ""
        if self.yard and self.yard != "none":
            from aip.engines.experience.landscape import YARD_NAMES

            name = YARD_NAMES[self.yard]
            plant += f", {name if name.endswith('s') else 'a ' + name} in the garden"
        feat = {"none": "", "jharokha": ", jharokha bays projecting over the street",
                "colonnade": ", a colonnaded verandah along the front", "chhatri": ", chhatri pavilions on the roof",
                "cornice": ", deep cornices marking every floor", "breeze": ", a breeze-block screen wall",
                "greenwall": ", a planted green wall", "balcony": ", cantilevered balconies over the street",
                "arcade": ", an arcade of arches along the front", "portico": ", a double-height portico at the door",
                "bay": ", projecting bay windows",
                "floatbox": ", a deep framed box floating off the upper floor",
                "featurewall": ", a monolith wall rising the full height of the front",
                "thinnai": ", thinnai platforms flanking the door under a tiled lean-to",
                "bangla": ", a bangla-roofed pavilion on the terrace",
                "pergolaframe": ", a double-height timber pergola standing off the front",
                "cornerglass": ", the upper corner opened in glass",
                "brickcurtain": ", a perforated brick curtain across the front",
                "wavescreen": ", a rippling perforated screen across the front",
                "moongate": ", a square screen with a round moon-gate opening",
                "cantilever": ", a first-floor room cantilevered over the porch",
                "flutedbands": ", full-height fluted bands framing the front",
                "brisesoleil": ", a deep egg-crate brise-soleil",
                "planterbands": ", planter bands spilling green at every floor",
                "rooftopframe": ", a thin concrete frame crowning the roof"}[self.feature]
        # Say which way this design draws its signature element.
        if self.feature != "none":
            tr = traits(self)
            word = {"colonnade": WORD["column"][tr["column"]], "portico": WORD["column"][tr["column"]],
                    "arcade": WORD["arch"][tr["arch"]], "jharokha": WORD["canopy"][tr["canopy"]],
                    "chhatri": WORD["canopy"]["dome" if tr["canopy"] == "flat" else tr["canopy"]]}.get(self.feature)
            if word:
                feat = feat.replace(", a ", f", a {word} ", 1).replace(", an ", f", a {word} ", 1).replace(", jharokha", f", {word} jharokha", 1).replace(", chhatri", f", {word} chhatri", 1)
        return f"{base[0].upper()}{base[1:]}, {upper}{screen}{feat}{win}{plant}, under {roof}."

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["colours"] = {f: (f"#{d.pop(f)}" if d[f] else "") for f in COLOUR_KEYS.values()}
        d["paints"] = {k: f"#{v}" for k, v in decode_paints(self.paints).items()}
        return {"id": self.id, "name": self.name(), "story": self.story(), **d}


#: How much each choice changes what a passer-by sees, for keeping a batch far apart.
_WEIGHT = {"roof": 3.0, "feature": 2.5, "screen": 2.0, "upper": 1.5, "base": 1.2, "windows": 0.6,
           "planters": 0.4, "accent": 0.8, "wall": 1.5, "roof_tint": 0.6, "shade": 0.6, "canopy": 0.5,
           "boundary": 0.6, "gate": 0.3, "paving": 0.3, "garden": 0.4, "solar": 0.5, "panel": 1.2, "parapet": 0.8,
           "deck": 0.7, "lights": 0.4, "yard": 0.6}


def distance(a: Exterior, b: Exterior) -> float:
    return sum(w for k, w in _WEIGHT.items() if getattr(a, k) != getattr(b, k))


def combinations() -> int:
    """How many different exteriors the grammar can make: every form, every
    site and detail option, and a named paint or scheme on each surface."""
    n = len(ROOFS) * len(BASES) * len(UPPERS) * len(SCREENS) * len(WINDOWS) * 2 * len(ACCENTS) * len(FEATURES)
    for _field, vocab in OPTION_KEYS.values():
        n *= len(vocab)
    for surface in PAINTS.values():
        n *= len(surface) + 1                     # each paint, or the design's own
    return n


def decode_paints(v: str) -> dict[str, str]:
    """"compound-8a8a8a.gate-7a4b2a" -> {"compound": "8a8a8a", ...}, known parts only."""
    out: dict[str, str] = {}
    for item in filter(None, (v or "").split(".")):
        key, _, hx = item.rpartition("-")
        if key in PARTS and _hex6(hx):
            out[key] = _hex6(hx)
    return out


def encode_paints(paints: dict[str, str]) -> str:
    """The canonical form: parts in PARTS order, so equal paints give equal ids."""
    return ".".join(f"{k}-{_hex6(paints[k])}" for k in PARTS if k in paints and _hex6(paints[k]))


def with_paints(ex: Exterior, changes: dict[str, str | None]) -> Exterior:
    """The design with some parts repainted (a hex) or returned to the design's own (None)."""
    from dataclasses import replace

    cur = decode_paints(ex.paints)
    for k, v in changes.items():
        if k not in PARTS:
            continue
        if v is None:
            cur.pop(k, None)
        elif _hex6(v):
            cur[k] = _hex6(v)
    return replace(ex, paints=encode_paints(cur))


def grammar() -> dict[str, Any]:
    """The vocabulary a client can customise with, labelled."""
    parts = [{"key": k, "label": lab, "group": grp} for k, (lab, grp, _w) in PARTS.items()]
    return {"parts": parts, "combinations": combinations(), "roof": list(ROOFS), "base": list(BASES), "upper": list(UPPERS), "screen": list(SCREENS),
            "windows": list(WINDOWS), "feature": list(FEATURES), "accents": ACCENTS,
            "tones": {k: v[0] for k, v in WALL_TONES.items()}, "labels": NAMES, "schemes": list(EXTERIOR_SCHEMES),
            "boundary": list(BOUNDARIES), "railing": list(RAILINGS), "shade": list(SHADES), "canopy": list(CANOPIES),
            "gate": list(GATES), "paving": list(PAVINGS), "garden": list(GARDENS), "solar": list(SOLAR),
            "panel": list(PANELS), "parapet": list(PARAPETS), "deck": list(DECKS), "lights": list(LIGHTS),
            "yard": list(YARDS),
            "paints": {k: [{"name": n, "hex": h} for n, h in v] for k, v in PAINTS.items()},
            "styles": [{"id": k, "name": STYLE_NAMES.get(k, k.replace("_", " ").title()),
                        "schemes": list(STYLE_DNA.get(k, {}).get("schemes", ()))} for k in STYLE_BIAS]}


STYLE_NAMES = {"contemporary": "Contemporary", "modern_minimal": "Minimal", "tropical_modern": "Tropical", "kerala_vernacular": "Kerala",
               "traditional_indian": "Traditional", "chettinad": "Chettinad", "rajasthani_haveli": "Haveli",
               "indo_saracenic": "Indo-Saracenic", "scandinavian": "Scandinavian", "japandi": "Japandi", "industrial": "Industrial",
               "biophilic": "Biophilic", "mid_century_modern": "Mid-century"}


def generate(plan: FloorPlan, n: int = 10, prefer: dict[str, Any] | None = None,
             seed: int | str | None = None, avoid: set[str] | None = None,
             style: str | None = None, taken: set[str] | None = None) -> list[Exterior]:
    """A varied set of designs for this plan, drawn from a style's whole
    identity (roof to gate) and steered by what the client asked for
    (`prefer`, e.g. from `prefer_from_text`), then spread as far apart as the
    grammar allows so no two read alike.

    Without `seed` the set is the plan's own, the same every time. A seed gives
    a fresh batch, coloured from the style's own schemes and wall washes;
    `avoid` holds ids already shown, so a batch never repeats one; `taken`,
    designs other houses have claimed, whose building forms it never offers.
    """
    fresh = seed is not None
    key = f"{plan.id or 'x'}:{seed}:{style or ''}" if fresh else (plan.id or "x")
    rng = random.Random(int(hashlib.sha1(key.encode()).hexdigest()[:12], 16))
    asked = style in STYLE_BIAS
    # A style asked for leads the batch; otherwise the plan's own.
    style = style if asked else (plan.style if plan.style in STYLE_BIAS else "contemporary")
    bias: dict[str, Any] = {**STYLE_DNA.get(style, STYLE_DNA["contemporary"]), **STYLE_BIAS[style]}
    bias.setdefault("tone", TONE_BIAS.get(style, TONE_BIAS["contemporary"]))
    # The client's words win over the style where they speak.
    for k, v in (prefer or {}).items():
        if v:
            bias[k] = v if isinstance(v, float) else tuple(v)
    one_floor = len(plan.levels) <= 1
    n = max(1, min(int(n), 60))
    # An asked-for style holds its line; the house's own batch strays more,
    # so batch after batch keeps surprising.
    lead = 0.9 if asked else (0.78 if fresh else 0.85)

    def pick(key: str, pool: tuple[str, ...]) -> str:
        fav = [x for x in bias.get(key, ()) if x in pool]
        # What the client named holds firmer than what the style leans to.
        hold = 0.97 if prefer and prefer.get(key) else lead
        return rng.choice(fav) if fav and rng.random() < hold else rng.choice(pool)

    def option(key: str, vocab: tuple[str, ...]) -> str:
        v = pick(key, vocab)
        return "" if v == vocab[0] else v           # the house's own value stays out of the id

    schemes = [x for x in EXTERIOR_SCHEMES if x["id"] in bias.get("schemes", ())]
    shown = [e for e in (Exterior.parse(i) for i in (avoid or ())) if e is not None]
    shown_forms = {e.form for e in shown} | {e.form for e in (Exterior.parse(i) for i in (taken or ())) if e is not None}
    pool: list[Exterior] = []
    forms: set[tuple] = set()
    tries = 0
    while len(pool) < n * 6 and tries < n * 60:
        tries += 1
        roof = pick("roof", ROOFS)
        e = Exterior(
            roof=roof,
            base=pick("base", BASES),
            upper="plaster" if one_floor else pick("upper", UPPERS),
            screen=pick("screen", SCREENS),
            windows=pick("windows", WINDOWS),
            planters=rng.random() < float(bias.get("planters", 0.35)),
            accent=pick("accent", tuple(ACCENTS)),
            feature=pick("feature", FEATURES),
            boundary=option("boundary", BOUNDARIES), railing=option("railing", RAILINGS),
            shade=option("shade", SHADES), canopy=option("canopy", CANOPIES), gate=option("gate", GATES),
            paving=option("paving", PAVINGS), garden=option("garden", GARDENS),
            solar="on" if roof in ("flat", "slab") and rng.random() < float(bias.get("solar", 0.2)) else "",
            panel=option("panel", PANELS), lights=option("lights", LIGHTS), yard=option("yard", YARDS),
            parapet=option("parapet", PARAPETS) if roof == "flat" else "",
            deck=option("deck", DECKS) if roof == "flat" else "",
        )
        if fresh:
            tints = _colours(rng, bias, schemes, e.roof, "tone" in (prefer or {}), strict=asked)
            e = Exterior(**{**asdict(e), **tints})
        if not _harmonious(e, one_floor) or e.form in forms or e.form in shown_forms:
            continue
        forms.add(e.form)
        pool.append(e)
    # How far a design strays from its style: the parts a passer-by reads it
    # by, outside the style's own vocabulary; the roof and the signature
    # element read first, so they count double. An asked-for style keeps only
    # designs that stray at most a little, while it has enough of them.
    def strays(e: Exterior) -> int:
        return sum(2 if k in ("roof", "feature") else 1 for k in ("roof", "screen", "feature", "base", "upper")
                   if bias.get(k) and not isinstance(bias[k], float) and getattr(e, k) not in bias[k]
                   and not (k == "upper" and one_floor))

    if asked:
        close = [e for e in pool if strays(e) <= 1]
        pool = close if len(close) >= n else pool
    pool.sort(key=strays)
    # Farthest-point selection: each next design is the one least like any
    # chosen (or already shown), less what it strays from the style, so
    # variety never comes from leaving the style. The first is the most in-style.
    out: list[Exterior] = pool[:1]
    rest = pool[1:]
    while rest and len(out) < n:
        near = [min((distance(c, x) for x in [*out, *shown]), default=99.0) - 2.5 * strays(c) for c in rest]
        i = max(range(len(rest)), key=lambda j: (near[j], -j))
        out.append(rest.pop(i))
    return out


def with_style_details(e: Exterior, style: str | None) -> Exterior:
    """Fill what a design leaves open (shades, canopy, railings, boundary,
    gate, drive, garden) from its style, the same way every time for the same
    design, so a designer's sketch arrives dressed to the gate."""
    from dataclasses import replace

    dna = STYLE_DNA.get(style or "", STYLE_DNA["contemporary"])
    rng = random.Random(int(hashlib.sha1(f"{e.id}:{style}".encode()).hexdigest()[:12], 16))
    fill = {}
    for key, (field, vocab) in OPTION_KEYS.items():
        if getattr(e, field) or field == "solar":
            continue
        fav = [v for v in dna.get(field, ()) if v in vocab]
        v = rng.choice(fav) if fav else vocab[0]
        fill[field] = "" if v == vocab[0] else v
    return replace(e, **fill)


def _colours(rng: random.Random, bias: dict[str, Any], schemes: list[dict[str, str]], roof: str,
             tone_asked: bool, strict: bool = False) -> dict[str, str]:
    """A fresh design's colours: most often one of its style's own schemes
    whole, otherwise a wall wash of the style with a roof tone that suits it.
    A colour the client named always leads."""
    if schemes and not tone_asked and rng.random() < 0.6:
        sc = rng.choice(schemes)
        return {"wall": sc["wall"].lstrip("#"), "clad": sc["clad"].lstrip("#"), "roof_tint": sc["roof"].lstrip("#"),
                "metal": sc["metal"].lstrip("#"), "frame": sc.get("frame", "").lstrip("#"), "door": sc.get("door", "").lstrip("#")}
    tones = [t for t in bias.get("tone", ()) if t in WALL_TONES] or list(WALL_TONES)
    # An asked-for style keeps to its own washes; the house's own batch now
    # and then tries another.
    wall, roofs = WALL_TONES[rng.choice(tones) if strict or rng.random() < 0.85 else rng.choice(list(WALL_TONES))]
    return {"wall": wall.lstrip("#"),
            "roof_tint": rng.choice(roofs).lstrip("#") if roof in ("hip", "gable", "mono", "butterfly") else ""}


def _harmonious(e: Exterior, one_floor: bool) -> bool:
    """Combinations an architect would not draw."""
    if e.roof in ("hip", "gable") and e.screen == "perforated":
        return False
    if e.base == e.upper == "brick" and e.screen == "jaali":
        return False
    if e.feature == "chhatri" and e.roof != "flat":
        return False                         # chhatris stand on a flat roof
    if e.feature in ("jharokha", "balcony", "bay", "floatbox", "cornerglass", "cantilever", "planterbands") and one_floor:
        return False
    if e.feature == "rooftopframe" and e.roof not in ("flat", "slab"):
        return False
    if e.feature == "bangla" and e.roof != "flat":
        return False
    if e.roof in ("vault", "sawtooth") and e.feature == "chhatri":
        return False
    if e.base in ("metal", "glass") and e.upper in ("stone", "brick", "slate", "terracotta"):
        return False                         # the heavy skin goes below the light one
    if e.base == e.upper == "glass" and e.roof in ("hip", "gable", "vault"):
        return False                         # an all-glass house carries a flat plate, not a tiled roof
    if e.base == "timber" and e.upper == "stone":
        return False
    if e.roof in ("hip", "gable") and e.base == e.upper == "metal":
        return False
    return True


# ---------------------------------------------------------------------------
# Building it
# ---------------------------------------------------------------------------

def skins(ex: Exterior, n_levels: int) -> dict[int, str]:
    """The wall material of each floor's outside face."""
    out = {}
    for i in range(n_levels):
        skin = ex.base if i == 0 else ex.upper
        if skin in SKIN:
            out[i] = SKIN[skin]
    return out


def door_spans(level, e: Edge, margin: float = 0.45, windows: bool = False) -> list[tuple[float, float]]:
    """Where along an outside edge its doors are, as fractions of the edge,
    widened by a margin: nothing a facade adds may stand in a doorway."""
    L = e.length
    if L < 1e-6:
        return []
    out = []
    d = e.dir
    for w in getattr(level, "walls", []):
        doors = [o for o in w.openings if windows or o.kind.is_door or o.kind.value in ("french_window", "sliding_door")]
        if not doors:
            continue
        a, c = Vec2(w.start.x, w.start.y), Vec2(w.end.x, w.end.y)
        # On this edge's line: both ends within a wall's thickness of it.
        n = Vec2(-d.y, d.x)
        if abs((a - e.a).dot(n)) > 0.3 or abs((c - e.a).dot(n)) > 0.3:
            continue
        for o in doors:
            p = a + (c - a) * o.position
            t = (p - e.a).dot(d) / L
            half = (o.width / 2 + margin + (0.35 if o.kind.value == "main_door" else 0.0)) / L
            out.append((t - half, t + half))
    return out


def clear(t0: float, t1: float, spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The parts of [t0, t1] that stay clear of every span."""
    parts = [(t0, t1)]
    for a, b in spans:
        nxt = []
        for x, y in parts:
            if b <= x or a >= y:
                nxt.append((x, y))
                continue
            if a > x:
                nxt.append((x, a))
            if b < y:
                nxt.append((b, y))
        parts = nxt
    return [(x, y) for x, y in parts if y - x > 1e-3]


def _free(t: float, half: float, spans) -> bool:
    return all(t + half <= a or t - half >= b for a, b in spans)


def _box(b, node, mat, p: Vec2, y: float, size, yaw: float) -> None:
    b.box(node, mat, (p.x, y, -p.y), size, yaw)


def _yaw(e: Edge) -> float:
    return math.atan2(e.dir.y, e.dir.x)


SKIN = {"stone": "clad", "brick": "ex_brick", "concrete": "ex_concrete", "timber": "ex_timber", "metal": "ex_metal",
        "terracotta": "ex_terracotta", "acp": "ex_acp", "slate": "ex_slate", "glass": "ex_curtain", "corten": "ex_corten"}
#: A feature panel's finish: the skin it copies, and a name the viewer reads its texture by.
PANEL_FINISH = {"stone": ("clad", "panel_stone_cladding"), "timber": ("ex_timber", "panel_timber_boards"),
                "slate": ("ex_slate", "panel_slate_stack"), "terracotta": ("ex_terracotta", "panel_terracotta_tile"),
                "acp": ("ex_acp", "panel_acp_panel"), "brick": ("ex_brick", "panel_brick"),
                "corten": ("ex_corten", "panel_corten_steel")}


def recolour(palette, ex: Exterior) -> None:
    """Lay the design's exact tints over the colour scheme: walls, the
    cladding of whichever skins it uses, the roof and the accent metal."""
    m = palette.m

    def tint(key: str, hex_: str) -> None:
        if key in m:
            old = m[key]
            m[key] = old.__class__(old.name, _rgb(hex_), old.roughness, old.metallic, old.alpha, old.emissive)

    if ex.wall:
        tint("plaster", ex.wall)
    if ex.clad:
        for skin in {ex.base, ex.upper} - {"plaster"} - SELF_COLOURED or {"stone"}:
            tint(SKIN[skin], ex.clad)
    if ex.roof_tint:
        for key in ("roof_tile", "roof_flat", "ex_roof"):
            tint(key, ex.roof_tint)
    if ex.metal:
        tint("rail_metal", ex.metal)
    if ex.frame:
        tint("frame", ex.frame)
    if ex.door:
        tint("main_door", ex.door)
    # The boundary wall takes a finish of its own, named for the texture it wears.
    if ex.boundary in ("stone", "brick"):
        src = m["clad"] if ex.boundary == "stone" else m["ex_brick"]
        m["compound"] = src.__class__(f"compound_{ex.boundary}", src.rgb, src.roughness)
    palette.boundary = ex.boundary
    palette.railing = ex.railing
    palette.shade, palette.canopy, palette.gate = ex.shade, ex.canopy, ex.gate
    palette.garden, palette.solar = ex.garden, ex.solar == "on"
    palette.parapet, palette.deck, palette.lights = ex.parapet, ex.deck, ex.lights
    palette.yard = ex.yard
    palette.garage = ex.garage
    if ex.deck == "pergola":
        palette.pergola = True
    elif ex.deck:
        palette.pergola = False
    if ex.panel in PANEL_FINISH:
        src, name = PANEL_FINISH[ex.panel]
        m["ex_panel"] = m[src].__class__(name, m[src].rgb, m[src].roughness, m[src].metallic)
    # Last, whatever the client painted part by part.
    for key, hex_ in decode_paints(ex.paints).items():
        tint(key, hex_)
    # The drive's surface, named for the texture it wears.
    pave = {"concrete": ("paving_concrete", "#a9a7a1"), "gravel": ("gravel", "#b7aa94"), "grass": ("grass_pavers", "#6f8a4f")}
    if ex.paving in pave:
        name, hex_ = pave[ex.paving]
        m["paving"] = m["paving"].__class__(name, _rgb(hex_), 0.95)


def apply(b, plan: FloorPlan, ex: Exterior, levels: list[tuple[Any, float, Any]], road: Vec2 | None,
          roof_y: float) -> dict[str, Any]:
    """Dress the house in the design; return the roof the builder should draw."""
    street = lambda e: road is None or e.out.dot(road) > 0.6  # noqa: E731
    b.p.m["ex_accent"] = b.p.m["frame"].__class__("exterior_accent", _rgb(ex.metal or ACCENTS[ex.accent]),
                                                  0.45 if ex.metal else 0.5, 0.55 if ex.metal else 0.3)
    n = len(levels)
    for li, (level, base, fp) in enumerate(levels):
        h = level.floor_to_floor
        node = f"level_{level.index}/facade"
        skin = ex.base if li == 0 else ex.upper
        for e in edges(fp):
            L, yaw = e.length, _yaw(e)
            spans = door_spans(level, e)
            # A slab band between floors marks each storey on the skin.
            if li > 0 and skin != "plaster":
                _box(b, node, "slab", e.at(0.5, 0.06), base - 0.08, (L + 0.12, 0.16, 0.1), yaw)
            if ex.windows == "band" and street(e) and L > 2.5:
                # The glazing band stops either side of a door; it never covers one.
                for t0, t1 in clear(0.07, 0.93, spans):
                    if (t1 - t0) * L > 0.8:
                        _box(b, node, "ex_glassband", e.at((t0 + t1) / 2, 0.06), base + 1.55, ((t1 - t0) * L, 1.2, 0.04), yaw)
            if skin == "glass" and L > 1.2:
                _curtain(b, node, e, L, yaw, base, h, spans)
            upper = li >= 1 or n == 1
            if upper and street(e):
                _screen(b, node, ex.screen, e, L, yaw, base, h, spans, ground=li == 0)
            if ex.planters and li == 0 and street(e) and L > 3:
                for t in (0.18, 0.82):
                    if not _free(t, 0.9 / L, spans):
                        continue               # never a planter in front of a door
                    p = e.at(t, 0.55)
                    _box(b, node, "ex_concrete", p, base + 0.25, (1.2, 0.5, 0.5), yaw)
                    b.blob(node, "leaf", (p.x, base + 0.62, -p.y), 0.34, 0.8)
        if li == n - 1 and ex.planters and ex.roof in ("flat", "slab"):
            for e in edges(fp):
                if street(e) and e.length > 3:
                    p = e.at(0.5, -0.35)
                    _box(b, "roof", "ex_concrete", p, roof_y + 0.22, (min(3.0, e.length * 0.5), 0.4, 0.4), _yaw(e))
                    b.blob("roof", "leaf", (p.x, roof_y + 0.55, -p.y), 0.3, 0.7)
    _feature(b, ex, levels, street, roof_y)
    _panel(b, ex, levels, street)
    _lights(b, ex, levels, street, roof_y)
    return {"roof": {"flat": "flat", "slab": "slab", "mono": "pitch", "butterfly": "butterfly", "hip": "hip", "gable": "gable",
                     "vault": "vault", "sawtooth": "sawtooth"}[ex.roof]}


def _curtain(b, node: str, e: Edge, L: float, yaw: float, base: float, h: float, spans) -> None:
    """A glass curtain wall's frame: slim mullions about every 1.25 m, kept off
    the doors, and a transom at the slab so each storey reads behind the glass."""
    n = max(1, round(L / 1.25))
    for k in range(n + 1):
        t = k / n
        if 0.0 < t < 1.0 and not _free(t, 0.08 / L, spans):
            continue
        _box(b, node, "frame", e.at(t, 0.05), base + h / 2, (0.06, h, 0.1), yaw)
    for y in (base + 0.05, base + h - 0.12):
        _box(b, node, "frame", e.at(0.5, 0.05), y, (L, 0.08, 0.1), yaw)


# ---------------------------------------------------------------------------
# Signature elements, each in the character of its design
# ---------------------------------------------------------------------------

def _pick(ex: Exterior, key: str, options: tuple):
    """A stable choice for this design: the same design always draws the same
    way, but no two designs need share one. Tints do not change the shape."""
    h = int(hashlib.sha1(f"{ex.form}:{key}".encode()).hexdigest()[:8], 16)
    return options[h % len(options)]


def traits(ex: Exterior) -> dict[str, Any]:
    """How this design's signature element is drawn, read from its materials
    and roof: the family its detailing belongs to, then a variation within it."""
    timber = "timber" in (ex.base, ex.upper) or ex.roof in ("hip", "gable")
    masonry = ex.base in ("stone", "brick", "terracotta") or ex.screen == "jaali"
    family = "timber" if timber and not masonry else "masonry" if masonry else "modern"
    column = _pick(ex, "column", {"timber": ("timber", "bracketed"), "masonry": ("round", "twin", "octagonal"),
                                  "modern": ("square", "steel")}[family])
    arch = _pick(ex, "arch", {"timber": ("segmental", "round"), "masonry": ("round", "pointed", "scalloped"),
                              "modern": ("segmental", "lintel")}[family])
    canopy = _pick(ex, "canopy", {"timber": ("pyramid", "bangla"), "masonry": ("dome", "bangla", "pyramid"),
                                  "modern": ("flat", "pyramid")}[family])
    frame = _pick(ex, "frame", ("ex_accent", "skin", "ex_accent"))
    return {"family": family, "column": column, "arch": arch, "canopy": canopy,
            "bay": _pick(ex, "bay", (2.2, 2.6, 3.0)), "count": _pick(ex, "count", (1, 2, 3, 4)),
            "cornice": _pick(ex, "cornice", ("single", "double", "dentil")),
            "frame": SKIN.get(ex.upper, "plaster") if frame == "skin" else "ex_accent"}


WORD = {"column": {"timber": "timber-post", "bracketed": "bracketed", "round": "round-column", "twin": "twin-column",
                   "octagonal": "octagonal-column", "square": "square-pier", "steel": "steel-column"},
        "arch": {"round": "round-arched", "pointed": "pointed-arch", "scalloped": "scalloped-arch",
                 "segmental": "segmental-arch", "lintel": "flat-lintel"},
        "canopy": {"dome": "domed", "bangla": "bangla-roofed", "pyramid": "pyramid-roofed", "flat": "flat-roofed"}}


def _column(b, node: str, kind: str, p: Vec2, y0: float, height: float, yaw: float) -> None:
    """One column of the given kind standing at p from y0."""
    if kind in ("timber", "bracketed"):
        _box(b, node, "plinth", p, y0 + 0.12, (0.34, 0.24, 0.34), yaw)
        b.cylinder(node, "timber", (p.x, y0 + 0.24, -p.y), 0.1, height - 0.24, 12)
        if kind == "bracketed":
            for s_ in (-1, 1):
                q = p + Vec2(math.cos(yaw), math.sin(yaw)) * (s_ * 0.22)
                _box(b, node, "timber", q, y0 + height - 0.2, (0.36, 0.12, 0.14), yaw)
        return
    if kind == "steel":
        b.cylinder(node, "rail_metal", (p.x, y0, -p.y), 0.06, height, 10)
        return
    if kind == "square":
        _box(b, node, "plaster", p, y0 + height / 2, (0.32, height, 0.32), yaw)
        return
    if kind == "twin":
        for s_ in (-1, 1):
            q = p + Vec2(math.cos(yaw), math.sin(yaw)) * (s_ * 0.13)
            b.cylinder(node, "plaster", (q.x, y0 + 0.1, -q.y), 0.08, height - 0.2, 12)
    else:
        b.cylinder(node, "plaster", (p.x, y0 + 0.1, -p.y), 0.15, height - 0.2, 8 if kind == "octagonal" else 16)
    # A base and a capital: what makes a masonry column read as one.
    _box(b, node, "slab", p, y0 + 0.05, (0.46, 0.1, 0.46), yaw)
    _box(b, node, "slab", p, y0 + height - 0.06, (0.46, 0.12, 0.46), yaw)


def _arch(b, node: str, kind: str, e: Edge, ta: float, tb: float, off: float, top: float, yaw: float) -> None:
    """An arch across one bay [ta, tb] of edge e, its crown just under `top`."""
    span = (tb - ta) * e.length
    if span < 0.9:
        return
    mid = e.at((ta + tb) / 2, off)
    half = span / 2 - 0.2
    if kind == "lintel":
        _box(b, node, "plaster", mid, top - 0.2, (span, 0.4, 0.3), yaw)
        return
    rise = {"segmental": half * 0.45, "pointed": half * 1.25}.get(kind, half)
    spring = top - 0.25 - rise
    steps = 15
    for j in range(steps + 1):
        x = -half + 2 * half * j / steps
        if kind == "pointed":
            y = rise * (1 - abs(x) / half) ** 0.7
        elif kind == "segmental":
            y = rise * (1 - (x / half) ** 2)
        else:
            y = math.sqrt(max(0.0, half * half - x * x)) * rise / half
            if kind == "scalloped":
                y -= 0.07 * abs(math.sin(6 * math.pi * j / steps))
        q = mid + e.dir * x
        _box(b, node, "plaster", q, spring + y, (2 * half / steps + 0.06, 0.14, 0.3), yaw)
    # The spandrel over the arch, up to the beam.
    _box(b, node, "plaster", mid, top - 0.12, (span, 0.24, 0.3), yaw)


def _cap(b, node: str, kind: str, c: Vec2, y: float, w: float, d: float, yaw: float) -> None:
    """A canopy w x d whose underside is at y: dome, bangla, pyramid or flat."""
    if kind == "flat":
        _box(b, node, "ex_accent", c, y + 0.06, (w + 0.2, 0.12, d + 0.2), yaw)
        return
    _box(b, node, "ex_accent", c, y + 0.05, (w + 0.15, 0.1, d + 0.15), yaw)
    if kind == "dome":
        b.blob(node, "ex_accent", (c.x, y + 0.1, -c.y), min(w, d) * 0.45, 0.55)
        b.cylinder(node, "brass", (c.x, y + 0.1 + min(w, d) * 0.4, -c.y), 0.03, 0.3, 6)
        return
    if kind == "pyramid":
        for k in range(5):
            s = 1 - k / 5
            _box(b, node, "roof_tile", c, y + 0.15 + k * 0.1, (w * s + 0.1, 0.1, d * s + 0.1), yaw)
        return
    # Bangla: a roof that curves down to its eaves, the Bengali hut roof in stone.
    u = Vec2(math.cos(yaw), math.sin(yaw))
    for j in range(11):
        x = -w / 2 - 0.1 + (w + 0.2) * j / 10
        rise = 0.45 * (1 - (2 * x / (w + 0.2)) ** 2)
        _box(b, node, "roof_tile", c + u * x, y + 0.12 + rise, ((w + 0.2) / 10 + 0.04, 0.08, d + 0.3), yaw)


def _feature(b, ex: Exterior, levels, street, roof_y: float) -> None:
    """The design's signature element, drawn in the design's own character
    (see `traits`) and always clear of doors, and of windows it would cover."""
    f = ex.feature
    if f == "none" or not levels:
        return
    tr = traits(ex)
    n = len(levels)
    fronts_done = False
    for li, (level, base, fp) in enumerate(levels):
        h = level.floor_to_floor
        node = f"level_{level.index}/facade"
        es = edges(fp)
        front = max((e for e in es if street(e)), key=lambda x: x.length, default=None)
        for e in es:
            L, yaw = e.length, _yaw(e)
            doors = door_spans(level, e)
            if f == "colonnade" and li == 0 and street(e) and L > 3.0:
                # The verandah line: columns of the design's kind, a beam and a shallow roof.
                k = max(2, round(L / tr["bay"]))
                for i in range(k + 1):
                    if _free(i / k, 0.2 / L, doors):
                        _column(b, node, tr["column"], e.at(i / k, 1.5), base, h - 0.3, yaw)
                _box(b, node, tr["frame"], e.at(0.5, 1.5), base + h - 0.32, (L + 0.3, 0.26, 0.3), yaw)
                b.slab(node, "slab", [e.at(0, 0), e.at(1, 0), e.at(1, 1.75), e.at(0, 1.75)], base + h - 0.18, base + h - 0.06)
            elif f == "arcade" and li == 0 and street(e) and L > 3.0:
                # Piers and arches of the design's shape, a verandah behind them.
                k = max(2, round(L / tr["bay"]))
                posts = [i / k for i in range(k + 1) if _free(i / k, 0.25 / L, doors) or i in (0, k)]
                for t in posts:
                    _box(b, node, "plaster", e.at(t, 1.6), base + (h - 0.3) / 2, (0.4, h - 0.3, 0.4), yaw)
                for ta, tb in zip(posts, posts[1:]):
                    _arch(b, node, tr["arch"], e, ta, tb, 1.6, base + h - 0.3, yaw)
                _box(b, node, tr["frame"], e.at(0.5, 1.6), base + h - 0.3, (L + 0.4, 0.3, 0.42), yaw)
                b.slab(node, "slab", [e.at(0, 0), e.at(1, 0), e.at(1, 1.85), e.at(0, 1.85)], base + h - 0.15, base + h - 0.03)
            elif f == "jharokha" and li >= 1 and street(e) and L > 3.0:
                # Projecting bays on brackets, as many as the face takes, under the design's canopy.
                wins = clear(0.1, 0.9, door_spans(level, e, 0.3))
                for t0, t1 in wins[:min(3, tr["count"] + 1)]:
                    w = min(1.8, (t1 - t0) * L * 0.8)
                    if w < 1.0:
                        continue
                    c = e.at((t0 + t1) / 2, 0.38)
                    _box(b, node, tr["frame"], c, base + 0.55, (w, 0.14, 0.76), yaw)
                    for s_ in (-1, 1):
                        _box(b, node, "joinery", c + e.dir * (s_ * (w / 2 - 0.05)), base + 1.25, (0.1, 1.3, 0.7), yaw)
                        _box(b, node, "joinery", c + e.dir * (s_ * (w / 2 - 0.2)) - e.out * 0.1, base + 0.35, (0.12, 0.3, 0.5), yaw)
                    _box(b, node, "ex_glassband", c + e.out * 0.3, base + 1.25, (w - 0.2, 1.1, 0.04), yaw)
                    _cap(b, node, tr["canopy"], c, base + 1.92, w, 0.9, yaw)
            elif f == "balcony" and li >= 1 and street(e) and L > 3.0:
                # A cantilevered balcony off the widest opening; its depth and
                # width follow the design, its guard is the design's railing.
                ops = door_spans(level, e, 0.0)
                t = sum(max(ops, key=lambda s_: s_[1] - s_[0])) / 2 if ops else 0.5
                w = min(L * {1: 0.4, 2: 0.5, 3: 0.6, 4: 0.75}[tr["count"]], 4.2)
                t = min(max(t, w / 2 / L + 0.02), 1 - w / 2 / L - 0.02)
                dep = 0.9 + 0.15 * tr["count"]
                c = e.at(t, dep / 2)
                _box(b, node, "slab", c, base - 0.07, (w, 0.16, dep), yaw)
                guard = "rail_glass" if ex.railing in ("", "glass") else "rail_metal" if ex.railing == "metal" else "plaster"
                _box(b, node, guard, e.at(t, dep - 0.03), base + 0.55, (w - 0.06, 0.95, 0.03 if guard != "plaster" else 0.12), yaw)
                _box(b, node, tr["frame"], e.at(t, dep - 0.03), base + 1.04, (w, 0.05, 0.07), yaw)
                for s_ in (-1, 1):
                    q = c + e.dir * (s_ * (w / 2 - 0.02))
                    _box(b, node, guard, q, base + 0.55, (0.03, 0.95, dep - 0.06), yaw)
            elif f == "portico" and li == 0 and street(e) and L > 3.0:
                # Double-height columns of the design's kind at the door, under a slab
                # or, on a pitched house, a pediment.
                ds = door_spans(level, e, 0.0)
                if ds:
                    ta, tb = max(ds, key=lambda s_: s_[1] - s_[0])
                    tall = sum(lv.floor_to_floor for lv, _b, _f in levels[:2]) - 0.2
                    mid = e.at((ta + tb) / 2, 0.0)
                    half = max(1.3, (tb - ta) * L / 2 + 0.7)
                    for s_ in (-1, 1):
                        _column(b, node, tr["column"], mid + e.dir * (s_ * half) + e.out * 2.0, base, tall, yaw)
                    corners = [mid + e.dir * (-half - 0.4), mid + e.dir * (half + 0.4),
                               mid + e.dir * (half + 0.4) + e.out * 2.5, mid + e.dir * (-half - 0.4) + e.out * 2.5]
                    b.slab(node, "slab", corners, base + tall, base + tall + 0.2)
                    _box(b, node, tr["frame"], mid + e.out * 2.5, base + tall + 0.1, (2 * half + 0.8, 0.22, 0.08), yaw)
                    if ex.roof in ("hip", "gable"):
                        y = base + tall + 0.2
                        a_, c_ = mid + e.dir * (-half - 0.4) + e.out * 2.5, mid + e.dir * (half + 0.4) + e.out * 2.5
                        apex = mid + e.out * 2.5
                        b.tri(node, "plaster", (a_.x, y, -a_.y), (c_.x, y, -c_.y), (apex.x, y + 1.0, -apex.y))
            elif f == "bay" and li >= 1 and street(e) and L > 3.0:
                # A projecting box window round the widest window, framed in the design's material.
                wins = door_spans(level, e, 0.0, windows=True)
                if wins:
                    ta, tb = max(wins, key=lambda s_: s_[1] - s_[0])
                    w = min(3.0, (tb - ta) * L + 0.5)
                    c = e.at((ta + tb) / 2, 0.35)
                    for yy in (base + 0.45, base + 2.25):
                        _box(b, node, tr["frame"], c, yy, (w, 0.12, 0.7), yaw)
                    for s_ in (-1, 1):
                        _box(b, node, tr["frame"], c + e.dir * (s_ * (w / 2 - 0.05)), base + 1.35, (0.1, 1.8, 0.7), yaw)
                    _box(b, node, "ex_glassband", c + e.out * 0.32, base + 1.35, (w - 0.2, 1.68, 0.03), yaw)
            elif f in ("brickcurtain", "wavescreen") and (li >= 1 or n == 1) and e is front and L > 3.0:
                # A perforated curtain of bricks across the front: light and air
                # through it, patterned shadow behind it; the wave version ripples.
                mat = {"masonry": "ex_brick", "timber": "ex_terracotta", "modern": "ex_concrete"}[tr["family"]]
                rows = int((h - 0.3) / 0.16)
                cols = int((L - 0.3) / 0.3)
                for j in range(rows):
                    shift = 0.15 if j % 2 else 0.0
                    for i in range(cols):
                        t = (0.15 + shift + i * 0.3) / L
                        if t > 0.97:
                            continue
                        wave = 0.16 * math.sin(2 * math.pi * (t * L) / 2.2 + j * 0.35) if f == "wavescreen" else 0.0
                        _box(b, node, mat, e.at(t, 0.4 + wave), base + 0.2 + j * 0.16, (0.22, 0.075, 0.1), yaw)
                _box(b, node, tr["frame"], e.at(0.5, 0.4), base + h - 0.05, (L, 0.1, 0.5), yaw)
            elif f == "moongate" and e is front and L > 3.5 and li == n - 1:
                # A square screen with a round opening cut through it, standing off the top floor.
                side = min(3.4, h * 1.05, L * 0.5)
                cr = side * 0.36
                c = e.at(_pick(ex, "moonat", (0.3, 0.5, 0.7)), 0.45)
                cells = int(side / 0.2)
                for i in range(cells):
                    for j in range(cells):
                        x = -side / 2 + (i + 0.5) * side / cells
                        y = -side / 2 + (j + 0.5) * side / cells
                        if math.hypot(x, y) > cr:
                            _box(b, node, "clad" if tr["family"] == "masonry" else tr["frame"], c + e.dir * x,
                                 base + h / 2 + y * 0.95, (side / cells + 0.01, side / cells * 0.95 + 0.01, 0.2), yaw)
            elif f == "cantilever" and li == 1 and e is front and L > 3.5:
                # A first-floor room pushed out over the porch: a solid volume, glazed at its end.
                w = min(4.2, L * 0.45)
                t = _pick(ex, "cantat", (w / 2 / L + 0.02, 0.5, 1 - w / 2 / L - 0.02))
                d = 1.3
                c = e.at(t, d / 2)
                skin = SKIN.get(ex.upper, "plaster")
                _box(b, node, skin, c, base - 0.05, (w, 0.3, d), yaw)
                _box(b, node, skin, c, base + h - 0.1, (w, 0.3, d), yaw)
                for s_ in (-1, 1):
                    _box(b, node, skin, c + e.dir * (s_ * (w / 2 - 0.1)), base + h / 2, (0.2, h, d), yaw)
                _box(b, node, "ex_glassband", e.at(t, d - 0.05), base + h / 2, (w - 0.4, h - 0.5, 0.04), yaw)
            elif f == "flutedbands" and li == 0 and e is front and L > 3.0:
                # Full-height fluted bands framing the front, ribbed like a column.
                tall = sum(lv.floor_to_floor for lv, _b, _f in levels) - 0.1
                for t0 in (0.0, 1.0 - 1.2 / L):
                    for k in range(10):
                        _box(b, "level_0/facade", tr["frame"] if tr["frame"] != "ex_accent" else "ex_concrete",
                             e.at(t0 + (0.06 + k * 0.12) / L, 0.06), tall / 2, (0.07, tall, 0.12), yaw)
            elif f == "brisesoleil" and (li >= 1 or n == 1) and street(e) and L > 3.0:
                # A deep egg-crate of fins over the face: Chandigarh's sun-breaker.
                for j in range(int(h / 0.75) + 1):
                    _box(b, node, "ex_concrete", e.at(0.5, 0.3), base + 0.1 + j * 0.75, (L, 0.08, 0.6), yaw)
                k = max(2, int(L / 0.9))
                for i in range(k + 1):
                    if _free(i / k, 0.05 / L, doors):
                        _box(b, node, "ex_concrete", e.at(i / k, 0.3), base + h / 2, (0.08, h, 0.6), yaw)
            elif f == "planterbands" and li >= 1 and street(e) and L > 3.0:
                # A planter trough along every slab edge, greenery spilling over it.
                _box(b, node, "ex_concrete", e.at(0.5, 0.3), base - 0.05, (L, 0.45, 0.45), yaw)
                for i in range(int(L / 0.45)):
                    q = e.at((i + 0.5) * 0.45 / L, 0.33)
                    b.blob(node, "leaf" if i % 2 else "leaf2", (q.x, base + 0.25, -q.y), 0.26, 0.8)
                    if i % 3 == 0:
                        b.blob(node, "leaf2", (q.x, base - 0.35, -q.y), 0.16, 1.6)
            elif f == "cornice":
                # A cornice at every floor: single, doubled, or with a dentil course.
                _box(b, node, "slab", e.at(0.5, 0.2), base + h - 0.12, (L + 0.5, 0.2, 0.42), yaw)
                _box(b, node, tr["frame"], e.at(0.5, 0.26), base + h - 0.3, (L + 0.42, 0.1, 0.3), yaw)
                if tr["cornice"] == "double":
                    _box(b, node, "slab", e.at(0.5, 0.14), base + h - 0.48, (L + 0.3, 0.12, 0.28), yaw)
                elif tr["cornice"] == "dentil":
                    k = max(4, int(L / 0.3))
                    for i in range(k):
                        _box(b, node, "slab", e.at((i + 0.5) / k, 0.12), base + h - 0.42, (0.12, 0.12, 0.2), yaw)
            elif f == "breeze" and li == min(1, n - 1) and street(e) and L > 3.0:
                # A breeze-block panel between the windows: shade with air through it.
                for t0, t1 in clear(0.08, 0.92, door_spans(level, e, 0.2, windows=True)):
                    w = (t1 - t0) * L
                    if w < 1.0:
                        continue
                    c = e.at((t0 + t1) / 2, 0.12)
                    cols, rows = max(2, int(w / 0.4)), max(3, int((h - 0.6) / 0.4))
                    for i in range(cols):
                        for j in range(rows):
                            if (i + j) % 2 == 0:
                                q = c + e.dir * (-w / 2 + (i + 0.5) * w / cols)
                                _box(b, node, "ex_concrete", q, base + 0.3 + (j + 0.5) * (h - 0.6) / rows,
                                     (w / cols - 0.06, (h - 0.6) / rows - 0.06, 0.12), yaw)
            elif f == "greenwall" and not street(e) and L > 3.0 and li == 0:
                # A planted wall on the garden side, clear of every opening.
                for t0, t1 in clear(0.05, 0.95, door_spans(level, e, 0.2, windows=True)):
                    w = (t1 - t0) * L
                    if w < 1.2:
                        continue
                    c = e.at((t0 + t1) / 2, 0.08)
                    _box(b, node, "ex_concrete", c, base + h / 2, (w, h - 0.3, 0.06), yaw)
                    for i in range(max(2, int(w / 0.6))):
                        for j in range(max(3, int((h - 0.4) / 0.6))):
                            q = c + e.dir * (-w / 2 + 0.3 + i * 0.6) + e.out * 0.1
                            b.blob(node, "leaf" if (i + j) % 2 else "leaf2", (q.x, base + 0.35 + j * 0.6, -q.y), 0.27, 0.8)
            elif f == "floatbox" and li >= 1 and e is front and L > 3.0:
                # A deep framed box floating off the upper floor round its widest window.
                wins = door_spans(level, e, 0.0, windows=True)
                ta, tb = max(wins, key=lambda s_: s_[1] - s_[0]) if wins else (0.3, 0.7)
                w = min(L - 0.4, max(2.4, (tb - ta) * L + 1.2))
                t = min(max((ta + tb) / 2, w / 2 / L), 1 - w / 2 / L)
                d = 0.6 + 0.2 * tr["count"]
                c = e.at(t, d / 2)
                for yy in (base + 0.08, base + h - 0.1):
                    _box(b, node, tr["frame"], c, yy, (w, 0.24, d), yaw)
                for s_ in (-1, 1):
                    _box(b, node, tr["frame"], c + e.dir * (s_ * (w / 2 - 0.12)), base + h / 2, (0.24, h, d), yaw)
            elif f == "featurewall" and e is front and L > 3.0 and not fronts_done:
                # A monolith wall standing up the full height of the house at one end of the front.
                fronts_done = True
                end = _pick(ex, "wallend", (0.04, 0.96))
                tall = sum(lv.floor_to_floor for lv, _b, _f in levels) + 1.2
                mat = {"masonry": "clad", "timber": "ex_timber", "modern": "ex_concrete"}[tr["family"]]
                _box(b, "level_0/facade", mat, e.at(end, 0.55), tall / 2, (0.4, tall, 1.3), yaw)
            elif f == "thinnai" and li == 0 and e is front and L > 3.0:
                # Raised verandah platforms either side of the door, timber posts and a tiled lean-to.
                ds = door_spans(level, e, 0.0)
                gap = max(ds, key=lambda s_: s_[1] - s_[0]) if ds else (0.45, 0.55)
                for t0, t1 in clear(0.02, 0.98, [gap]):
                    w = (t1 - t0) * L
                    if w < 1.2:
                        continue
                    c = e.at((t0 + t1) / 2, 0.7)
                    _box(b, node, "plinth", c, base + 0.22, (w, 0.44, 1.2), yaw)
                    for t in (t0 + 0.15 / L, t1 - 0.15 / L):
                        _column(b, node, "timber" if tr["family"] != "masonry" else "round", e.at(t, 1.2), base + 0.44, h - 0.9, yaw)
                lo, hi = e.at(0, 1.6), e.at(1, 1.6)
                y = base + h - 0.4
                b.quad_strip(node, "roof_tile", (e.a.x, y + 0.4, -e.a.y), (e.c.x, y + 0.4, -e.c.y), (hi.x, y, -hi.y), (lo.x, y, -lo.y))
            elif f == "pergolaframe" and li == 0 and e is front and L > 3.0:
                # A double-height timber frame standing off the front, rafters across it.
                tall = sum(lv.floor_to_floor for lv, _b, _f in levels[:2]) - 0.1
                k = max(2, round(L / tr["bay"]))
                for i in range(k + 1):
                    p = e.at(i / k, 1.8)
                    if _free(i / k, 0.2 / L, doors):
                        _box(b, node, "timber", p, base + tall / 2, (0.18, tall, 0.18), yaw)
                _box(b, node, "timber", e.at(0.5, 1.8), base + tall, (L, 0.22, 0.16), yaw)
                for i in range(int(L / 0.45) + 1):
                    _box(b, node, "timber", e.at(i * 0.45 / L, 0.95), base + tall + 0.15, (0.07, 0.16, 1.9), yaw)
            elif f == "cornerglass" and li >= 1 and e is front and L > 3.0:
                # The upper floor's street corner opened in glass, framed thin.
                end = _pick(ex, "glassend", (0, 1))
                w = min(2.4, L * 0.35)
                t = (w / 2) / L if end == 0 else 1 - (w / 2) / L
                c = e.at(t, 0.12)
                _box(b, node, "ex_glassband", c, base + h / 2, (w, h - 0.3, 0.04), yaw)
                for yy in (base + 0.1, base + h - 0.12):
                    _box(b, node, tr["frame"], e.at(t, 0.2), yy, (w + 0.2, 0.14, 0.4), yaw)
                for i in range(1, 3):
                    _box(b, node, "frame", c + e.dir * (-w / 2 + i * w / 3), base + h / 2, (0.05, h - 0.3, 0.06), yaw)
    if f == "rooftopframe" and ex.roof in ("flat", "slab"):
        # A thin concrete frame crowning the roof: the house drawn as one bold line.
        level, base, fp = levels[-1]
        if fp is not None and not fp.is_empty:
            front = max((e for e in edges(fp) if street(e)), key=lambda x: x.length, default=None)
            if front is not None:
                w = front.length * _pick(ex, "crownw", (0.5, 0.65, 0.8))
                c = front.at(0.5, -1.2)
                yaw, y = _yaw(front), roof_y + (0.18 if ex.roof == "slab" else 0.0)
                for s_ in (-1, 1):
                    _box(b, "roof", "ex_concrete", c + front.dir * (s_ * w / 2), y + 1.6, (0.25, 3.2, 2.4), yaw)
                _box(b, "roof", "ex_concrete", c, y + 3.2, (w + 0.25, 0.25, 2.4), yaw)
    if f in ("chhatri", "bangla") and ex.roof == "flat":
        level, base, fp = levels[-1]
        if fp is not None and not fp.is_empty:
            x0, y0, x1, y1 = fp.bounds
            if f == "bangla":
                # One rooftop pavilion under a curved bangla roof, on slender columns.
                cx, cy = _pick(ex, "pav", (((x0 + x1) / 2, y1 - 1.4), ((x0 + x1) / 2, y0 + 1.4)))
                w, d = min(3.2, (x1 - x0) * 0.4), 2.0
                for dx in (-w / 2 + 0.15, w / 2 - 0.15):
                    for dy in (-d / 2 + 0.15, d / 2 - 0.15):
                        _column(b, "roof", "round" if tr["family"] == "masonry" else tr["column"], Vec2(cx + dx, cy + dy), roof_y + 0.15, 1.9, 0.0)
                _cap(b, "roof", "bangla", Vec2(cx, cy), roof_y + 2.05, w, d, 0.0)
            else:
                # Chhatris on the roof corners: one to four, under the design's canopy.
                spots = [(x0 + 0.9, y0 + 0.9), (x1 - 0.9, y1 - 0.9), (x1 - 0.9, y0 + 0.9), (x0 + 0.9, y1 - 0.9)]
                for cx, cy in spots[:tr["count"]]:
                    for dx in (-0.45, 0.45):
                        for dy in (-0.45, 0.45):
                            b.cylinder("roof", "plaster", (cx + dx, roof_y + 0.2, -(cy + dy)), 0.07, 1.5, 10)
                    _cap(b, "roof", "dome" if tr["canopy"] == "flat" else tr["canopy"], Vec2(cx, cy), roof_y + 1.7, 1.3, 1.3, 0.0)


def _panel(b, ex: Exterior, levels, street) -> None:
    """A full-height feature panel in a second material on each floor's street
    face, over the widest stretch of wall that has no door or window in it."""
    if ex.panel not in PANEL_FINISH:
        return
    for level, base, fp in levels:
        h = level.floor_to_floor
        fronts = [e for e in edges(fp) if street(e) and e.length > 3.0]
        if not fronts:
            continue
        e = max(fronts, key=lambda x: x.length)
        spans = [(t0, t1) for t0, t1 in clear(0.02, 0.98, door_spans(level, e, 0.12, windows=True)) if (t1 - t0) * e.length >= 0.9]
        if not spans:
            continue
        t0, t1 = max(spans, key=lambda sp: sp[1] - sp[0])
        w = min((t1 - t0) * e.length, 2.6)
        _box(b, f"level_{level.index}/facade", "ex_panel", e.at((t0 + t1) / 2, 0.05), base + h / 2, (w, h, 0.06), _yaw(e))


def _lights(b, ex: Exterior, levels, street, roof_y: float) -> None:
    """Facade lighting on the street faces: wall washers up the piers, or
    LED strips tucked under each floor's band and the parapet; they glow in
    the night view."""
    if ex.lights not in ("washers", "strips"):
        return
    for li, (level, base, fp) in enumerate(levels):
        h = level.floor_to_floor
        node = f"level_{level.index}/facade"
        for e in edges(fp):
            if not street(e) or e.length < 2.0:
                continue
            yaw = _yaw(e)
            if ex.lights == "strips":
                _box(b, node, "facade_light", e.at(0.5, 0.16), base + h - 0.16, (e.length * 0.94, 0.025, 0.03), yaw)
            else:
                spans = door_spans(level, e, 0.1, windows=True)
                k = max(2, int(e.length / 2.2))
                for i in range(k + 1):
                    t = 0.04 + 0.92 * i / k
                    if _free(t, 0.08 / e.length, spans):
                        _box(b, node, "facade_light", e.at(t, 0.07), base + 0.35, (0.1, 0.06, 0.08), yaw)
                        _box(b, node, "facade_light", e.at(t, 0.07), base + h - 0.3, (0.1, 0.06, 0.08), yaw)


def _screen(b, node, kind, e: Edge, L: float, yaw: float, base: float, h: float,
            spans: list[tuple[float, float]] = (), ground: bool = False) -> None:
    """The street screen, kept out of every doorway: fins and slats are left
    out where a door is, louvres, jaali and frame beams run either side of it."""
    spans = list(spans)
    if kind == "fins":
        k = max(3, int(L / 0.45))
        for i in range(k):
            t = (i + 0.5) / k
            if _free(t, 0.05 / L, spans):
                _box(b, node, "ex_accent", e.at(t, 0.22), base + h / 2, (0.06, h - 0.1, 0.38), yaw)
    elif kind == "louvres":
        rows = int((h - 0.4) / 0.22)
        for t0, t1 in clear(0.04, 0.96, spans):
            for j in range(rows):
                _box(b, node, "ex_accent", e.at((t0 + t1) / 2, 0.28), base + 0.3 + j * 0.22, ((t1 - t0) * L, 0.05, 0.22), yaw)
    elif kind == "frame":
        d = 0.75
        # On the ground floor the frame has no sill beam: it would be a kerb across the door.
        for y in ((base + h - 0.1,) if ground else (base + 0.05, base + h - 0.1)):
            _box(b, node, "ex_accent", e.at(0.5, d / 2), y, (L + 0.5, 0.22, d), yaw)
        for t, s in ((0.0, 1), (1.0, -1)):
            _box(b, node, "ex_accent", e.at(t, d / 2) + e.dir * (s * 0.14), base + h / 2, (0.22, h, d), yaw)
    elif kind == "jaali" and L > 2.0:
        rows = int((h - 0.6) / 0.2)
        for t0, t1 in clear(0.2, 0.8, spans):
            w = (t1 - t0) * L
            if w < 0.8:
                continue
            s0 = e.at((t0 + t1) / 2, 0.32)
            cols = max(2, int(w / 0.2))
            for i in range(cols + 1):
                _box(b, node, "joinery", s0 + e.dir * (-w / 2 + i * w / cols), base + 0.3 + (h - 0.6) / 2, (0.04, h - 0.6, 0.05), yaw)
            for j in range(rows + 1):
                _box(b, node, "joinery", s0, base + 0.3 + j * (h - 0.6) / rows, (w, 0.04, 0.05), yaw)
    elif kind == "slats":
        # Close vertical timber slats across the whole face, left out at doors.
        k = max(6, int(L / 0.11))
        for i in range(k):
            t = (i + 0.5) / k
            if _free(t, 0.03 / L, spans):
                _box(b, node, "ex_timber", e.at(t, 0.12), base + h / 2, (0.035, h - 0.15, 0.09), yaw)
        _box(b, node, "ex_accent", e.at(0.5, 0.12), base + h - 0.06, (L, 0.08, 0.14), yaw)
    elif kind == "bamboo":
        # A veil of bamboo poles on a top and bottom rail.
        k = max(6, int(L / 0.13))
        for i in range(k):
            t = (i + 0.5) / k
            if _free(t, 0.04 / L, spans):
                p = e.at(t, 0.2)
                b.cylinder(node, "bamboo", (p.x, base + 0.08, -p.y), 0.032, h - 0.16, 7)
        for yy in (base + 0.1, base + h - 0.12):
            _box(b, node, "ex_accent", e.at(0.5, 0.2), yy, (L, 0.05, 0.08), yaw)
    elif kind == "perforated" and L > 2.0:
        w = L * 0.55
        k = max(6, int(w / 0.12))
        for i in range(k):
            t = 0.62 - 0.275 + (i + 0.5) * 0.55 / k
            if not _free(t, 0.06 / L, spans):
                continue
            gap = 0.03 + 0.05 * abs(math.sin(i * 0.7))       # a slatted rhythm reads as perforation
            _box(b, node, "ex_metal", e.at(t, 0.3), base + h / 2, (w / k - gap, h - 0.3, 0.03), yaw)


def _curved_roofs(b, kind: str, footprint, y: float) -> bool:
    """A barrel vault over the long axis, or a sawtooth of north lights
    along it: roofs that change the house's whole silhouette."""
    fx0, fy0, fx1, fy1 = footprint.bounds
    eave = 0.45
    x0, y0, x1, y1 = fx0 - eave, fy0 - eave, fx1 + eave, fy1 + eave
    along_x = (x1 - x0) >= (y1 - y0)
    long0, long1 = (x0, x1) if along_x else (y0, y1)
    short0, short1 = (y0, y1) if along_x else (x0, x1)
    lo = y + 0.2

    def P(u: float, v: float, h: float) -> tuple[float, float, float]:
        # u along the long axis, v across it, h up.
        return (u, h, -v) if along_x else (v, h, -u)

    # The walls carried up a little to meet the roof.
    b.slab("roof", "plaster", [Vec2(fx0, fy0), Vec2(fx1, fy0), Vec2(fx1, fy1), Vec2(fx0, fy1)], y, lo)
    if kind == "vault":
        span = short1 - short0
        rise = span * 0.24
        n = 16
        arc = [(short0 + span * i / n, lo + math.sin(math.pi * i / n) * rise) for i in range(n + 1)]
        for (va, ha), (vb, hb) in zip(arc, arc[1:]):
            b.quad_strip("roof", "ex_roof", P(long0, va, ha), P(long1, va, ha), P(long1, vb, hb), P(long0, vb, hb))
            for u in (long0 + eave, long1 - eave):
                # The vault's end walls, glazed: light along the whole house.
                b.quad_strip("roof", "glass", P(u, va, lo), P(u, vb, lo), P(u, vb, hb), P(u, va, ha))
        return True
    length = long1 - long0
    teeth = max(2, round(length / 4.0))
    seg, rise = length / teeth, 1.2
    for i in range(teeth):
        ua, ub = long0 + i * seg, long0 + (i + 1) * seg
        b.quad_strip("roof", "ex_roof", P(ua, short0, lo), P(ub, short0, lo + rise), P(ub, short1, lo + rise), P(ua, short1, lo))
        b.quad_strip("roof", "glass", P(ub, short0, lo), P(ub, short1, lo), P(ub, short1, lo + rise), P(ub, short0, lo + rise))
        for v in (short0, short1):
            b.tri("roof", "plaster", P(ua, v, lo), P(ub, v, lo), P(ub, v, lo + rise))
    return True


def _rgb(hex_: str) -> tuple[float, float, float]:
    v = hex_.lstrip("#")
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def roof(b, kind: str, footprint, y: float, road: Vec2 | None, slab_mat: str = "slab") -> bool:
    """Roofs the builder does not already draw. True if drawn."""
    if footprint is None or footprint.is_empty:
        return False
    x0, y0, x1, y1 = footprint.bounds
    if kind in ("vault", "sawtooth"):
        return _curved_roofs(b, kind, footprint, y)
    if kind == "slab":
        # A thin roof plate cantilevered well past the walls, with a fascia.
        o = 0.6
        b.slab("roof", slab_mat, [Vec2(x0 - o, y0 - o), Vec2(x1 + o, y0 - o), Vec2(x1 + o, y1 + o), Vec2(x0 - o, y1 + o)], y, y + 0.18)
        return True
    if kind == "pitch":
        pitch_roof(b, footprint, y, road)
        return True
    if kind in ("butterfly", "gable"):
        eave = 0.6
        x0, y0, x1, y1 = x0 - eave, y0 - eave, x1 + eave, y1 + eave
        along_x = (x1 - x0) >= (y1 - y0)
        mid = (y0 + y1) / 2 if along_x else (x0 + x1) / 2
        rise = (min(x1 - x0, y1 - y0)) * (0.12 if kind == "butterfly" else 0.3)
        # Ridge (gable) or valley (butterfly) along the long axis.
        r = rise if kind == "gable" else -rise * 0.6
        lo = y + 0.2 + (0 if kind == "gable" else rise)
        P = lambda px, py, h: (px, h, -py)  # noqa: E731
        mat = "roof_tile" if kind == "gable" else "ex_roof"
        if along_x:
            A, B, C, D = P(x0, y0, lo), P(x1, y0, lo), P(x1, y1, lo), P(x0, y1, lo)
            M0, M1 = P(x0, mid, lo + r), P(x1, mid, lo + r)
            b.quad_strip("roof", mat, A, B, M1, M0)
            b.quad_strip("roof", mat, M0, M1, C, D)
            b.tri("roof", "plaster", A, M0, D) if kind == "gable" else None
            b.tri("roof", "plaster", B, C, M1) if kind == "gable" else None
        else:
            A, B, C, D = P(x0, y0, lo), P(x1, y0, lo), P(x1, y1, lo), P(x0, y1, lo)
            M0, M1 = P(mid, y0, lo + r), P(mid, y1, lo + r)
            b.quad_strip("roof", mat, A, M0, M1, D)
            b.quad_strip("roof", mat, M0, B, C, M1)
            b.tri("roof", "plaster", A, B, M0) if kind == "gable" else None
            b.tri("roof", "plaster", D, C, M1) if kind == "gable" else None
        if kind == "butterfly":
            # Walls carried up to meet the raised outer edges.
            fx0, fy0, fx1, fy1 = footprint.bounds
            b.slab("roof", "plaster", [Vec2(fx0, fy0), Vec2(fx1, fy0), Vec2(fx1, fy1), Vec2(fx0, fy1)], y, y + 0.2)
        return True
    return False
