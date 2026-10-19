"""Signature homes: complete exteriors after admired house types.

Each look is a whole house designed together - roof, walls, screen,
signature element, colours, site and garden - after a house type people
travel to see: a Goan villa, a Chettinad mansion, a Kerala nalukettu, a
Mumbai Art Deco block, a Bawa tropical house, a Laurie Baker brick house,
a Chandigarh modernist box. They are offered as they are, adapted to the plan
(`Exterior.fitted`), and in colour variations, so each look gives several
designs. Sources are listed in docs/VASTU_AND_DESIGN_GUIDELINES.md, Part 4.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aip.domain.plan import FloorPlan
from aip.engines.experience.exteriors import EXTERIOR_SCHEMES, Exterior

_SCHEMES = {s["id"]: s for s in EXTERIOR_SCHEMES}


def _tints(scheme_id: str) -> dict[str, str]:
    sc = _SCHEMES[scheme_id]
    return {"wall": sc["wall"].lstrip("#"), "clad": sc["clad"].lstrip("#"), "roof_tint": sc["roof"].lstrip("#"),
            "metal": sc["metal"].lstrip("#"), "frame": sc.get("frame", "").lstrip("#"), "door": sc.get("door", "").lstrip("#")}


#: id -> (name, what it is after, the house, colour variations by scheme id)
LOOKS: dict[str, tuple[str, str, dict[str, Any], tuple[str, ...]]] = {
    "goan_villa": ("Goan Villa", "After Goa's Portuguese villas: pastel walls, a verandah of columns, white-framed windows and a tiled roof.",
                   dict(roof="hip", base="plaster", upper="plaster", screen="none", windows="punched", accent="white",
                        feature="colonnade", shade="box", railing="metal", gate="timber", boundary="grille", yard="tulsi"),
                   ("goa_villa", "jodhpur_blue", "pondicherry")),
    "chettinad_mansion": ("Chettinad Mansion", "After the Chettiar mansions of Karaikudi: carved-pillar thinnais, a stepped parapet and Athangudi colours.",
                          dict(roof="flat", base="stone", upper="plaster", screen="jaali", windows="punched", accent="teak",
                               feature="thinnai", parapet="stepped", gate="timber", yard="tulsi"),
                          ("chettinad_blue", "saffron", "ochre_kerala")),
    "kerala_nalukettu": ("Kerala Nalukettu", "After Kerala's nalukettu: a tiled hip roof on deep eaves, timber above a laterite base and a verandah of posts.",
                         dict(roof="hip", base="stone", upper="timber", screen="none", windows="punched", accent="teak",
                              feature="colonnade", shade="deep", canopy="pergola", garden="lush", gate="timber", yard="tulsi"),
                         ("ochre_kerala", "lime_teak", "terracotta")),
    "mumbai_deco": ("Mumbai Art Deco", "After Marine Drive's Indo-Deco: eyebrow chajjas, cornice bands, curving balconies and pastel walls.",
                    dict(roof="flat", base="plaster", upper="plaster", screen="none", windows="band", accent="white",
                         feature="balcony", shade="deep", parapet="grooved", railing="metal", lights="washers"),
                    ("mumbai_deco", "powder_blue", "blush_white")),
    "baker_brick": ("Laurie Baker Brick House", "After Laurie Baker's Kerala houses: exposed brick, a brick jaali curtain for air and a sloping tiled roof.",
                    dict(roof="gable", base="brick", upper="brick", screen="none", windows="punched", accent="terracotta",
                         feature="brickcurtain", shade="deep", garden="lush", boundary="brick", yard="sitout"),
                    ("terracotta", "kutch_mud", "clay_copper")),
    "bawa_tropical": ("Bawa Tropical House", "After Geoffrey Bawa's tropical modernism: white walls under terracotta roofs, colonnades and a reflecting pool.",
                      dict(roof="hip", base="plaster", upper="plaster", screen="louvres", windows="punched", accent="teak",
                           feature="colonnade", shade="deep", canopy="pergola", garden="lush", paving="gravel", yard="koipond"),
                      ("lime_teak", "seaside_white", "sage_oak")),
    "chandigarh_modernist": ("Chandigarh Modernist", "After Le Corbusier's Chandigarh: raw concrete and brick under deep egg-crate sun-breakers.",
                             dict(roof="flat", base="concrete", upper="concrete", screen="none", windows="band", accent="charcoal",
                                  feature="brisesoleil", panel="brick", parapet="plain", boundary="brick", yard="rockgarden"),
                             ("concrete_raw", "basalt_brass", "grey_oak")),
    "rajput_haveli": ("Rajput Haveli", "After the havelis of Jaipur and Jaisalmer: sandstone, jaali, jharokhas on brackets and a stepped parapet.",
                      dict(roof="flat", base="stone", upper="stone", screen="jaali", windows="punched", accent="sand",
                           feature="jharokha", parapet="stepped", boundary="stone", gate="timber", yard="waterwall", lights="washers"),
                      ("sandstone", "jaipur_pink", "haveli_red")),
    "jodhpur_blue_house": ("Jodhpur Blue House", "After the indigo houses of Jodhpur's old city: blue walls, white trims and chhatris on the roof.",
                           dict(roof="flat", base="plaster", upper="plaster", screen="none", windows="punched", accent="white",
                                feature="chhatri", parapet="stepped", gate="timber", yard="tulsi"),
                           ("jodhpur_blue", "powder_blue", "seaside_white")),
    "bengal_bari": ("Bengal Terracotta Bari", "After Bengal's terracotta temples and baris: terracotta skins and a bangla-roofed pavilion.",
                    dict(roof="flat", base="terracotta", upper="plaster", screen="perforated", windows="punched", accent="brass",
                         feature="bangla", parapet="screen", garden="lush", yard="koipond"),
                    ("terracotta", "mustard_clay", "saffron")),
    "mughal_pavilion": ("Mughal Garden Pavilion", "After the Mughal garden pavilions: red sandstone, pointed-arch arcades and a water channel.",
                        dict(roof="flat", base="stone", upper="plaster", screen="jaali", windows="punched", accent="white",
                             feature="arcade", parapet="stepped", boundary="stone", paving="stone", yard="waterwall"),
                        ("haveli_red", "sandstone", "desert_rose")),
    "colonial_bungalow": ("Colonial Bungalow", "After the cantonment bungalows of Bengaluru and Pune: a portico, white trims and a tiled hip roof.",
                          dict(roof="hip", base="plaster", upper="plaster", screen="none", windows="punched", accent="white",
                               feature="portico", shade="slim", canopy="slab", garden="lush", boundary="grille", yard="sitout"),
                          ("cream_brown", "lemon_white", "emerald")),
    "pondicherry_french": ("Pondicherry French House", "After White Town, Pondicherry: ochre walls, white columns, green shutters and a grooved parapet.",
                           dict(roof="flat", base="plaster", upper="plaster", screen="none", windows="punched", accent="white",
                                feature="colonnade", parapet="grooved", gate="timber", boundary="plaster", yard="jhoola"),
                           ("pondicherry", "lemon_white", "mustard_clay")),
    "japandi_courtyard": ("Japandi Courtyard House", "Japanese calm in Indian timber: slats, a round moon gate and a raked rock garden.",
                          dict(roof="slab", base="plaster", upper="timber", screen="slats", windows="band", accent="charcoal",
                               feature="moongate", shade="none", paving="gravel", yard="rockgarden"),
                          ("warm_minimal", "greige", "olive_grove")),
    "concrete_brutalist": ("Brutalist Concrete Villa", "Board-marked concrete, a first-floor room cantilevered over the porch and LED strips at night.",
                           dict(roof="slab", base="concrete", upper="concrete", screen="none", windows="band", accent="graphite",
                                feature="cantilever", lights="strips", paving="concrete", yard="rockgarden"),
                           ("concrete_raw", "slate_modern", "basalt_brass")),
    "glass_pavilion": ("Glass Pavilion", "A minimal white house opened at its corner in glass, with a glass parapet and a water wall.",
                       dict(roof="flat", base="plaster", upper="metal", screen="none", windows="band", accent="white",
                            feature="cornerglass", parapet="glass", railing="glass", lights="strips", yard="waterwall"),
                       ("white_black", "seaside_white", "nordic")),
    "tropical_resort": ("Tropical Resort Villa", "A butterfly roof over timber and bamboo, planter bands spilling green and a koi pond.",
                        dict(roof="butterfly", base="stone", upper="timber", screen="bamboo", windows="band", accent="teak",
                             feature="planterbands", shade="deep", garden="lush", paving="grass", yard="koipond"),
                        ("sage_oak", "forest_lodge", "lime_teak")),
    "nordic_cabin": ("Nordic Black Cabin", "A black timber gable with a glass corner, nothing applied.",
                     dict(roof="gable", base="timber", upper="timber", screen="none", windows="punched", accent="charcoal",
                          feature="cornerglass", shade="none", paving="gravel", yard="sitout"),
                     ("nordic", "grey_oak", "white_black")),
}


def look_designs(plan: FloorPlan, variations: int = 3) -> list[dict[str, Any]]:
    """Every signature home, fitted to this plan, in up to `variations`
    colourways each: (the first is the look's own)."""
    one_floor = len(plan.levels) <= 1
    out: list[dict[str, Any]] = []
    for look_id, (name, inspired, spec, schemes) in LOOKS.items():
        base = Exterior(**spec)
        for k, scheme in enumerate(schemes[:variations]):
            ex, _notes = replace(base, **_tints(scheme)).fitted(one_floor)
            d = ex.to_dict()
            d["name"] = name if k == 0 else f"{name} · {_SCHEMES[scheme]['name']}"
            d["story"] = f"{inspired} {d['story']}"
            d["look"] = look_id
            out.append(d)
    return out
