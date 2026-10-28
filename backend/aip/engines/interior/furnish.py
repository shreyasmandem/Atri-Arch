"""Dressing a furnished house so it reads as a home in VR.

The interior engine decides what stands where; this module decides what that
looks like up close, and adds what makes a room lived in:

* **Real pieces.** Where a photographed, scanned model exists (Poly Haven, CC0),
  a catalogue item is drawn with it instead of the 3D builder's own shapes: a
  teak-and-leather armchair, a fluted sideboard, a brass diya lantern.
* **The finishing layer** an Indian home has and a plan never shows: a ceiling
  fan in every bedroom and living room, a pendant over the dining table,
  cushions on the sofa, a tea set on the coffee table, a brass vase on the
  console, a lamp on the study desk, a lantern in the puja room.
* **Paintings.** Above the bed and the sofa, and wherever the client hangs
  one: public-domain Indian art (Raja Ravi Varma, Rajput and Pahari miniatures).

Everything is returned as placements in model space (metres, y up), so the
viewer can load each piece once and stand it where it belongs.
"""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from aip.domain.plan import FloorPlan, RoomType
from aip.engines.interior.engine import InteriorScheme, PlacedFurniture, _window_segments, design_interior

T = RoomType

#: Catalogue items drawn with a real model: item -> (asset, how it is fitted[, how high it hangs]).
#: "box" scales the model evenly to fit the item's footprint and height;
#: "height" scales it to the item's height (a plant may spread wider). A third
#: value lifts it off the floor: metres, or "ceiling" to hang it from the ceiling.
MODELS: dict[str, tuple] = {
    **{i: ("modern_arm_chair_01", "box") for i in ("accent_chair", "accent_chair_x", "armchair", "wing_chair_a",
                                                   "wing_chair_b")},
    "reading_chair": ("mid_century_lounge_chair", "box"),
    **{i: ("modern_coffee_table_01", "box") for i in ("coffee_table", "coffee_table_x", "centre_table")},
    **{i: ("side_table_01", "box") for i in ("nightstand", "nightstand_l", "nightstand_r", "side_table")},
    **{i: ("wooden_display_shelves_01", "box") for i in ("bookshelf", "bookshelf_x", "shelving")},
    **{i: ("modern_wooden_cabinet", "box") for i in ("sideboard", "console", "console_x")},
    "dining_round": ("round_wooden_table_01", "box"),
    "plant_small": ("potted_plant_02", "height"),
    "plant_tall": ("potted_plant_02", "height"),
    "tulsi": ("potted_plant_02", "height"),
    "basket": ("wicker_basket_01", "box"),
    "chowki": ("chinese_tea_table", "box"),
    "candles": ("brass_candleholders", "box"),
    "chandelier": ("Chandelier_01", "box", "ceiling"),
    "pendant_light": ("modern_ceiling_lamp_01", "box", "ceiling"),
    "wall_clock": ("wall_clock", "box", 1.95),
    "books": ("book_encyclopedia_set_01", "box"),
    "planter_box": ("planter_box_01", "box"),
    "succulent": ("potted_plant_04", "height"),
    "floor_vase": ("brass_vase_03", "height"),
    "brass_pot": ("brass_pot_01", "box"),
}

_BEDS = {T.MASTER_BEDROOM, T.BEDROOM, T.GUEST_BEDROOM, T.CHILDREN_BEDROOM}
_FANNED = _BEDS | {T.LIVING, T.DRAWING, T.FAMILY, T.STUDY, T.HOME_OFFICE, T.LIBRARY}
_SOFAS = ("sofa", "sectional", "diwan")
_DESKS = ("desk", "study_desk")
_TOPS = ("console", "sideboard")

ART_DIR = Path(__file__).resolve().parents[4] / "frontend" / "assets" / "art"


@lru_cache(maxsize=1)
def artworks() -> list[dict[str, Any]]:
    """The paintings a room may hang, with their credits."""
    try:
        return json.loads((ART_DIR / "art.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _pick(seed: str, n: int) -> int:
    return int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16) % max(1, n)


def _local(p: PlacedFurniture, u: float, v: float) -> tuple[float, float]:
    """A point in an item's frame (u across, v from its back edge) in plan coordinates."""
    rot = math.radians(p.rotation)
    lx, ly = u, -(p.depth / 2) + v
    return p.x + lx * math.cos(rot) - ly * math.sin(rot), p.y + lx * math.sin(rot) + ly * math.cos(rot)


def _place(asset: str, x: float, y: float, z: float, rotation: float, w: float, d: float, h: float, *,
           fit: str = "box", room_id: str, level: int, colour: str | None = None) -> dict[str, Any]:
    # Plan (x, y) to model space (x, -z); a model's front is +z, an item's is its local +y.
    return {"asset": asset, "x": round(x, 3), "y": round(z, 3), "z": round(-y, 3),
            "yaw": round(math.radians(rotation) + math.pi, 4), "w": w, "d": d, "h": h,
            "fit": fit, "colour": colour, "room_id": room_id, "level": level}


def _painting(art_id: str, p: PlacedFurniture, z: float, width: float, *, room_id: str, level: int) -> dict[str, Any]:
    art = next((a for a in artworks() if a["id"] == art_id), None)
    if art is None:
        return {}
    aspect = float(art.get("aspect", 0.8))
    w = min(width, 1.1 if aspect >= 1 else 0.75)
    h = w / aspect
    # Plan rooms are drawn to the wall centrelines, so an item's back edge sits
    # inside the wall: hang the frame a hand's width in front of it.
    x, y = _local(p, 0.0, 0.15)
    return {"art": art_id, "title": art["title"], "artist": art["artist"], "x": round(x, 3),
            "y": round(z + h / 2, 3), "z": round(-y, 3), "yaw": round(math.radians(p.rotation) + math.pi, 4),
            "w": round(w, 3), "h": round(h, 3), "room_id": room_id, "level": level}


def _window_behind(p: PlacedFurniture, windows) -> bool:
    """Is there a window in the wall behind this item, across the middle of it?"""
    bx0, by0 = _local(p, -p.width * 0.4, 0.0)
    bx1, by1 = _local(p, p.width * 0.4, 0.0)
    for a, b, _ in windows:
        # The window lies along the item's back edge, within a wall's thickness of it.
        ux, uy = bx1 - bx0, by1 - by0
        length = math.hypot(ux, uy) or 1.0
        ux, uy = ux / length, uy / length
        off = max(abs((a.x - bx0) * uy - (a.y - by0) * ux), abs((b.x - bx0) * uy - (b.y - by0) * ux))
        if off > 0.35:
            continue
        ta, tb = sorted(((a.x - bx0) * ux + (a.y - by0) * uy, (b.x - bx0) * ux + (b.y - by0) * uy))
        if tb > 0 and ta < length:
            return True
    return False


def furnishings(plan: FloorPlan, scheme: InteriorScheme | None = None) -> dict[str, Any]:
    """Every real model, decoration and painting in the house, placed in model space."""
    from aip.engines.experience.arch3d import PLINTH, SLAB

    scheme = scheme or design_interior(plan)
    bases, ceilings, level_of = [], [], {}
    y = PLINTH
    for lv in plan.levels:
        bases.append(y)
        ceilings.append(y + lv.floor_to_floor - SLAB)
        for r in lv.rooms:
            level_of[r.id] = lv.index
        y += lv.floor_to_floor
    rooms = {r.id: r for r in plan.all_rooms}
    edits = (plan.metadata or {}).get("interior_edits") or {}
    arts = artworks()
    models: list[dict[str, Any]] = []
    paintings: list[dict[str, Any]] = []
    for ri in scheme.rooms:
        li = level_of.get(ri.room_id)
        room = rooms.get(ri.room_id)
        if li is None or room is None:
            continue
        base, ceil = bases[li], ceilings[li]
        kw = {"room_id": ri.room_id, "level": li}
        for p in ri.furniture:
            iid = p.item_id
            parent = None
            if iid in MODELS:
                asset, fit, *lift = MODELS[iid]
                lift = lift[0] if lift else 0.0
                y0 = ceil - p.height - 0.05 if lift == "ceiling" else base + lift
                parent = len(models)
                models.append(_place(asset, p.x, p.y, y0, p.rotation, p.width, p.depth, p.height, fit=fit,
                                     colour=p.colour, **kw))
            on = {"on": parent} if parent is not None else {}
            if iid.startswith(_SOFAS):
                x, y_ = _local(p, 0.0, 0.36)
                models.append(_place("throw_pillows_01", x, y_, base + 0.46, p.rotation, min(1.0, p.width * 0.5),
                                     0.4, 0.5, **kw))
            elif iid.startswith(("coffee_table", "centre_table")):
                x, y_ = _local(p, 0.1, p.depth / 2)
                models.append({**_place("tea_set_01", x, y_, base + 0.42, p.rotation, 0.45, 0.3, 0.22, **kw), **on})
            elif iid.startswith(_DESKS):
                x, y_ = _local(p, -p.width / 2 + 0.2, 0.15)
                models.append(_place("desk_lamp_arm_01", x, y_, base + 0.76, p.rotation, 0.3, 0.3, 0.5, **kw))
                x, y_ = _local(p, p.width / 2 - 0.25, 0.12)
                models.append(_place("book_encyclopedia_set_01", x, y_, base + 0.76, p.rotation, 0.4, 0.2, 0.28, **kw))
            elif iid.startswith(_TOPS):
                x, y_ = _local(p, p.width / 2 - 0.2, p.depth / 2)
                models.append({**_place("brass_vase_01", x, y_, base + 0.8, p.rotation, 0.25, 0.25, 0.35, **kw), **on})
            elif iid.startswith("dining") and iid != "dining_round":
                models.append(_place("ceramic_vase_02", p.x, p.y, base + 0.77, 0, 0.25, 0.25, 0.28, **kw))
                models.append(_place("modern_ceiling_lamp_01", p.x, p.y, ceil - 0.75, 0, 0.6, 0.6, 0.75, **kw))
            elif iid.startswith("mandir"):
                x, y_ = _local(p, 0.0, p.depth + 0.4)
                models.append(_place("brass_diya_lantern", x, y_, ceil - 0.9, p.rotation, 0.3, 0.3, 0.9, **kw))
            # Paintings: the ones the client hung, and one over the bed and the main sofa.
            if iid == "wall_art":
                art_id = p.art or (arts[_pick(p.uid or ri.room_id, len(arts))]["id"] if arts else "")
                paintings.append(_painting(art_id, p, base + 1.05, p.width, **kw))
        room_art = ((edits.get(ri.room_id) or {}).get("finishes") or {}).get("art")
        if arts and room_art != "none":
            # Over the bed head, else the sofa, else a console: the first of
            # those whose wall has no window where the painting would hang.
            windows = _window_segments(plan, room)
            order = [p for p in ri.furniture if p.item_id.startswith("bed")] + \
                [p for p in ri.furniture if p.item_id.startswith(_SOFAS)] + \
                [p for p in ri.furniture if p.item_id.startswith(_TOPS + ("crockery", "tv_unit"))]
            anchor = next((p for p in order if not _window_behind(p, windows)), None)
            if anchor is not None:
                art_id = room_art or arts[_pick(ri.room_id, len(arts))]["id"]
                top = base + {"bed_palang": 1.55}.get(anchor.item_id, 1.35 if anchor.item_id.startswith("bed") else 1.15)
                if anchor.item_id.startswith("tv_unit"):
                    top = base + 1.95          # above the screen
                paintings.append(_painting(art_id, anchor, top, anchor.width * 0.7, **kw))
        if room.type in _FANNED and room.area > 6.0:
            c = room.centre
            models.append(_place("ceiling_fan", c.x, c.y, ceil - 0.45, 0, 1.2, 1.2, 0.45, **kw))
        if room.type is T.PUJA and not any(p.item_id.startswith("mandir") for p in ri.furniture):
            c = room.centre
            models.append(_place("brass_diya_lantern", c.x, c.y, ceil - 0.9, 0, 0.3, 0.3, 0.9, **kw))
    return {
        "models": models,
        "paintings": [p for p in paintings if p],
        "skip": sorted({*MODELS, "wall_art"}),
        "assets": "assets/models/",
        "art": "assets/art/",
        "credits": {
            "models": "Poly Haven (polyhaven.com), CC0",
            "paintings": [{"id": a["id"], "title": a["title"], "artist": a["artist"], "source": a["source"],
                           "licence": a["licence"]} for a in arts],
        },
    }


__all__ = ["MODELS", "artworks", "furnishings"]
