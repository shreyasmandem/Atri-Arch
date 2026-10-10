"""Colour schemes for the house, inside and out, and how one is chosen.

A scheme is a coordinated set: the exterior plaster, cladding, roof, frames
and doors, and inside, a paint for every kind of room, the wet-area tiles, the
floors, the joinery and the soft furnishings. They are designed together so
that whatever the client flips to, the outside and the inside belong to the
same house.

Choosing one is a ranking, not a lookup. Each scheme is scored on:

* **style** - a Chettinad house wants ochre and oxide, not Nordic fog;
* **climate** - in a hot city a dark facade is a heat sink, so light,
  reflective plaster is preferred and a dark one is marked down with a reason;
* **Vastu** - the classical colour for each direction (earth tones in the
  south-west master bedroom, warm tones for a south-east kitchen, light and
  white in the north-east) is checked against the colour the scheme would
  actually paint that room;
* **what the client said** - colour words in their own text ("sage bedrooms",
  "no pink", "lots of wood", "a navy front door") become liked and avoided
  families and exact overrides for particular surfaces.

Every scheme carries the reasons it scored as it did, so the recommendation
explains itself.
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass, field, replace
from typing import Any

# ---------------------------------------------------------------------------
# The schemes
# ---------------------------------------------------------------------------

EXTERIOR_SLOTS = ("plaster", "trim", "clad", "roof", "frame", "door", "metal", "compound")
INTERIOR_SLOTS = ("living", "dining", "bedroom", "master", "kids", "kitchen", "study", "puja",
                  "circulation", "ceiling", "bath_tile", "kitchen_tile", "accent_wall",
                  "floor_stone", "floor_wood", "floor_tile", "joinery", "upholstery", "accent", "metal_in")


@dataclass(frozen=True, slots=True)
class Scheme:
    id: str
    name: str
    story: str
    tags: frozenset[str]
    styles: frozenset[str]
    exterior: dict[str, str]
    interior: dict[str, str]

    def colour(self, slot: str) -> str:
        return self.exterior.get(slot) or self.interior.get(slot) or "#cccccc"


def _s(id_: str, name: str, story: str, tags: str, styles: str, ext: dict[str, str], inn: dict[str, str]) -> Scheme:
    return Scheme(id_, name, story, frozenset(tags.split()), frozenset(styles.split()), ext, inn)


SCHEMES: tuple[Scheme, ...] = (
    _s("monsoon_lime", "Monsoon Lime",
       "Warm lime plaster, laterite and terracotta outside; sage, teak and kota within.",
       "warm earthy white wood green natural light", "kerala_vernacular traditional_indian tropical_modern biophilic",
       {"plaster": "#efe7d8", "trim": "#d9cdb8", "clad": "#9a5b3c", "roof": "#a2472b", "frame": "#4a3326",
        "door": "#5a3720", "metal": "#2c2a28", "compound": "#e4dccd"},
       {"living": "#f2ece1", "dining": "#efe6d6", "bedroom": "#dfe3d3", "master": "#cfd5c0", "kids": "#e9e4c9",
        "kitchen": "#f4efe4", "study": "#e3dccd", "puja": "#f3e2b8", "circulation": "#eee7da", "ceiling": "#f7f4ee",
        "bath_tile": "#d9d4c8", "kitchen_tile": "#8aa38e", "accent_wall": "#8c9a78", "floor_stone": "#cdbfa6",
        "floor_wood": "#8a5a36", "floor_tile": "#c9c3b6", "joinery": "#6e4528", "upholstery": "#d7cdb9",
        "accent": "#6f8662", "metal_in": "#3b352f"}),
    _s("chettinad_ochre", "Chettinad Ochre",
       "Egg-plaster ochre and oxide red, Athangudi tiles, Burma teak and brass.",
       "warm bold yellow ochre red earthy wood heritage", "chettinad traditional_indian indo_saracenic",
       {"plaster": "#e6c27a", "trim": "#f2e3c2", "clad": "#8e3b26", "roof": "#9c3a22", "frame": "#3d2a1d",
        "door": "#4b2a16", "metal": "#2a2420", "compound": "#e9d3a4"},
       {"living": "#f1dfb5", "dining": "#efd3a0", "bedroom": "#ead9bf", "master": "#d9b98c", "kids": "#f0e0a8",
        "kitchen": "#f3e6c8", "study": "#e6d2b0", "puja": "#f0c96a", "circulation": "#f0e2c4", "ceiling": "#fbf4e4",
        "bath_tile": "#d8cbb3", "kitchen_tile": "#2f5d73", "accent_wall": "#a3432b", "floor_stone": "#b8553a",
        "floor_wood": "#6b3f22", "floor_tile": "#c8b28e", "joinery": "#5a3218", "upholstery": "#a3432b",
        "accent": "#2f5d73", "metal_in": "#b08a3e"}),
    _s("jaipur_rose", "Jaipur Rose",
       "Rose sandstone and lime-white jaalis; blush, saffron and deep teal inside.",
       "pink warm bold heritage red", "rajasthani_haveli indo_saracenic traditional_indian",
       {"plaster": "#e2b4a0", "trim": "#f3e9dc", "clad": "#c07a5f", "roof": "#9b4d38", "frame": "#f3ece2",
        "door": "#2f5552", "metal": "#2c2a2a", "compound": "#e8c5b4"},
       {"living": "#f3e1d6", "dining": "#f0d6c6", "bedroom": "#efdcd2", "master": "#e3c2b2", "kids": "#f4e3c8",
        "kitchen": "#f5ebe1", "study": "#e8d6c9", "puja": "#f2c46b", "circulation": "#f2e6dc", "ceiling": "#fbf6f1",
        "bath_tile": "#e0d3c8", "kitchen_tile": "#2f5552", "accent_wall": "#b85f45", "floor_stone": "#d9c0a8",
        "floor_wood": "#7a4a30", "floor_tile": "#d7c9bb", "joinery": "#6a3b26", "upholstery": "#2f5552",
        "accent": "#d68a2e", "metal_in": "#b08a3e"}),
    _s("coastal_indigo", "Coastal Indigo",
       "Crisp white walls and indigo shutters; pale oak, linen and sea-glass blues.",
       "cool white blue light fresh coastal", "contemporary tropical_modern modern_minimal coastal",
       {"plaster": "#f6f6f2", "trim": "#e6e7e3", "clad": "#7f8b91", "roof": "#3e4a57", "frame": "#22344d",
        "door": "#22344d", "metal": "#28313b", "compound": "#eceeea"},
       {"living": "#f5f6f3", "dining": "#eef1ef", "bedroom": "#e2e9ee", "master": "#d3dde6", "kids": "#e6efe6",
        "kitchen": "#f6f7f5", "study": "#e3e7ea", "puja": "#f3ead2", "circulation": "#f1f2ef", "ceiling": "#fbfbf9",
        "bath_tile": "#d9e3e8", "kitchen_tile": "#3c5f80", "accent_wall": "#2f4a6b", "floor_stone": "#dcd9d1",
        "floor_wood": "#c2a37c", "floor_tile": "#d6d8d5", "joinery": "#d8c3a2", "upholstery": "#e6e2d8",
        "accent": "#3c5f80", "metal_in": "#8c939a"}),
    _s("japandi_ash", "Japandi Ash",
       "Warm-grey plaster and charcoal frames; ash, linen and a single moss accent.",
       "neutral grey wood calm minimal natural light", "japandi scandinavian wabi_sabi modern_minimal",
       {"plaster": "#dedad2", "trim": "#c8c3b8", "clad": "#5e5850", "roof": "#3a3a3b", "frame": "#2b2a29",
        "door": "#6d5a46", "metal": "#2b2a29", "compound": "#d6d1c7"},
       {"living": "#ebe7df", "dining": "#e7e2d8", "bedroom": "#e2ddd3", "master": "#d6cfc2", "kids": "#e6e1d4",
        "kitchen": "#eeebe5", "study": "#dfd9cd", "puja": "#eee4cc", "circulation": "#e8e4dc", "ceiling": "#f5f3ee",
        "bath_tile": "#cfcac0", "kitchen_tile": "#bdb6a8", "accent_wall": "#7d7a66", "floor_stone": "#cfc8bb",
        "floor_wood": "#b89a74", "floor_tile": "#c9c4ba", "joinery": "#a88a66", "upholstery": "#dcd4c6",
        "accent": "#6e7458", "metal_in": "#2b2a29"}),
    _s("concrete_walnut", "Concrete & Walnut",
       "Off-white render, board-marked concrete and black steel; walnut and smoke inside.",
       "grey dark modern wood neutral bold", "contemporary industrial modern_minimal",
       {"plaster": "#ecebe8", "trim": "#9c9a96", "clad": "#7b7974", "roof": "#2f3032", "frame": "#1d1d1e",
        "door": "#4a3424", "metal": "#1d1d1e", "compound": "#a9a7a2"},
       {"living": "#efeeeb", "dining": "#e9e8e4", "bedroom": "#dcdad6", "master": "#c9c6c1", "kids": "#e4e3dc",
        "kitchen": "#f0efec", "study": "#d8d6d1", "puja": "#efe5cf", "circulation": "#e6e5e1", "ceiling": "#f6f6f4",
        "bath_tile": "#bdbbb6", "kitchen_tile": "#3a3a3c", "accent_wall": "#4f4b47", "floor_stone": "#b4b1ab",
        "floor_wood": "#5c3d28", "floor_tile": "#a9a7a2", "joinery": "#5c3d28", "upholstery": "#8f8a83",
        "accent": "#b3612f", "metal_in": "#1d1d1e"}),
    _s("sage_courtyard", "Sage Courtyard",
       "Pale sage render and terracotta jaali; olive, clay and cane within.",
       "green earthy natural calm warm", "biophilic tropical_modern kerala_vernacular contemporary",
       {"plaster": "#d9ddcc", "trim": "#eef0e6", "clad": "#a35f40", "roof": "#8f4a31", "frame": "#3f4635",
        "door": "#59452f", "metal": "#2f332b", "compound": "#dfe2d5"},
       {"living": "#ecede3", "dining": "#e7e9dc", "bedroom": "#dbe2d2", "master": "#c7d1bb", "kids": "#ebe6c9",
        "kitchen": "#f1f1ea", "study": "#dcdfcf", "puja": "#f1e2b8", "circulation": "#e9eade", "ceiling": "#f7f7f2",
        "bath_tile": "#d4d8cb", "kitchen_tile": "#b56a47", "accent_wall": "#6e7b55", "floor_stone": "#c8b79c",
        "floor_wood": "#94673f", "floor_tile": "#cdc8b9", "joinery": "#8c6a45", "upholstery": "#d9cdb3",
        "accent": "#b56a47", "metal_in": "#3f4635"}),
    _s("terracotta_sun", "Terracotta Sun",
       "Burnt-orange render with cream bands; mustard, rust and cane inside.",
       "warm orange earthy bold red vibrant", "mid_century_modern bohemian traditional_indian contemporary",
       {"plaster": "#c9774f", "trim": "#f0e2cb", "clad": "#e8d6b8", "roof": "#8a3a22", "frame": "#f0e8da",
        "door": "#3b2a1e", "metal": "#2c2622", "compound": "#e6c7a8"},
       {"living": "#f3e4cf", "dining": "#f0dcc0", "bedroom": "#eedfcc", "master": "#e2c3a3", "kids": "#f4dc9e",
        "kitchen": "#f5eadb", "study": "#e8d4bc", "puja": "#f2c46b", "circulation": "#f1e5d3", "ceiling": "#faf4ea",
        "bath_tile": "#e1d5c3", "kitchen_tile": "#c0603a", "accent_wall": "#b9562f", "floor_stone": "#c88e66",
        "floor_wood": "#7d4a2b", "floor_tile": "#d6c3a8", "joinery": "#7d4a2b", "upholstery": "#d39a3c",
        "accent": "#b9562f", "metal_in": "#b08a3e"}),
    _s("nordic_fog", "Nordic Fog",
       "Soft white and pale blue-grey outside; birch, wool and powder blue within.",
       "cool light pastel white blue calm", "scandinavian modern_minimal contemporary",
       {"plaster": "#f1f2f0", "trim": "#d7dcdf", "clad": "#a9b3b9", "roof": "#46505a", "frame": "#f4f4f2",
        "door": "#6f8796", "metal": "#3c444b", "compound": "#e5e8e8"},
       {"living": "#f3f4f2", "dining": "#eef0ee", "bedroom": "#e3e9ed", "master": "#d4dde4", "kids": "#efe6dc",
        "kitchen": "#f5f6f4", "study": "#e5e8e8", "puja": "#f2ead6", "circulation": "#f0f1ef", "ceiling": "#fafbfa",
        "bath_tile": "#e1e6e8", "kitchen_tile": "#a9bac6", "accent_wall": "#8aa1b1", "floor_stone": "#dad7cf",
        "floor_wood": "#d2b48c", "floor_tile": "#dcdedc", "joinery": "#e1cfae", "upholstery": "#c9ccc8",
        "accent": "#6f8796", "metal_in": "#9aa0a4"}),
    _s("teal_midcentury", "Mid-century Teal",
       "Cream render and teal doors; walnut, mustard and deep teal inside.",
       "retro teal blue green bold warm wood vibrant", "mid_century_modern bohemian contemporary",
       {"plaster": "#efe6d2", "trim": "#d6c7a6", "clad": "#7c5a3c", "roof": "#3a4b4c", "frame": "#2c3b3a",
        "door": "#1f6b6b", "metal": "#2a2c2c", "compound": "#e6dcc6"},
       {"living": "#f1e9d8", "dining": "#ece2cc", "bedroom": "#dfe5df", "master": "#cbd8d3", "kids": "#f2dd9c",
        "kitchen": "#f4eee1", "study": "#e3dcc9", "puja": "#f2d27a", "circulation": "#eee6d5", "ceiling": "#faf6ec",
        "bath_tile": "#cfe0dc", "kitchen_tile": "#1f6b6b", "accent_wall": "#1f6b6b", "floor_stone": "#cdbb98",
        "floor_wood": "#6b4428", "floor_tile": "#d3cab6", "joinery": "#6b4428", "upholstery": "#d6a23a",
        "accent": "#1f6b6b", "metal_in": "#b08a3e"}),
    _s("charcoal_modern", "Charcoal Modern",
       "A charcoal and timber facade; gallery-white rooms, black steel and brass.",
       "dark black grey bold modern white minimal", "contemporary industrial modern_minimal",
       {"plaster": "#4a4a4b", "trim": "#2c2c2d", "clad": "#8a6a4c", "roof": "#232324", "frame": "#161616",
        "door": "#8a6a4c", "metal": "#161616", "compound": "#5a5a5b"},
       {"living": "#f4f4f2", "dining": "#efefec", "bedroom": "#e6e5e2", "master": "#3f4042", "kids": "#ece8e0",
        "kitchen": "#f5f5f3", "study": "#d9d8d4", "puja": "#f1e6cc", "circulation": "#efefed", "ceiling": "#fafaf9",
        "bath_tile": "#2e2e30", "kitchen_tile": "#1d1d1e", "accent_wall": "#2e2e30", "floor_stone": "#c9c7c2",
        "floor_wood": "#7a5a3e", "floor_tile": "#8e8c88", "joinery": "#2e2e30", "upholstery": "#b9b4ab",
        "accent": "#b08a3e", "metal_in": "#161616"}),
    _s("desert_sand", "Desert Sand",
       "Sand render and limestone; taupe, oatmeal and smoked oak inside.",
       "beige neutral warm light earthy natural", "contemporary indo_saracenic modern_minimal tropical_modern",
       {"plaster": "#e3d5bd", "trim": "#f2ebde", "clad": "#c2ab88", "roof": "#7c5a40", "frame": "#3f3a33",
        "door": "#6b4e35", "metal": "#2f2b26", "compound": "#e8dcc8"},
       {"living": "#efe7da", "dining": "#ebe1d1", "bedroom": "#e6dccc", "master": "#d6c6ae", "kids": "#efe2c6",
        "kitchen": "#f3ede3", "study": "#e2d6c3", "puja": "#f1e0b6", "circulation": "#ede6da", "ceiling": "#f8f4ec",
        "bath_tile": "#ddd2c1", "kitchen_tile": "#bfa889", "accent_wall": "#a68a68", "floor_stone": "#d8cab2",
        "floor_wood": "#8b6a4c", "floor_tile": "#d3c8b6", "joinery": "#8b6a4c", "upholstery": "#d6cab5",
        "accent": "#8f6a45", "metal_in": "#3f3a33"}),
)

BY_ID = {s.id: s for s in SCHEMES}

# ---------------------------------------------------------------------------
# Reading the client's own words
# ---------------------------------------------------------------------------

#: Colour names a client actually uses, with the families they belong to.
NAMED: dict[str, tuple[str, str]] = {
    "white": ("#f5f4f0", "white light"), "off white": ("#efebe2", "white light neutral"),
    "ivory": ("#f3ecd9", "white warm light"), "cream": ("#f0e6cf", "warm light white"),
    "beige": ("#e3d5bd", "beige neutral warm"), "sand": ("#e0cfb1", "beige warm neutral"),
    "taupe": ("#b9a994", "neutral beige"), "grey": ("#a8a8a6", "grey neutral"), "gray": ("#a8a8a6", "grey neutral"),
    "light grey": ("#d4d4d1", "grey light"), "dark grey": ("#4d4d4e", "grey dark"), "charcoal": ("#3a3a3b", "dark grey"),
    "black": ("#1c1c1d", "dark black"), "brown": ("#7a5233", "earthy warm wood"), "chocolate": ("#5a3a24", "dark earthy"),
    "wood": ("#8a5f3c", "wood warm natural"), "wooden": ("#8a5f3c", "wood warm natural"), "teak": ("#7a4b2a", "wood warm"),
    "walnut": ("#5c3d28", "wood dark"), "oak": ("#c2a37c", "wood light"),
    "terracotta": ("#b9603e", "earthy warm orange"), "rust": ("#a2492a", "warm orange red"),
    "orange": ("#d9773a", "orange warm bold"), "peach": ("#f1c4a2", "warm pastel orange"),
    "coral": ("#e07a62", "warm pink bold"), "red": ("#b23a2e", "red bold warm"), "maroon": ("#6b2328", "red dark"),
    "pink": ("#e8b4b0", "pink pastel warm"), "blush": ("#efd0c6", "pink pastel light"), "rose": ("#d99a92", "pink warm"),
    "mustard": ("#cf9f2e", "yellow warm bold"), "yellow": ("#f0d56b", "yellow warm bright"),
    "ochre": ("#cc8e35", "yellow earthy warm"), "gold": ("#c9a14a", "yellow warm"), "lemon": ("#f2e58f", "yellow light"),
    "green": ("#6f8a5e", "green natural"), "sage": ("#a9b59a", "green calm light"), "olive": ("#6e7346", "green earthy"),
    "mint": ("#c6e2cf", "green pastel light"), "emerald": ("#2e6b4f", "green bold dark"),
    "forest green": ("#2f4a34", "green dark"), "teal": ("#1f6b6b", "teal blue green bold"),
    "turquoise": ("#3fa3a0", "teal blue bright"), "blue": ("#4a6d92", "blue cool"), "light blue": ("#cddceb", "blue light pastel cool"),
    "sky blue": ("#a9cbe3", "blue light cool"), "powder blue": ("#c9d8e4", "blue pastel light cool"),
    "navy": ("#22344d", "blue dark cool"), "indigo": ("#2f3f6b", "blue dark cool"),
    "lavender": ("#c9bfdc", "purple pastel cool"), "purple": ("#6c4f8a", "purple bold"), "lilac": ("#d4c3de", "purple pastel"),
}

#: Words for a whole family, liked or avoided.
FAMILIES = {
    "warm": "warm", "earthy": "earthy", "earth": "earthy", "natural": "natural", "neutral": "neutral",
    "pastel": "pastel", "pastels": "pastel", "bold": "bold", "vibrant": "vibrant", "bright": "vibrant",
    "colourful": "vibrant", "colorful": "vibrant", "dark": "dark", "moody": "dark", "light": "light", "airy": "light",
    "cool": "cool", "calm": "calm", "minimal": "minimal", "minimalist": "minimal", "monochrome": "grey",
    "heritage": "heritage", "traditional": "heritage", "retro": "retro", "coastal": "coastal", "fresh": "fresh",
}

#: Surfaces the client can name, to the scheme slots they mean.
SURFACES: list[tuple[str, tuple[str, ...]]] = [
    (r"accent wall|feature wall", ("accent_wall",)),
    (r"main door|front door|entrance door", ("door",)),
    (r"window frames?|frames?|windows?", ("frame",)),
    (r"exterior|facade|façade|outside|outer walls?|elevation", ("plaster",)),
    (r"roof", ("roof",)),
    (r"compound|boundary wall|gate", ("compound",)),
    (r"master bed(room)?|master", ("master",)),
    (r"kids?'? ?(bed)?room|children'?s? ?(bed)?room|kids", ("kids",)),
    (r"bedrooms?", ("bedroom", "master", "kids")),
    (r"living( room)?|hall|lounge", ("living",)),
    (r"dining", ("dining",)),
    (r"kitchen (tiles?|backsplash|dado)|backsplash", ("kitchen_tile",)),
    (r"kitchen", ("kitchen",)),
    (r"puja|pooja|mandir|prayer", ("puja",)),
    (r"study|office|library", ("study",)),
    (r"bath(room)?s?|toilets?|washrooms?", ("bath_tile",)),
    (r"wooden floors?|wood floors?", ("floor_stone", "floor_wood")),
    (r"floors?|flooring", ("floor_stone",)),
    (r"sofas?|upholstery|cushions?|fabrics?", ("upholstery",)),
    (r"cabinets?|wardrobes?|joinery|cupboards?|kitchen units?", ("joinery",)),
    (r"ceilings?", ("ceiling",)),
    (r"interior walls?|walls?|inside|interiors?", ("living", "dining", "bedroom", "master", "kids", "kitchen",
                                                  "study", "circulation")),
]

_NEG = re.compile(r"\b(no|not|avoid|without|hate|dislike|don'?t (?:like|want)|never|except)\b")


@dataclass(slots=True)
class ColourPrefs:
    likes: set[str] = field(default_factory=set)
    avoids: set[str] = field(default_factory=set)
    overrides: dict[str, str] = field(default_factory=dict)
    mentions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"likes": sorted(self.likes), "avoids": sorted(self.avoids),
                "overrides": dict(self.overrides), "mentions": list(self.mentions)}

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ColourPrefs:
        d = d or {}
        return cls(set(d.get("likes", ())), set(d.get("avoids", ())), dict(d.get("overrides", {})), list(d.get("mentions", ())))

    def __bool__(self) -> bool:
        return bool(self.likes or self.avoids or self.overrides)


def preferences_from_text(text: str | None) -> ColourPrefs:
    """Colour preferences from free text.

    In each clause, a named colour beside a named surface ("sage green
    bedrooms", "front door in navy") becomes an exact override for that
    surface; a colour or family word on its own becomes a like; either after a
    negation ("no pink", "avoid dark colours") becomes an avoid.
    """
    prefs = ColourPrefs()
    if not text:
        return prefs
    names = sorted(NAMED, key=len, reverse=True)
    name_re = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")
    for clause in re.split(r"[.;\n]|,|\bbut\b|\bwhile\b", text.lower()):
        clause = clause.strip()
        if not clause:
            continue
        neg = _NEG.search(clause)
        colours = [(m.start(), m.end(), m.group(1)) for m in name_re.finditer(clause)]
        taken: list[tuple[int, int]] = []
        surfaces = []
        for pat, slots in SURFACES:
            for m in re.finditer(r"\b(?:" + pat + r")\b", clause):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue      # "kitchen" inside "kitchen backsplash" is already claimed
                taken.append((m.start(), m.end()))
                surfaces.append((m.start(), m.end(), slots, m.group(0)))
        used: set[int] = set()
        for s0, s1, slots, label in sorted(surfaces):
            # The colour describing a surface sits just before it ("navy door")
            # or just after it ("door in navy").
            best, gap = None, 99
            for k, (c0, c1, _name) in enumerate(colours):
                if k in used:
                    continue
                d = s0 - c1 if c1 <= s0 else (c0 - s1 + 4 if c0 >= s1 else 99)
                if 0 <= d < gap and d <= 24:
                    best, gap = k, d
            if best is None:
                if "wood" in label or ("floor" in label and "wood" in clause):
                    prefs.overrides["floor_stone"] = NAMED["wood"][0]
                    prefs.mentions.append("wooden floors")
                continue
            if neg and neg.start() < colours[best][0]:
                continue
            used.add(best)
            # "sage green": the first of two adjacent colour words is the specific one.
            if best > 0 and best - 1 not in used and colours[best][0] - colours[best - 1][1] <= 1:
                best -= 1
                used.add(best)
            name = colours[best][2]
            for slot in slots:
                if slot == "floor_wood":
                    continue
                prefs.overrides[slot] = NAMED[name][0]
            prefs.mentions.append(f"{name} {label}")
        for word, fam in FAMILIES.items():
            m = re.search(rf"\b{re.escape(word)}\b", clause)
            if not m or (fam == "light" and colours):
                continue
            (prefs.avoids if neg and neg.start() < m.start() else prefs.likes).add(fam)
        for k, (c0, _c1, name) in enumerate(colours):
            if k in used:
                continue
            fams = set(NAMED[name][1].split())
            if neg and neg.start() < c0:
                prefs.avoids |= fams & {"pink", "red", "orange", "yellow", "green", "blue", "purple", "teal",
                                        "dark", "black", "grey", "white", "beige", "bold"}
            else:
                prefs.likes |= fams
    prefs.likes -= prefs.avoids
    return prefs


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _hls(hex_: str) -> tuple[float, float, float]:
    v = hex_.lstrip("#")
    r, g, b = (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def luminance(hex_: str) -> float:
    v = hex_.lstrip("#")
    r, g, b = (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


#: Classical Vastu colour families for a room by the zone it sits in.
VASTU_ZONE_COLOURS = {
    "NE": {"white", "light", "yellow", "blue"}, "E": {"white", "light", "green"},
    "SE": {"orange", "warm", "red", "pink"}, "S": {"red", "warm", "orange", "earthy"},
    "SW": {"earthy", "beige", "warm", "neutral", "brown"}, "W": {"blue", "grey", "cool", "white"},
    "NW": {"white", "grey", "light", "cream"}, "N": {"green", "blue", "light"},
}


def _families(hex_: str) -> set[str]:
    h, l, s = _hls(hex_)
    deg = h * 360
    fams = set()
    fams.add("light" if l > 0.78 else "dark" if l < 0.32 else "mid")
    if s < 0.12:
        fams |= {"white"} if l > 0.86 else {"grey", "neutral"}
        return fams
    if deg < 18 or deg >= 340:
        fams |= {"red", "warm"}
    elif deg < 45:
        fams |= {"orange", "warm", "earthy"} if l < 0.7 else {"beige", "warm", "neutral", "earthy"}
    elif deg < 70:
        fams |= {"yellow", "warm"} if s > 0.45 else {"beige", "neutral", "warm"}
    elif deg < 165:
        fams |= {"green"}
    elif deg < 200:
        fams |= {"teal", "cool"}
    elif deg < 260:
        fams |= {"blue", "cool"}
    elif deg < 300:
        fams |= {"purple", "cool"}
    else:
        fams |= {"pink", "warm"}
    return fams


def _zone(plan, room) -> str | None:
    try:
        from aip.domain.geometry import bearing_between

        centre = plan.levels[0].envelope().centre
        b = bearing_between(centre, room.centre, plan.site.north_angle)
    except Exception:  # noqa: BLE001
        return None
    if room.centre.distance_to(centre) < 1.0:
        return None
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((b + 22.5) % 360) // 45)]


def room_slot(room_type: str) -> str:
    t = room_type
    if t in {"master_bedroom"}:
        return "master"
    if t in {"bedroom", "guest_bedroom"}:
        return "bedroom"
    if t in {"children_bedroom"}:
        return "kids"
    if t in {"living", "family", "drawing", "family_lounge", "home_theatre"}:
        return "living"
    if t in {"dining"}:
        return "dining"
    if t in {"kitchen", "pantry"}:
        return "kitchen"
    if t in {"study", "home_office", "library"}:
        return "study"
    if t in {"puja"}:
        return "puja"
    if t in {"bathroom", "toilet", "powder"}:
        return "bath_tile"
    return "circulation"


def apply_overrides(scheme: Scheme, prefs: ColourPrefs) -> Scheme:
    if not prefs.overrides:
        return scheme
    ext = {k: prefs.overrides.get(k, v) for k, v in scheme.exterior.items()}
    inn = {k: prefs.overrides.get(k, v) for k, v in scheme.interior.items()}
    return replace(scheme, exterior=ext, interior=inn)


def rank(plan, prefs: ColourPrefs | None = None) -> list[dict[str, Any]]:
    """Every scheme, best first, with its score and the reasons for it."""
    prefs = prefs if prefs is not None else ColourPrefs.from_dict((plan.metadata or {}).get("colour_preferences"))
    style = (plan.style or "contemporary")
    hot = abs(float(getattr(plan.site, "latitude", 20.0))) < 28.0
    vastu_on = str((plan.metadata or {}).get("vastu_mode", "balanced")) not in {"ignore", "off"}
    rooms = [(r, _zone(plan, r)) for lv in plan.levels for r in lv.rooms]
    out = []
    for base in SCHEMES:
        s = apply_overrides(base, prefs)
        score, why = 0.5, []
        if style in s.styles:
            score += 0.25
            why.append(f"suits the {style.replace('_', ' ')} style")
        ext_l = luminance(s.exterior["plaster"])
        if hot:
            if ext_l > 0.7:
                score += 0.12
                why.append("light facade reflects the heat")
            elif ext_l < 0.45:
                score -= 0.2
                why.append("dark facade absorbs heat in this climate")
        if vastu_on and rooms:
            hits = total = 0
            for r, z in rooms:
                slot = room_slot(r.type.value)
                if z is None or slot in {"circulation", "bath_tile"}:
                    continue
                total += 1
                if _families(s.colour(slot)) & VASTU_ZONE_COLOURS[z]:
                    hits += 1
            if total:
                share = hits / total
                score += 0.15 * share
                if share >= 0.6:
                    why.append(f"Vastu colours sit right in {hits} of {total} rooms")
        if prefs:
            fams = set(s.tags) | _families(s.exterior["plaster"]) | _families(s.interior["living"])
            liked = prefs.likes & fams
            hated = prefs.avoids & fams
            score += 0.12 * len(liked) - 0.3 * len(hated)
            if liked:
                why.append("matches your " + ", ".join(sorted(liked)))
            if hated:
                why.append("uses " + ", ".join(sorted(hated)) + ", which you wanted to avoid")
            if prefs.overrides:
                why.append("with your colours: " + ", ".join(prefs.mentions[:3]))
        out.append({
            "id": s.id, "name": s.name, "story": s.story, "score": round(score, 3), "reasons": why,
            "exterior": {k: s.exterior[k] for k in ("plaster", "trim", "clad", "roof", "frame", "door")},
            "interior": {k: s.interior[k] for k in ("living", "master", "bedroom", "kitchen", "accent_wall",
                                                     "floor_stone", "joinery", "upholstery")},
        })
    out.sort(key=lambda d: -d["score"])
    return out


def resolve(plan, scheme_id: str | None = None, prefs: ColourPrefs | None = None) -> Scheme:
    """The scheme to build with: the one asked for, else the top-ranked."""
    prefs = prefs if prefs is not None else ColourPrefs.from_dict((plan.metadata or {}).get("colour_preferences"))
    if scheme_id and scheme_id in BY_ID:
        return apply_overrides(BY_ID[scheme_id], prefs)
    return apply_overrides(BY_ID[rank(plan, prefs)[0]["id"]], prefs)
