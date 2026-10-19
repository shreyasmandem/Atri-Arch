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

ROOFS = ("flat", "slab", "mono", "butterfly", "hip", "gable")
#: Wall skins. Terracotta tile, ACP (aluminium composite panel) and stacked
#: slate are what Indian elevations layer today beside plaster and stone.
BASES = ("plaster", "stone", "brick", "concrete", "timber", "metal", "terracotta", "acp", "slate")
UPPERS = ("plaster", "timber", "metal", "brick", "stone", "concrete", "terracotta", "acp", "slate")
SCREENS = ("none", "fins", "louvres", "frame", "jaali", "perforated")
WINDOWS = ("punched", "band")
#: The design's signature element: what a passer-by remembers the house by.
FEATURES = ("none", "jharokha", "colonnade", "chhatri", "cornice", "breeze", "greenwall", "balcony")
ACCENTS = {"bronze": "#8a6a4c", "charcoal": "#2b2a29", "teak": "#7a4b2a", "white": "#efece6",
           "terracotta": "#a8553a", "sage": "#7d8b6a", "navy": "#2b3a52", "brass": "#b08a3e",
           "ochre": "#c08a2e", "indigo": "#34406e", "forest": "#2f4a36", "rose": "#b46a6a",
           "slate": "#59626b", "sand": "#d2b98f", "copper": "#b0683c", "olive": "#6b6b3a",
           "graphite": "#3d3f42", "verdigris": "#5f8a7e"}
#: The four tints a design may fix exactly: id key -> Exterior field.
COLOUR_KEYS = {"w": "wall", "c": "clad", "r": "roof_tint", "m": "metal", "f": "frame", "d": "door"}
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
PANELS = ("none", "stone", "timber", "slate", "terracotta", "acp", "brick")
PARAPETS = ("plain", "glass", "grooved", "screen", "stepped")   # the crown of a flat-roofed house
DECKS = ("none", "pergola", "garden")                            # what the roof terrace holds
LIGHTS = ("none", "washers", "strips")                           # facade lighting, lit at night
#: Discrete extras in the id's tail: id key -> (Exterior field, vocabulary).
#: The first value of each is what the house has when the id leaves it out.
OPTION_KEYS = {"b": ("boundary", BOUNDARIES), "l": ("railing", RAILINGS), "h": ("shade", SHADES),
               "e": ("canopy", CANOPIES), "g": ("gate", GATES), "v": ("paving", PAVINGS),
               "t": ("garden", GARDENS), "s": ("solar", SOLAR), "x": ("panel", PANELS), "q": ("parapet", PARAPETS),
               "k": ("deck", DECKS), "i": ("lights", LIGHTS)}
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
    "contemporary": {"roof": ("flat", "slab", "mono"), "screen": ("fins", "frame", "louvres", "perforated"),
                     "feature": ("none", "cornice", "breeze", "greenwall"), "accent": ("bronze", "charcoal", "slate", "teak")},
    "modern_minimal": {"roof": ("slab", "flat"), "screen": ("none", "frame"), "upper": ("plaster", "metal"),
                       "feature": ("none",), "accent": ("white", "charcoal", "slate")},
    "tropical_modern": {"roof": ("slab", "mono", "butterfly"), "upper": ("timber",), "screen": ("louvres", "fins"),
                        "feature": ("greenwall", "breeze", "none"), "accent": ("teak", "forest", "sage")},
    "kerala_vernacular": {"roof": ("hip", "gable"), "base": ("stone", "plaster"), "upper": ("timber", "plaster"),
                          "feature": ("colonnade",), "accent": ("teak", "terracotta", "forest")},
    "traditional_indian": {"roof": ("hip", "flat"), "screen": ("jaali",), "base": ("stone",),
                           "feature": ("jharokha", "colonnade", "cornice"), "accent": ("ochre", "terracotta", "teak", "indigo")},
    "chettinad": {"roof": ("hip", "flat"), "screen": ("jaali",), "base": ("stone", "brick"),
                  "feature": ("colonnade", "cornice"), "accent": ("ochre", "indigo", "rose", "teak")},
    "rajasthani_haveli": {"roof": ("flat",), "screen": ("jaali",), "base": ("stone",),
                          "feature": ("jharokha", "chhatri"), "accent": ("sand", "rose", "ochre", "terracotta")},
    "indo_saracenic": {"roof": ("flat",), "screen": ("jaali", "frame"), "base": ("stone", "brick"),
                       "feature": ("chhatri", "colonnade", "cornice"), "accent": ("sand", "terracotta", "white")},
    "scandinavian": {"roof": ("gable", "mono"), "upper": ("timber",), "screen": ("none",),
                     "feature": ("none",), "accent": ("charcoal", "white", "slate")},
    "japandi": {"roof": ("slab", "gable"), "upper": ("timber",), "screen": ("louvres", "none"),
                "feature": ("none", "greenwall"), "accent": ("teak", "charcoal", "sand")},
    "industrial": {"base": ("concrete", "brick"), "upper": ("metal", "brick"), "screen": ("perforated", "frame"),
                   "feature": ("none", "breeze"), "accent": ("charcoal", "slate", "terracotta")},
    "biophilic": {"roof": ("slab", "butterfly"), "upper": ("timber",), "screen": ("louvres", "fins"),
                  "feature": ("greenwall",), "accent": ("forest", "sage", "teak")},
    "mid_century_modern": {"roof": ("butterfly", "mono", "slab"), "base": ("brick", "stone"), "screen": ("frame", "fins"),
                           "feature": ("breeze", "none"), "accent": ("ochre", "teak", "sage", "navy")},
}

NAMES = {
    "fins": "Fin", "louvres": "Louvre", "frame": "Frame", "jaali": "Jaali", "perforated": "Screen", "none": "Plain",
    "flat": "Parapet", "slab": "Slab", "mono": "Skillion", "butterfly": "Butterfly", "hip": "Tiled", "gable": "Gable",
    "timber": "Timber", "metal": "Metal", "brick": "Brick", "stone": "Stone", "concrete": "Concrete", "plaster": "Lime",
    "terracotta": "Terracotta", "acp": "Panel", "slate": "Slate",
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

    @property
    def id(self) -> str:
        core = "ex:" + ".".join([self.roof, self.base, self.upper, self.screen, self.windows,
                                 "p" if self.planters else "n", self.accent, self.feature])
        tail = [f"{k}:{getattr(self, f)}" for k, f in COLOUR_KEYS.items() if getattr(self, f)]
        tail += [f"{k}:{getattr(self, f)}" for k, (f, _) in OPTION_KEYS.items() if getattr(self, f)]
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
        if e.feature in ("jharokha", "balcony") and one_floor:
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
        if e.feature == "chhatri" and e.roof != "flat":
            notes.append("Chhatris stand on a flat parapet roof; the roof is set to flat.")
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
                "butterfly": "a butterfly roof", "hip": "a hipped tile roof on deep eaves", "gable": "a pitched gable roof"}[self.roof]
        base = {"plaster": "a lime-plaster ground floor", "stone": "a stone-clad ground floor", "brick": "an exposed-brick ground floor",
                "concrete": "a board-marked concrete ground floor", "timber": "a timber-boarded ground floor",
                "metal": "a dark metal-clad ground floor", "terracotta": "a terracotta-tiled ground floor",
                "acp": "an aluminium-panelled ground floor", "slate": "a stacked-slate ground floor"}[self.base]
        upper = {"plaster": "plastered floors above", "timber": "timber-boarded floors above", "metal": "dark metal-clad floors above",
                 "brick": "brick floors above", "stone": "stone-clad floors above",
                 "concrete": "board-marked concrete floors above", "terracotta": "terracotta-tiled floors above",
                 "acp": "aluminium-panelled floors above", "slate": "stacked-slate floors above"}[self.upper]
        screen = {"none": "", "fins": ", vertical fins shading the street face", "louvres": ", horizontal louvres across the street face",
                  "frame": ", a deep frame around the upper floor", "jaali": ", a jaali screen against the hard sun",
                  "perforated": ", a perforated metal screen"}[self.screen]
        win = ", glazing in continuous bands" if self.windows == "band" else ""
        plant = ", planters along the edges" if self.planters else ""
        feat = {"none": "", "jharokha": ", jharokha bays projecting over the street",
                "colonnade": ", a colonnaded verandah along the front", "chhatri": ", chhatri pavilions on the roof",
                "cornice": ", deep cornices marking every floor", "breeze": ", a breeze-block screen wall",
                "greenwall": ", a planted green wall", "balcony": ", cantilevered balconies over the street"}[self.feature]
        return f"{base[0].upper()}{base[1:]}, {upper}{screen}{feat}{win}{plant}, under {roof}."

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["colours"] = {f: (f"#{d.pop(f)}" if d[f] else "") for f in COLOUR_KEYS.values()}
        return {"id": self.id, "name": self.name(), "story": self.story(), **d}


#: How much each choice changes what a passer-by sees, for keeping a batch far apart.
_WEIGHT = {"roof": 3.0, "feature": 2.5, "screen": 2.0, "upper": 1.5, "base": 1.2, "windows": 0.6,
           "planters": 0.4, "accent": 0.8, "wall": 1.5, "roof_tint": 0.6, "shade": 0.6, "canopy": 0.5,
           "boundary": 0.6, "gate": 0.3, "paving": 0.3, "garden": 0.4, "solar": 0.5, "panel": 1.2, "parapet": 0.8,
           "deck": 0.7, "lights": 0.4}


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


def grammar() -> dict[str, Any]:
    """The vocabulary a client can customise with, labelled."""
    return {"combinations": combinations(), "roof": list(ROOFS), "base": list(BASES), "upper": list(UPPERS), "screen": list(SCREENS),
            "windows": list(WINDOWS), "feature": list(FEATURES), "accents": ACCENTS,
            "tones": {k: v[0] for k, v in WALL_TONES.items()}, "labels": NAMES, "schemes": list(EXTERIOR_SCHEMES),
            "boundary": list(BOUNDARIES), "railing": list(RAILINGS), "shade": list(SHADES), "canopy": list(CANOPIES),
            "gate": list(GATES), "paving": list(PAVINGS), "garden": list(GARDENS), "solar": list(SOLAR),
            "panel": list(PANELS), "parapet": list(PARAPETS), "deck": list(DECKS), "lights": list(LIGHTS),
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
        return rng.choice(fav) if fav and rng.random() < lead else rng.choice(pool)

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
            panel=option("panel", PANELS), lights=option("lights", LIGHTS),
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
    if e.feature in ("jharokha", "balcony") and one_floor:
        return False
    if e.base == "metal" and e.upper in ("stone", "brick"):
        return False                         # the heavy skin goes below the light one
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
        "terracotta": "ex_terracotta", "acp": "ex_acp", "slate": "ex_slate"}
#: A feature panel's finish: the skin it copies, and a name the viewer reads its texture by.
PANEL_FINISH = {"stone": ("clad", "panel_stone_cladding"), "timber": ("ex_timber", "panel_timber_boards"),
                "slate": ("ex_slate", "panel_slate_stack"), "terracotta": ("ex_terracotta", "panel_terracotta_tile"),
                "acp": ("ex_acp", "panel_acp_panel"), "brick": ("ex_brick", "panel_brick")}


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
        for skin in {ex.base, ex.upper} - {"plaster"} or {"stone"}:
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
    if ex.deck == "pergola":
        palette.pergola = True
    elif ex.deck:
        palette.pergola = False
    if ex.panel in PANEL_FINISH:
        src, name = PANEL_FINISH[ex.panel]
        m["ex_panel"] = m[src].__class__(name, m[src].rgb, m[src].roughness, m[src].metallic)
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
    return {"roof": {"flat": "flat", "slab": "slab", "mono": "pitch", "butterfly": "butterfly", "hip": "hip", "gable": "gable"}[ex.roof]}


def _feature(b, ex: Exterior, levels, street, roof_y: float) -> None:
    """The design's signature element, always clear of doors (and of windows
    where it would cover them)."""
    f = ex.feature
    if f == "none" or not levels:
        return
    n = len(levels)
    for li, (level, base, fp) in enumerate(levels):
        h = level.floor_to_floor
        node = f"level_{level.index}/facade"
        for e in edges(fp):
            L, yaw = e.length, _yaw(e)
            doors = door_spans(level, e)
            if f == "colonnade" and li == 0 and street(e) and L > 3.0:
                # Posts along the front, a beam and a shallow roof: the verandah line.
                k = max(2, int(L / 2.4))
                for i in range(k + 1):
                    t = i / k
                    if _free(t, 0.2 / L, doors):
                        p = e.at(t, 1.5)
                        b.cylinder(node, "plaster", (p.x, base, -p.y), 0.13, h - 0.25, 14)
                        _box(b, node, "slab", p, base + 0.04, (0.42, 0.08, 0.42), yaw)
                _box(b, node, "ex_accent", e.at(0.5, 1.5), base + h - 0.32, (L + 0.3, 0.26, 0.3), yaw)
                b.slab(node, "slab", [e.at(0, 0), e.at(1, 0), e.at(1, 1.75), e.at(0, 1.75)], base + h - 0.18, base + h - 0.06)
            elif f == "jharokha" and li >= 1 and street(e) and L > 3.0:
                # Projecting bay windows on brackets, each under a small canopy.
                wins = clear(0.12, 0.88, door_spans(level, e, 0.3))
                for t0, t1 in wins[:2]:
                    w = min(1.8, (t1 - t0) * L * 0.8)
                    if w < 1.0:
                        continue
                    c = e.at((t0 + t1) / 2, 0.38)
                    _box(b, node, "ex_accent", c, base + 0.55, (w, 0.14, 0.76), yaw)
                    for s_ in (-1, 1):
                        _box(b, node, "joinery", c + e.dir * (s_ * (w / 2 - 0.05)), base + 1.25, (0.1, 1.3, 0.7), yaw)
                    _box(b, node, "ex_glassband", c + e.out * 0.3, base + 1.25, (w - 0.2, 1.1, 0.04), yaw)
                    _box(b, node, "ex_accent", c, base + 1.98, (w + 0.3, 0.12, 0.95), yaw)
                    b.blob(node, "ex_accent", (c.x, base + 2.1, -c.y), w * 0.32, 0.45)
            elif f == "balcony" and li >= 1 and street(e) and L > 3.0:
                # A cantilevered slab with a glass balustrade, centred on the
                # widest opening (the balcony is what the door opens onto).
                ops = door_spans(level, e, 0.0)
                t = sum(max(ops, key=lambda s_: s_[1] - s_[0])) / 2 if ops else 0.5
                w = min(L * 0.5, 3.6)
                t = min(max(t, w / 2 / L + 0.02), 1 - w / 2 / L - 0.02)
                dep = 1.1
                c = e.at(t, dep / 2)
                _box(b, node, "slab", c, base - 0.07, (w, 0.16, dep), yaw)
                _box(b, node, "rail_glass", e.at(t, dep - 0.03), base + 0.55, (w - 0.06, 0.95, 0.03), yaw)
                _box(b, node, "ex_accent", e.at(t, dep - 0.03), base + 1.04, (w, 0.05, 0.07), yaw)
                for s_ in (-1, 1):
                    q = c + e.dir * (s_ * (w / 2 - 0.02))
                    _box(b, node, "rail_glass", q, base + 0.55, (0.03, 0.95, dep - 0.06), yaw)
                    _box(b, node, "ex_accent", q, base + 1.04, (0.05, 0.05, dep), yaw)
            elif f == "cornice":
                _box(b, node, "slab", e.at(0.5, 0.2), base + h - 0.12, (L + 0.5, 0.2, 0.42), yaw)
                _box(b, node, "ex_accent", e.at(0.5, 0.26), base + h - 0.3, (L + 0.42, 0.1, 0.3), yaw)
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
    if f == "chhatri" and ex.roof == "flat":
        level, base, fp = levels[-1]
        if fp is not None and not fp.is_empty:
            x0, y0, x1, y1 = fp.bounds
            for cx, cy in ((x0 + 0.9, y0 + 0.9), (x1 - 0.9, y1 - 0.9)):
                for dx in (-0.45, 0.45):
                    for dy in (-0.45, 0.45):
                        b.cylinder("roof", "plaster", (cx + dx, roof_y + 0.2, -(cy + dy)), 0.07, 1.5, 10)
                b.slab("roof", "slab", [Vec2(cx - 0.65, cy - 0.65), Vec2(cx + 0.65, cy - 0.65), Vec2(cx + 0.65, cy + 0.65),
                                        Vec2(cx - 0.65, cy + 0.65)], roof_y + 1.7, roof_y + 1.82)
                b.blob("roof", "ex_accent", (cx, roof_y + 2.05, -cy), 0.6, 0.6)


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
    elif kind == "perforated" and L > 2.0:
        w = L * 0.55
        k = max(6, int(w / 0.12))
        for i in range(k):
            t = 0.62 - 0.275 + (i + 0.5) * 0.55 / k
            if not _free(t, 0.06 / L, spans):
                continue
            gap = 0.03 + 0.05 * abs(math.sin(i * 0.7))       # a slatted rhythm reads as perforation
            _box(b, node, "ex_metal", e.at(t, 0.3), base + h / 2, (w / k - gap, h - 0.3, 0.03), yaw)


def _rgb(hex_: str) -> tuple[float, float, float]:
    v = hex_.lstrip("#")
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def roof(b, kind: str, footprint, y: float, road: Vec2 | None, slab_mat: str = "slab") -> bool:
    """Roofs the builder does not already draw. True if drawn."""
    if footprint is None or footprint.is_empty:
        return False
    x0, y0, x1, y1 = footprint.bounds
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
