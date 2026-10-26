"""Architectural 3D model: a building you could show a client, not a stack of blocks.

`model3d` extrudes the plan into coloured boxes. This module builds the house
an architect would model for a presentation, from the same `FloorPlan`:

* **Site** - the plot as lawn, a compound wall with a gate on the road, a paved
  drive to the door, a walkway, and trees and shrubs placed in the free setback
  space so they never stand inside the building or across the drive.
* **Structure** - a raised plinth with entrance steps, floor slabs with a
  projecting drip band at every level, walls to the slab soffit, a staircase
  modelled as real flights, a landing and a handrail.
* **Facade** - exterior plaster in the style's colour with the road elevation of
  the ground floor clad in stone, framed windows with mullions, glass, stone
  sills and concrete sunshades (chajjas) over every exterior window, framed
  door leaves, a canopy over the main entrance, glass-and-steel railings on
  balconies and terraces.
* **Roof** - a tiled hip roof with deep eaves for the vernacular and tropical
  styles, a flat roof with parapet, coping, stair head-room and water tank for
  the rest, and a timber pergola on tropical-modern terraces.
* **Interior** - floor finishes per room (timber in bedrooms, stone in living,
  matt tile in wet rooms), and the interior engine's own furniture placements
  built as recognisable pieces (a bed has a headboard, mattress and pillows; a
  sofa has a seat, back and arms) in the style palette's colours, plus a ceiling
  light per room that glows in a night view.

Materials are glTF PBR (base colour, metalness, roughness, alpha) so a standard
viewer lights them correctly, and geometry is flat-shaded per face so edges read
crisply. Nodes are grouped `site`, `level_<n>/<part>` and `roof`, so a viewer
can lift the roof or upper floors away to look inside.

Plan coordinates are metres, +Y north. The model is Y-up (glTF): plan (x, y) at
height h maps to (x, h, -y).
"""

from __future__ import annotations

import hashlib
import io
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np

from aip.core.logging import get_logger, log_event
from aip.domain.geometry import BoundingBox, Vec2
from aip.domain.plan import FloorPlan, Level, Opening, Room, RoomType, Wall, WallKind

logger = get_logger("aip.experience.arch3d")

PLINTH = 0.45          # m: ground floor finished level above the site
SLAB = 0.15            # m: structural slab
DRIP = 0.08            # m: how far the floor band projects past the wall face
PARAPET = 1.0          # m
CHAJJA_DEPTH = 0.55    # m: sunshade projection
EAVE = 0.85            # m: roof overhang
ROOF_PITCH = math.radians(24)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Material:
    """A glTF metallic-roughness material."""

    name: str
    rgb: tuple[float, float, float]
    roughness: float = 0.8
    metallic: float = 0.0
    alpha: float = 1.0
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)


def _linear(c: float) -> float:
    """sRGB channel to linear light."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hex(value: str, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    try:
        v = value.strip().lstrip("#")
        return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except Exception:  # noqa: BLE001 - a malformed palette entry must not break the model
        return fallback


#: Exterior character per style: plaster, cladding, roof form and roof tone.
_EXTERIOR: dict[str, dict[str, Any]] = {
    "tropical_modern": {"plaster": (0.93, 0.91, 0.87), "clad": (0.55, 0.50, 0.44), "roof": "flat", "pergola": True},
    "contemporary": {"plaster": (0.95, 0.95, 0.93), "clad": (0.42, 0.42, 0.42), "roof": "flat"},
    "modern_minimal": {"plaster": (0.96, 0.96, 0.95), "clad": (0.30, 0.30, 0.31), "roof": "flat"},
    "scandinavian": {"plaster": (0.95, 0.94, 0.91), "clad": (0.62, 0.50, 0.36), "roof": "hip", "tile": (0.30, 0.31, 0.33)},
    "industrial": {"plaster": (0.62, 0.62, 0.60), "clad": (0.48, 0.30, 0.24), "roof": "flat"},
    "mid_century_modern": {"plaster": (0.92, 0.89, 0.82), "clad": (0.52, 0.36, 0.22), "roof": "flat"},
    "traditional_indian": {"plaster": (0.94, 0.86, 0.72), "clad": (0.60, 0.40, 0.28), "roof": "hip", "tile": (0.62, 0.28, 0.18)},
    "kerala_vernacular": {"plaster": (0.95, 0.92, 0.84), "clad": (0.50, 0.32, 0.20), "roof": "hip", "tile": (0.60, 0.26, 0.16)},
    "chettinad": {"plaster": (0.93, 0.84, 0.66), "clad": (0.58, 0.36, 0.22), "roof": "hip", "tile": (0.64, 0.30, 0.18)},
    "indo_saracenic": {"plaster": (0.93, 0.83, 0.70), "clad": (0.70, 0.52, 0.38), "roof": "flat"},
    "biophilic": {"plaster": (0.92, 0.92, 0.88), "clad": (0.45, 0.40, 0.32), "roof": "flat", "pergola": True},
    "japandi": {"plaster": (0.92, 0.90, 0.86), "clad": (0.36, 0.30, 0.24), "roof": "hip", "tile": (0.24, 0.24, 0.25)},
}


class Palette:
    """Every material the model uses, resolved once for the plan's style."""

    def __init__(self, style: str, scheme: Any = None) -> None:
        ext = _EXTERIOR.get(style, _EXTERIOR["contemporary"])
        interior = None
        try:
            from aip.domain.brief import DesignStyle
            from aip.engines.interior.catalog import palette_for

            interior = palette_for(DesignStyle(style))
        except Exception:  # noqa: BLE001 - unknown style falls back to neutral interiors
            interior = None
        self.roof_kind: str = ext["roof"]
        self.pergola: bool = bool(ext.get("pergola"))
        # Set by the exterior design: the boundary wall and balustrade kinds.
        self.boundary: str = ""
        self.railing: str = ""
        self.shade: str = ""
        self.canopy: str = ""
        self.gate: str = ""
        self.garden: str = ""
        self.solar: bool = False
        self.parapet: str = ""
        self.deck: str = ""
        self.lights: str = ""
        self.yard: str = ""
        self.garage: str = ""
        joinery = _hex(interior.joinery, (0.45, 0.32, 0.22)) if interior else (0.45, 0.32, 0.22)
        uph = _hex(interior.upholstery, (0.72, 0.68, 0.62)) if interior else (0.72, 0.68, 0.62)
        accent = _hex(interior.accent, (0.36, 0.42, 0.40)) if interior else (0.36, 0.42, 0.40)
        metal = _hex(interior.metal, (0.20, 0.20, 0.21)) if interior else (0.20, 0.20, 0.21)
        wall_in = _hex(interior.wall, (0.94, 0.93, 0.90)) if interior else (0.94, 0.93, 0.90)
        wall_acc = _hex(interior.wall_accent, (0.80, 0.74, 0.66)) if interior else (0.80, 0.74, 0.66)
        floor = _hex(interior.floor, (0.78, 0.72, 0.64)) if interior else (0.78, 0.72, 0.64)
        self.m: dict[str, Material] = {
            "plaster": Material("plaster", ext["plaster"], 0.92),
            "clad": Material("stone_cladding", ext["clad"], 0.85),
            "wall_in": Material("interior_paint", wall_in, 0.95),
            "wall_accent": Material("accent_wall", wall_acc, 0.9),
            "slab": Material("concrete_band", (0.80, 0.79, 0.77), 0.9),
            "plinth": Material("plinth_stone", (0.46, 0.44, 0.41), 0.9),
            "glass": Material("glass", (0.62, 0.74, 0.80), 0.05, 0.0, 0.32),
            "frame": Material("window_frame", (0.17, 0.16, 0.15), 0.4, 0.6),
            "sill": Material("stone_sill", (0.68, 0.66, 0.62), 0.6),
            "door": Material("door_timber", (0.40, 0.26, 0.15), 0.55),
            "main_door": Material("main_door_teak", (0.33, 0.20, 0.11), 0.45),
            "rail_glass": Material("railing_glass", (0.70, 0.80, 0.84), 0.05, 0.0, 0.28),
            "rail_metal": Material("railing_steel", (0.22, 0.22, 0.23), 0.35, 0.8),
            "roof_tile": Material("roof_tile", ext.get("tile", (0.58, 0.27, 0.17)), 0.75),
            "roof_flat": Material("roof_screed", (0.72, 0.71, 0.69), 0.95),
            "timber": Material("pergola_timber", (0.46, 0.31, 0.19), 0.7),
            # The gate has finishes of its own, so it can be painted apart from the pergola and railings.
            "gate": Material("gate_timber", (0.46, 0.31, 0.19), 0.7),
            "gate_steel": Material("gate_steel", (0.22, 0.22, 0.23), 0.35, 0.8),
            "shutter": Material("rolling_shutter", (0.60, 0.61, 0.62), 0.45, 0.6),
            "car": Material("car_paint", (0.62, 0.64, 0.66), 0.3, 0.6),
            "car_glass": Material("car_glass", (0.08, 0.09, 0.10), 0.1, 0.3),
            "tyre": Material("tyre", (0.06, 0.06, 0.06), 0.9),
            # A deep grass green: the sun on open ground lifts it a long way.
            "lawn": Material("lawn", (0.21, 0.36, 0.14), 1.0),
            "paving": Material("paving", (0.70, 0.67, 0.62), 0.9),
            "compound": Material("compound_wall", (0.86, 0.84, 0.80), 0.95),
            "trunk": Material("tree_trunk", (0.33, 0.24, 0.17), 0.95),
            "leaf": Material("foliage", (0.24, 0.42, 0.20), 0.9),
            "leaf2": Material("foliage_light", (0.36, 0.52, 0.26), 0.9),
            "water": Material("water_tank", (0.20, 0.20, 0.21), 0.6),
            "pool_water": Material("pool_water", (0.22, 0.62, 0.70), 0.06, 0.1, 0.9),
            "pool_tile": Material("pool_tile", (0.55, 0.78, 0.82), 0.3),
            "bamboo": Material("bamboo_pole", (0.71, 0.60, 0.38), 0.6),
            "yard_gravel": Material("yard_gravel", (0.72, 0.69, 0.62), 0.95),
            "boulder": Material("boulder_stone", (0.48, 0.46, 0.42), 0.9),
            "f_wood": Material("floor_timber", (0.58, 0.42, 0.28), 0.6),
            "f_stone": Material("floor_stone", floor, 0.35),
            "f_tile": Material("floor_tile_matt", (0.78, 0.79, 0.78), 0.7),
            "f_out": Material("floor_outdoor", (0.62, 0.58, 0.52), 0.9),
            "f_kota": Material("floor_kota", (0.52, 0.56, 0.52), 0.6),
            "joinery": Material("joinery", joinery, 0.55),
            "uph": Material("upholstery", uph, 0.95),
            "accent": Material("accent", accent, 0.85),
            "metal": Material("metal", metal, 0.35, 0.8),
            "linen": Material("linen", (0.93, 0.92, 0.89), 0.95),
            "ceramic": Material("ceramic", (0.96, 0.96, 0.95), 0.2),
            "counter": Material("counter_stone", (0.20, 0.20, 0.21), 0.3),
            "appliance": Material("appliance", (0.82, 0.83, 0.84), 0.3, 0.6),
            "screen": Material("screen", (0.05, 0.05, 0.06), 0.2),
            "brass": Material("brass", (0.78, 0.60, 0.28), 0.3, 0.9),
            "light": Material("light", (1.0, 0.95, 0.84), 0.5, 0.0, 1.0, (1.0, 0.86, 0.62)),
            # Exterior skins.
            "ex_brick": Material("brick", (0.56, 0.30, 0.22), 0.9),
            "ex_concrete": Material("board_concrete", (0.62, 0.61, 0.58), 0.95),
            "ex_timber": Material("timber_boards", (0.55, 0.37, 0.22), 0.7),
            "ex_metal": Material("dark_metal", (0.16, 0.16, 0.17), 0.45, 0.6),
            "ex_glassband": Material("glazing_band", (0.10, 0.12, 0.14), 0.08, 0.4),
            "ex_accent": Material("exterior_accent", (0.54, 0.42, 0.30), 0.5, 0.3),
            "ex_roof": Material("roof_metal", (0.16, 0.16, 0.17), 0.45, 0.6),
            # Matte enough not to mirror the sky white from above.
            "solar": Material("solar_panel", (0.09, 0.13, 0.22), 0.45, 0.05),
            "solar_frame": Material("solar_frame", (0.72, 0.73, 0.74), 0.35, 0.8),
            "ex_terracotta": Material("terracotta_tile", (0.69, 0.38, 0.26), 0.85),
            "ex_acp": Material("acp_panel", (0.56, 0.57, 0.58), 0.35, 0.5),
            "ex_slate": Material("slate_stack", (0.31, 0.32, 0.33), 0.8),
            # A glass curtain wall: dark, smooth and a little reflective, opaque so no room shows through raw.
            "ex_curtain": Material("curtain_glass", (0.19, 0.25, 0.30), 0.07, 0.35),
            "ex_corten": Material("corten_steel", (0.47, 0.23, 0.11), 0.8, 0.3),
            # The garden's colour and its fire.
            "flower_pink": Material("flower_pink", (0.86, 0.36, 0.52), 0.9),
            "flower_yellow": Material("flower_yellow", (0.95, 0.77, 0.22), 0.9),
            "flower_white": Material("flower_white", (0.95, 0.94, 0.90), 0.9),
            "soil": Material("garden_soil", (0.30, 0.21, 0.14), 1.0),
            # The terrace and walks round the house where the brief keeps less lawn.
            "terrace": Material("terrace_paving", (0.74, 0.71, 0.66), 0.9),
            "fire": Material("fire_glow", (1.0, 0.52, 0.16), 0.6, 0.0, 1.0, (1.0, 0.42, 0.08)),
            "ex_panel": Material("panel_stone_cladding", ext["clad"], 0.85),
            # Warm facade lighting: a lamp, so it glows in the night view.
            "facade_light": Material("facade_light", (0.95, 0.93, 0.88), 0.4, 0.0, 1.0, (1.0, 0.8, 0.52)),
        }
        self.scheme = scheme
        if scheme is not None:
            self._apply(scheme)

    def _apply(self, scheme: Any) -> None:
        """Recolour every surface from a coordinated scheme, and add a paint per kind of room."""
        e, i = scheme.exterior, scheme.interior
        recolour = {
            "plaster": e["plaster"], "clad": e["clad"], "roof_tile": e["roof"], "frame": e["frame"],
            "main_door": e["door"], "rail_metal": e["metal"], "compound": e["compound"], "slab": e["trim"],
            "sill": e["trim"], "wall_in": i["circulation"], "wall_accent": i["accent_wall"],
            "f_stone": i["floor_stone"], "f_wood": i["floor_wood"], "f_tile": i["floor_tile"],
            "joinery": i["joinery"], "door": i["joinery"], "uph": i["upholstery"], "accent": i["accent"],
            "metal": i["metal_in"],
        }
        for key, hex_ in recolour.items():
            m = self.m[key]
            self.m[key] = Material(m.name, _hex(hex_, m.rgb), m.roughness, m.metallic, m.alpha, m.emissive)
        for slot in ("living", "dining", "bedroom", "master", "kids", "kitchen", "study", "puja",
                     "circulation", "ceiling"):
            self.m[f"paint_{slot}"] = Material(f"paint_{slot}", _hex(i[slot], (0.93, 0.92, 0.89)), 0.93)
        self.m["tile_bath"] = Material("wall_tile_bath", _hex(i["bath_tile"], (0.85, 0.84, 0.82)), 0.25)
        self.m["tile_kitchen"] = Material("backsplash_kitchen", _hex(i["kitchen_tile"], (0.6, 0.6, 0.6)), 0.2)

    def side_finish(self, room: Room | None, accent: bool = False) -> list[tuple[float, str]]:
        """A wall face's finish as bands from the floor up: (top of band, material)."""
        if self.scheme is None or room is None:
            return [(99.0, "wall_in")]
        from aip.engines.experience.palettes import room_slot

        slot = room_slot(room.type.value)
        if slot == "bath_tile":
            # Wet walls are tiled to door height and painted above.
            return [(2.1, "tile_bath"), (99.0, "paint_ceiling")]
        paint = "wall_accent" if accent else f"paint_{slot}"
        if slot == "kitchen":
            # A splashback between counter and wall cabinets.
            return [(0.86, paint), (1.5, "tile_kitchen"), (99.0, paint)]
        return [(99.0, paint)]


# ---------------------------------------------------------------------------
# Geometry primitives (flat-shaded: every face owns its vertices)
# ---------------------------------------------------------------------------


class Builder:
    """Collects triangles per (node, material) and emits a glTF scene."""

    def __init__(self, palette: Palette) -> None:
        self.p = palette
        self.buckets: dict[tuple[str, str], list[tuple[np.ndarray, np.ndarray]]] = defaultdict(list)

    def add(self, node: str, mat: str, verts: np.ndarray, faces: np.ndarray) -> None:
        if len(faces):
            self.buckets[(node, mat)].append((verts, faces))

    # --- primitives in model space (x, up, z) ---------------------------------

    def box(self, node: str, mat: str, centre: tuple[float, float, float],
            size: tuple[float, float, float], yaw: float = 0.0) -> None:
        """A box, optionally turned about the vertical axis by `yaw` radians."""
        hx, hy, hz = (s / 2 for s in size)
        quads = [  # each face as four corners, counter-clockwise from outside
            [(-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)],
            [(hx, -hy, -hz), (-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz)],
            [(-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz)],
            [(hx, -hy, hz), (hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz)],
            [(-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz), (-hx, hy, -hz)],
            [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz)],
        ]
        v = np.array([c for q in quads for c in q], dtype=np.float64)
        if yaw:
            c, s = math.cos(yaw), math.sin(yaw)
            v = v @ np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]]).T
        v += np.array(centre)
        f = np.array([[i, i + 1, i + 2] for i in range(0, 24, 4)] + [[i, i + 2, i + 3] for i in range(0, 24, 4)])
        self.add(node, mat, v, f)

    def quad_strip(self, node: str, mat: str, a: tuple, b: tuple, c: tuple, d: tuple) -> None:
        """One planar quad (a, b, c, d counter-clockwise from its front), both sides."""
        v = np.array([a, b, c, d], dtype=np.float64)
        self.add(node, mat, v, np.array([[0, 1, 2], [0, 2, 3]]))
        self.add(node, mat, v.copy(), np.array([[0, 2, 1], [0, 3, 2]]))

    def tri(self, node: str, mat: str, a: tuple, b: tuple, c: tuple) -> None:
        v = np.array([a, b, c], dtype=np.float64)
        self.add(node, mat, v, np.array([[0, 1, 2]]))
        self.add(node, mat, v.copy(), np.array([[0, 2, 1]]))

    def slab(self, node: str, mat: str, polygon: list[Vec2], y0: float, y1: float) -> None:
        """Extrude a plan polygon (any simple shape) between two heights."""
        from shapely.geometry import Polygon
        from shapely.ops import triangulate

        poly = Polygon([(p.x, p.y) for p in polygon]).buffer(0)
        if poly.is_empty or poly.area < 1e-4:
            return
        tris = [t for t in triangulate(poly) if poly.contains(t.representative_point())]
        for t in tris:
            (x0, z0), (x1, z1), (x2, z2) = list(t.exterior.coords)[:3]
            top = np.array([[x0, y1, -z0], [x1, y1, -z1], [x2, y1, -z2]])
            bot = np.array([[x0, y0, -z0], [x1, y0, -z1], [x2, y0, -z2]])
            self.add(node, mat, top, np.array([[0, 1, 2]]))
            self.add(node, mat, bot, np.array([[0, 2, 1]]))
        ring = list(poly.exterior.coords)
        for (xa, za), (xb, zb) in zip(ring, ring[1:]):
            self.quad_strip(node, mat, (xa, y0, -za), (xb, y0, -zb), (xb, y1, -zb), (xa, y1, -za))

    def cylinder(self, node: str, mat: str, base: tuple[float, float, float], radius: float,
                 height: float, sections: int = 10) -> None:
        import trimesh

        m = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
        m.apply_translation((0, 0, height / 2))
        m.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, (1, 0, 0)))
        m.apply_translation(base)
        m.unmerge_vertices()
        self.add(node, mat, np.asarray(m.vertices), np.asarray(m.faces))

    def blob(self, node: str, mat: str, centre: tuple[float, float, float], radius: float,
             squash: float = 1.0) -> None:
        import trimesh

        m = trimesh.creation.icosphere(subdivisions=1, radius=radius)
        m.apply_scale((1.0, squash, 1.0))
        m.apply_translation(centre)
        m.unmerge_vertices()
        self.add(node, mat, np.asarray(m.vertices), np.asarray(m.faces))

    # --- export ----------------------------------------------------------------

    def scene(self):
        import trimesh
        from trimesh.visual.material import PBRMaterial

        scene = trimesh.Scene()
        made: dict[str, PBRMaterial] = {}
        parents: set[str] = set()
        for (node, key), parts in sorted(self.buckets.items()):
            mat = self.p.m[key]
            if key not in made:
                # Colours are authored as sRGB; glTF factors are linear. Without
                # the conversion every finish renders washed out and pale.
                made[key] = PBRMaterial(
                    name=mat.name,
                    baseColorFactor=[*(_linear(c) for c in mat.rgb), mat.alpha],
                    metallicFactor=mat.metallic,
                    roughnessFactor=mat.roughness,
                    emissiveFactor=[_linear(c) for c in mat.emissive],
                    alphaMode="BLEND" if mat.alpha < 1 else "OPAQUE",
                    doubleSided=mat.alpha < 1,
                )
            verts, faces, offset = [], [], 0
            for v, f in parts:
                verts.append(v)
                faces.append(f + offset)
                offset += len(v)
            mesh = trimesh.Trimesh(np.vstack(verts), np.vstack(faces), process=False)
            mesh.visual = trimesh.visual.TextureVisuals(material=made[key])
            group = node.split("/")[0]
            if group not in parents:
                scene.graph.update(frame_to=group, frame_from=scene.graph.base_frame)
                parents.add(group)
            # glTF loaders strip "/" from names, so the path uses "__".
            # The material key last, so a click in the viewer knows which part it hit.
            label = f"{node}/{mat.name}/{key}".replace("/", "__")
            scene.add_geometry(mesh, node_name=label, geom_name=label,
                               parent_node_name=group)
        return scene


# ---------------------------------------------------------------------------
# Plan helpers
# ---------------------------------------------------------------------------


def _footprint(level: Level):
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    polys = [Polygon([(p.x, p.y) for p in r.polygon]).buffer(0) for r in level.rooms if len(r.polygon) >= 3]
    return unary_union(polys).buffer(0.12, join_style=2).buffer(-0.0, join_style=2) if polys else None


def _poly_pts(geom) -> list[Vec2]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "MultiPolygon":
        geom = max(geom.geoms, key=lambda g: g.area)
    return [Vec2(x, y) for x, y in list(geom.exterior.coords)[:-1]]


def _yaw(direction: Vec2) -> float:
    """Yaw that turns a box's +X axis onto a plan direction (plan Y is model -Z)."""
    return math.atan2(direction.y, direction.x)


def _room_floor_material(room: Room) -> str:
    t = room.type
    if t in {RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER, RoomType.UTILITY}:
        return "f_tile"
    if t in {RoomType.MASTER_BEDROOM, RoomType.BEDROOM, RoomType.GUEST_BEDROOM, RoomType.CHILDREN_BEDROOM,
             RoomType.STUDY, RoomType.HOME_OFFICE}:
        return "f_wood"
    if t in {RoomType.BALCONY, RoomType.TERRACE, RoomType.VERANDAH, RoomType.COURTYARD, RoomType.GARAGE}:
        return "f_out"
    if t in {RoomType.KITCHEN, RoomType.STORE}:
        return "f_kota"
    return "f_stone"


_OPEN_TO_SKY = {RoomType.COURTYARD}
_RAILED = {RoomType.BALCONY, RoomType.TERRACE}


# ---------------------------------------------------------------------------
# The building
# ---------------------------------------------------------------------------


def _accent_walls(level: Level) -> set[str]:
    """One feature wall per living room and master bedroom: its longest unbroken wall."""
    picks: set[str] = set()
    for room in level.rooms:
        if room.type not in (RoomType.LIVING, RoomType.MASTER_BEDROOM):
            continue
        solid = [w for w in level.walls if room.id in w.rooms and not w.openings
                 and w.kind not in (WallKind.EXTERIOR, WallKind.PARAPET)]
        solid = solid or [w for w in level.walls if room.id in w.rooms and not w.openings]
        if solid:
            picks.add(max(solid, key=lambda w: w.length).id)
    return picks


def _merged_walls(level: Level) -> list[Wall]:
    """The level's walls with collinear overlaps merged into one.

    A plan can carry two walls along the same line (a partition drawn over
    an interior wall). Built as they are, their faces coincide and flicker,
    and with a different paint on each the flicker is plain to see. Each run
    of overlapping collinear walls becomes one wall: the thickest, the most
    exterior kind, every room it bounds and every opening either carried.
    """
    rank = {WallKind.EXTERIOR: 0, WallKind.PARAPET: 1, WallKind.SHEAR: 2, WallKind.RETAINING: 3,
            WallKind.INTERIOR: 4, WallKind.PARTITION: 5}
    walls = [w for w in level.walls if w.length > 0.02]
    used = [False] * len(walls)
    out: list[Wall] = []
    for i, w in enumerate(walls):
        if used[i]:
            continue
        used[i] = True
        u = w.direction_vector.normalised()
        n = Vec2(-u.y, u.x)
        o = w.start
        group = [w]
        lo, hi = 0.0, w.length
        grew = True
        while grew:
            grew = False
            for j, v in enumerate(walls):
                if used[j]:
                    continue
                dv = v.direction_vector.normalised()
                if abs(dv.x * u.y - dv.y * u.x) > 0.03:
                    continue
                if abs((v.start - o).dot(n)) > 0.06 or abs((v.end - o).dot(n)) > 0.06:
                    continue
                a, b = sorted(((v.start - o).dot(u), (v.end - o).dot(u)))
                if b < lo + 0.05 or a > hi - 0.05:
                    continue
                used[j] = True
                group.append(v)
                lo, hi = min(lo, a), max(hi, b)
                grew = True
        if len(group) == 1:
            out.append(w)
            continue
        main = min(group, key=lambda g: (rank.get(g.kind, 9), -g.thickness))
        start, end = o + u * lo, o + u * hi
        length = hi - lo
        openings, centres = [], []
        for g in group:
            gu = g.direction_vector.normalised()
            for op in g.openings:
                c = ((g.start + gu * (op.position * g.length)) - start).dot(u)
                if any(abs(c - k) < 0.3 for k in centres):
                    continue
                centres.append(c)
                openings.append(op.model_copy(update={"position": min(1.0, max(0.0, c / length))}))
        rooms = list(dict.fromkeys(r for g in group for r in g.rooms))
        out.append(main.model_copy(update={
            "start": start, "end": end, "openings": openings, "rooms": rooms,
            "thickness": max(g.thickness for g in group),
        }))
    return out


def _garage_faces(level: Level, walls: list, road: Vec2 | None) -> dict[int, tuple[float, float, Room]]:
    """The street face of each car porch: (start, end) along that wall, by wall.
    The porch's outside wall that faces the road most, or its longest."""
    out: dict[int, tuple[float, float, Room]] = {}
    centre = level.envelope().centre
    for g in (r for r in level.rooms if r.type is RoomType.GARAGE and len(r.polygon) >= 3):
        best, score = None, -9.0
        for w in walls:
            if w.kind is not WallKind.EXTERIOR or g.id not in w.rooms:
                continue
            d = w.end - w.start
            if d.length < 1.5:
                continue
            u = d.normalised()
            ts = [(p - w.start).dot(u) for p in g.polygon]
            t0, t1 = max(0.0, min(ts)), min(d.length, max(ts))
            if t1 - t0 < 1.5:
                continue
            sc = (w.outward_normal(centre).dot(road) if road is not None else 0.0) + (t1 - t0) * 0.01
            if sc > score:
                best, score = (id(w), t0, t1), sc
        if best:
            out[best[0]] = (best[1], best[2], g)
    return out


def _car(b: Builder, node: str, g: Room, base: float, along: Vec2) -> None:
    """A car parked in the porch, nose to the street: its width runs along the
    street wall, its length into the porch."""
    c = g.centre
    yaw = _yaw(along)
    for dz, w, h, l, mat in ((0.42, 1.78, 0.62, 4.3, "car"), (0.98, 1.6, 0.5, 2.3, "car_glass"), (1.24, 1.5, 0.04, 2.1, "car")):
        b.box(node, mat, (c.x, base + dz, -c.y), (w, h, l), yaw)
    n = Vec2(-along.y, along.x)
    for s1 in (-1, 1):
        for s2 in (-1, 1):
            p = c + along * (s2 * 0.82) + n * (s1 * 1.35)
            b.box(node, "tyre", (p.x, base + 0.32, -p.y), (0.24, 0.62, 0.62), yaw)


def _walls(b: Builder, plan: FloorPlan, level: Level, base: float, node: str, road: Vec2 | None) -> None:
    by_id = {r.id: r for r in level.rooms}
    accents = _accent_walls(level)
    centre = level.envelope().centre
    height = level.floor_to_floor - SLAB
    walls = _merged_walls(level)
    porches = _garage_faces(level, walls, road) if level.index == 0 else {}
    for wall in walls:
        d = wall.end - wall.start
        length = d.length
        if length < 0.02:
            continue
        unit = d.normalised()
        yaw = _yaw(unit)
        exterior = wall.kind in (WallKind.EXTERIOR, WallKind.PARAPET)
        bounded = [by_id[r] for r in wall.rooms if r in by_id]
        railed = exterior and bounded and all(r.type in _RAILED for r in bounded)
        out = wall.outward_normal(centre) if exterior else Vec2(0, 0)
        cladded = (exterior and level.index == 0 and road is not None and out.dot(road) > 0.7)
        mat = "clad" if cladded else ("plaster" if exterior else "wall_in")
        if exterior and getattr(b.p, "skins", None) and level.index in b.p.skins:
            mat = b.p.skins[level.index]
        t = wall.thickness
        # Which room lies on which face: + is the side the left normal points to.
        n = Vec2(-unit.y, unit.x)
        mid_w = wall.start + unit * (length / 2)
        sides: dict[int, Room | None] = {1: None, -1: None}
        for r in bounded:
            sgn = 1 if (r.centre - mid_w).dot(n) >= 0 else -1
            sides[sgn] = sides[sgn] or r
        if exterior:
            sgn_out = 1 if out.dot(n) >= 0 else -1
            sides[sgn_out] = None
        finishes = {
            sgn: ([(99.0, mat)] if exterior and sgn == (1 if out.dot(n) >= 0 else -1)
                  else b.p.side_finish(sides[sgn], accent=wall.id in accents))
            for sgn in (1, -1)
        }
        two_sided = b.p.scheme is not None

        if railed:
            _railing(b, node, wall.start, wall.end, base, out)
            continue

        def piece(u0: float, u1: float, y0: float, y1: float, m: str = mat) -> None:
            if u1 - u0 < 0.01 or y1 - y0 < 0.01:
                return
            mid = wall.start + unit * ((u0 + u1) / 2)
            if not two_sided:
                b.box(node, m, (mid.x, base + (y0 + y1) / 2, -mid.y), (u1 - u0, y1 - y0, t), yaw)
                return
            # Two half-thickness leaves, each finished for the room it faces,
            # banded where a room needs it (tiles, a splashback).
            for sgn in (1, -1):
                c = mid + n * (sgn * t / 4)
                lo = y0
                for top, finish in finishes[sgn]:
                    hi = min(y1, top)
                    if hi - lo > 0.005:
                        b.box(node, finish, (c.x, base + (lo + hi) / 2, -c.y), (u1 - u0, hi - lo, t / 2), yaw)
                    lo = max(lo, hi)
                    if lo >= y1:
                        break

        cursor = 0.0
        porch = porches.get(id(wall))
        openings = sorted(wall.openings, key=lambda o: o.position)
        if porch:
            # The car porch's street face: open under a beam, or a rolling shutter.
            g0, g1, groom = porch
            openings = [o for o in openings if not (g0 - 0.1 <= o.position * length <= g1 + 0.1)]
            shut = getattr(b.p, "garage", "") == "closed"
            span = (g0 + 0.15, g1 - 0.15)
            opening_head = min(2.6, height - 0.3)
            done = False
            for o in openings + [None]:
                c = o.position * length if o else length + 1
                if not done and c > span[0]:
                    piece(cursor, span[0], 0.0, height)
                    piece(span[0], span[1], opening_head, height)
                    mid = wall.start + unit * ((span[0] + span[1]) / 2)
                    if shut:
                        w_ = span[1] - span[0]
                        b.box(node, "shutter", (mid.x, base + opening_head / 2, -mid.y), (w_, opening_head, 0.05), yaw)
                        for k in range(1, int(opening_head / 0.09)):
                            q = mid + out * 0.03
                            b.box(node, "shutter", (q.x, base + k * 0.09, -q.y), (w_, 0.012, 0.02), yaw)
                        hood = mid + out * 0.12
                        b.box(node, "shutter", (hood.x, base + opening_head + 0.12, -hood.y), (w_ + 0.1, 0.24, 0.24), yaw)
                    else:
                        _car(b, node, groom, base, unit)
                    cursor, done = span[1], True
                if o is None:
                    break
                left, right = max(0.0, c - o.width / 2), min(length, c + o.width / 2)
                if right <= left:
                    continue
                piece(cursor, left, 0.0, height)
                sill = 0.0 if o.kind.is_door else min(o.sill_height, height)
                head = min(o.head_height, height - 0.05)
                piece(left, right, 0.0, sill)
                piece(left, right, head, height)
                m_ = wall.start + unit * c
                if o.kind.is_door:
                    _door(b, node, o, m_, yaw, base, head, t, main=False)
                else:
                    _window(b, node, o, m_, yaw, base, sill, head, t, out)
                cursor = right
            piece(cursor, length, 0.0, height)
            continue
        for o in openings:
            c = o.position * length
            left, right = max(0.0, c - o.width / 2), min(length, c + o.width / 2)
            if right <= left:
                continue
            piece(cursor, left, 0.0, height)
            sill = 0.0 if o.kind.is_door else min(o.sill_height, height)
            head = min(o.head_height, height - 0.05)
            piece(left, right, 0.0, sill)
            piece(left, right, head, height)
            mid = wall.start + unit * c
            if o.kind.is_door:
                _door(b, node, o, mid, yaw, base, head, t, main=exterior and level.index == 0 and o.width >= 0.95)
                if exterior and level.index == 0 and o.width >= 0.95:
                    _entrance(b, plan, mid, out, o.width, base, head, yaw)
            else:
                _window(b, node, o, mid, yaw, base, sill, head, t, out if exterior else None)
            cursor = right
        piece(cursor, length, 0.0, height)


def _window(b: Builder, node: str, o: Opening, mid: Vec2, yaw: float, base: float,
            sill: float, head: float, t: float, out: Vec2 | None) -> None:
    w, h = o.width, head - sill
    if h <= 0.1:
        return
    fr = 0.055
    y0 = base + sill
    cx, cz = mid.x, -mid.y
    # Frame: two jambs, head and sill members, and a mullion on wide openings.
    off = lambda u: (cx + math.cos(yaw) * u, cz - math.sin(yaw) * u)  # noqa: E731
    for u in (-w / 2 + fr / 2, w / 2 - fr / 2):
        x, z = off(u)
        b.box(node, "frame", (x, y0 + h / 2, z), (fr, h, 0.09), yaw)
    for y in (y0 + fr / 2, y0 + h - fr / 2):
        b.box(node, "frame", (cx, y, cz), (w, fr, 0.09), yaw)
    if w > 1.3:
        n = 2 if w <= 2.4 else 3
        for k in range(1, n):
            x, z = off(-w / 2 + w * k / n)
            b.box(node, "frame", (x, y0 + h / 2, z), (fr * 0.8, h, 0.08), yaw)
    b.box(node, "glass", (cx, y0 + h / 2, cz), (w - fr, h - fr, 0.012), yaw)
    if out is not None:
        # Stone sill and a concrete sunshade, both projecting outward.
        sx, sz = cx + out.x * (t / 2 + 0.03), cz - out.y * (t / 2 + 0.03)
        b.box(node, "sill", (sx, y0 - 0.025, sz), (w + 0.12, 0.05, 0.12), yaw)
        shade = getattr(b.p, "shade", "") or "slim"
        if shade == "box":
            # A projecting box frame round the opening, in the accent.
            d = 0.38
            px, pz = cx + out.x * (t / 2 + d / 2), cz - out.y * (t / 2 + d / 2)
            b.box(node, "ex_accent", (px, y0 + h + 0.06, pz), (w + 0.24, 0.12, d), yaw)
            b.box(node, "ex_accent", (px, y0 - 0.06, pz), (w + 0.24, 0.12, d), yaw)
            for u in (-w / 2 - 0.06, w / 2 + 0.06):
                x, z = off(u)
                b.box(node, "ex_accent", (x + out.x * (t / 2 + d / 2), y0 + h / 2, z - out.y * (t / 2 + d / 2)), (0.12, h + 0.24, d), yaw)
        elif shade != "none":
            depth = 0.9 if shade == "deep" else CHAJJA_DEPTH
            hx, hz = cx + out.x * (t / 2 + depth / 2), cz - out.y * (t / 2 + depth / 2)
            b.box(node, "slab", (hx, base + head + 0.12, hz), (w + (0.6 if shade == "deep" else 0.3), 0.1 if shade == "deep" else 0.075, depth), yaw)
        if "fins" in (o.notes or "") and shade != "box":
            # A west window's vertical fins: the low afternoon sun a chajja lets under.
            d = 0.45
            for u in (-w / 2 - 0.1, w / 2 + 0.1):
                x, z = off(u)
                b.box(node, "slab", (x + out.x * (t / 2 + d / 2), y0 + h / 2 + 0.05, z - out.y * (t / 2 + d / 2)),
                      (0.08, h + 0.3, d), yaw)


def _door(b: Builder, node: str, o: Opening, mid: Vec2, yaw: float, base: float, head: float,
          t: float, *, main: bool) -> None:
    w = o.width
    fr = 0.06
    cx, cz = mid.x, -mid.y
    off = lambda u: (cx + math.cos(yaw) * u, cz - math.sin(yaw) * u)  # noqa: E731
    for u in (-w / 2 + fr / 2, w / 2 - fr / 2):
        x, z = off(u)
        b.box(node, "frame", (x, base + head / 2, z), (fr, head, t + 0.02), yaw)
    b.box(node, "frame", (cx, base + head - fr / 2, cz), (w, fr, t + 0.02), yaw)
    leaf = "main_door" if main else "door"
    if main and w > 1.2:
        for s in (-1, 1):
            x, z = off(s * (w - 2 * fr) / 4)
            b.box(node, leaf, (x, base + (head - fr) / 2, z), ((w - 2 * fr) / 2 - 0.01, head - fr, 0.045), yaw)
            hx, hz = off(s * 0.06)
            b.box(node, "brass", (hx, base + 1.05, hz), (0.03, 0.5, 0.07), yaw)
    else:
        b.box(node, leaf, (cx, base + (head - fr) / 2, cz), (w - 2 * fr, head - fr, 0.04), yaw)
        hx, hz = off((w - 2 * fr) / 2 - 0.08)
        b.box(node, "brass" if main else "metal", (hx, base + 1.0, hz), (0.12, 0.025, 0.07), yaw)


def _entrance(b: Builder, plan: FloorPlan, mid: Vec2, out: Vec2, width: float, base: float,
              head: float, yaw: float) -> None:
    """Steps down the plinth and a canopy over the main door."""
    steps = 3
    rise = PLINTH / steps
    for k in range(steps):
        depth = 0.32 * (k + 1)
        c = mid + out * (0.15 + depth / 2)
        b.box("site", "plinth", (c.x, rise * (steps - k) / 2, -c.y), (width + 1.2, rise * (steps - k), depth), yaw)
    kind = getattr(b.p, "canopy", "") or "slab"
    if kind == "none":
        return
    cdepth = 1.4
    c = mid + out * (cdepth / 2)
    y = base + head + 0.25
    if kind == "glass":
        # A glass canopy on two steel brackets.
        b.box("level_0/facade", "rail_glass", (c.x, y, -c.y), (width + 1.4, 0.03, cdepth), yaw)
        for s in (-1, 1):
            q = c + Vec2(math.cos(yaw), math.sin(yaw)) * (s * (width / 2 + 0.4))
            b.box("level_0/facade", "rail_metal", (q.x, y - 0.06, -q.y), (0.05, 0.1, cdepth), yaw)
        return
    if kind == "pergola":
        # Timber rafters on two posts: shade with the sky through it.
        along = Vec2(math.cos(yaw), math.sin(yaw))
        for k in range(int((width + 1.6) / 0.3) + 1):
            q = c + along * (-(width + 1.6) / 2 + k * 0.3)
            b.box("level_0/facade", "timber", (q.x, y, -q.y), (0.06, 0.16, cdepth + 0.3), yaw)
        for s in (-1, 1):
            q = mid + out * (cdepth - 0.1) + along * (s * (width / 2 + 0.6))
            b.box("level_0/facade", "timber", (q.x, PLINTH / 2 + y / 2 - 0.05, -q.y), (0.14, y - PLINTH / 2, 0.14), yaw)
        return
    b.box("level_0/facade", "slab", (c.x, y, -c.y), (width + 1.6, 0.12, cdepth), yaw)


def _railing(b: Builder, node: str, a: Vec2, c: Vec2, base: float, out: Vec2) -> None:
    d = c - a
    length = d.length
    yaw = _yaw(d.normalised())
    mid = (a + c) * 0.5
    kind = getattr(b.p, "railing", "") or "glass"
    if kind == "solid":
        # A solid parapet, plastered, with a coping.
        b.box(node, "plaster", (mid.x, base + 0.5, -mid.y), (length, 1.0, 0.14), yaw)
        b.box(node, "slab", (mid.x, base + 1.03, -mid.y), (length + 0.06, 0.06, 0.22), yaw)
        return
    if kind == "metal":
        # Square balusters at a child-safe spacing under a flat top rail.
        k = max(2, int(length / 0.12))
        for i in range(k + 1):
            p = a + d * (i / k)
            b.box(node, "rail_metal", (p.x, base + 0.52, -p.y), (0.022, 0.92, 0.022), yaw)
    else:
        b.box(node, "rail_glass", (mid.x, base + 0.5, -mid.y), (length, 0.95, 0.015), yaw)
    b.box(node, "rail_metal", (mid.x, base + 1.0, -mid.y), (length, 0.05, 0.06), yaw)
    b.box(node, "slab", (mid.x, base + 0.05, -mid.y), (length, 0.1, 0.18), yaw)
    n = max(2, int(length / 1.2) + 1)
    for k in range(n):
        p = a + d * (k / (n - 1))
        b.box(node, "rail_metal", (p.x, base + 0.5, -p.y), (0.04, 1.0, 0.04), yaw)


def _stair(b: Builder, room: Room, base: float, rise: float, node: str) -> None:
    """A dog-leg: two flights along the long side, a landing at the far end."""
    box = room.bbox
    along_x = box.width >= box.height
    long_len = box.width if along_x else box.height
    short = box.height if along_x else box.width
    risers = max(10, round(rise / 0.17))
    per_flight = risers // 2
    riser = rise / risers
    landing = min(1.2, short / 2)
    going = max(0.22, (long_len - landing - 0.1) / max(per_flight, 1))
    half = short / 2

    def put(u: float, v: float, du: float, dv: float, y0: float, y1: float) -> None:
        # u along the long side from its start, v across.
        if along_x:
            x, z = box.min_x + u + du / 2, box.min_y + v + dv / 2
            b.box(node, "slab", (x, base + (y0 + y1) / 2, -z), (du, y1 - y0, dv))
        else:
            x, z = box.min_x + v + dv / 2, box.min_y + u + du / 2
            b.box(node, "slab", (x, base + (y0 + y1) / 2, -z), (dv, y1 - y0, du))

    for k in range(per_flight):
        top = (k + 1) * riser
        put(k * going, 0.0, going, half - 0.05, max(0.0, top - 0.18), top)
    land_y = per_flight * riser
    put(long_len - landing, 0.0, landing, short, land_y - 0.18, land_y)
    for k in range(risers - per_flight):
        top = land_y + (k + 1) * riser
        u = long_len - landing - (k + 1) * going
        put(u, half + 0.05, going, half - 0.05, top - 0.18, top)
    # Handrails along the inner edge of both flights.
    for v, y0, y1 in ((half - 0.07, 0.9, 0.9 + land_y), (half + 0.07, 0.9 + land_y, 0.9 + rise)):
        u0, u1 = 0.0, long_len - landing
        length = math.hypot(u1 - u0, y1 - y0)
        ang = math.atan2(y1 - y0, u1 - u0)
        if along_x:
            cx, cz = box.min_x + (u0 + u1) / 2, box.min_y + v
            yaw = 0.0
        else:
            cx, cz = box.min_x + v, box.min_y + (u0 + u1) / 2
            yaw = math.pi / 2
        import trimesh

        m = trimesh.creation.box(extents=(length, 0.05, 0.05))
        m.apply_transform(trimesh.transformations.rotation_matrix(ang if along_x else -ang, (0, 0, 1)))
        m.apply_transform(trimesh.transformations.rotation_matrix(yaw, (0, 1, 0)))
        m.apply_translation((cx, base + (y0 + y1) / 2, -cz))
        m.unmerge_vertices()
        b.add(node, "rail_metal", np.asarray(m.vertices), np.asarray(m.faces))


def _hip_roof(b: Builder, env: BoundingBox, y: float) -> None:
    x0, x1 = env.min_x - EAVE, env.max_x + EAVE
    z0, z1 = env.min_y - EAVE, env.max_y + EAVE
    w, d = x1 - x0, z1 - z0
    rise = min(w, d) / 2 * math.tan(ROOF_PITCH)
    top = y + rise
    if w >= d:
        r0, r1 = (x0 + d / 2, (z0 + z1) / 2), (x1 - d / 2, (z0 + z1) / 2)
        P = lambda x, z, h: (x, h, -z)  # noqa: E731
        A, B, C, D = P(x0, z0, y), P(x1, z0, y), P(x1, z1, y), P(x0, z1, y)
        R0, R1 = P(r0[0], r0[1], top), P(r1[0], r1[1], top)
        b.quad_strip("roof", "roof_tile", A, B, R1, R0)
        b.quad_strip("roof", "roof_tile", C, D, R0, R1)
        b.tri("roof", "roof_tile", B, C, R1)
        b.tri("roof", "roof_tile", D, A, R0)
    else:
        r0, r1 = ((x0 + x1) / 2, z0 + w / 2), ((x0 + x1) / 2, z1 - w / 2)
        P = lambda x, z, h: (x, h, -z)  # noqa: E731
        A, B, C, D = P(x0, z0, y), P(x1, z0, y), P(x1, z1, y), P(x0, z1, y)
        R0, R1 = P(r0[0], r0[1], top), P(r1[0], r1[1], top)
        b.quad_strip("roof", "roof_tile", B, C, R1, R0)
        b.quad_strip("roof", "roof_tile", D, A, R0, R1)
        b.tri("roof", "roof_tile", A, B, R0)
        b.tri("roof", "roof_tile", C, D, R1)
    # A fascia band along the eaves.
    for (xa, za), (xb, zb) in (((x0, z0), (x1, z0)), ((x1, z0), (x1, z1)), ((x1, z1), (x0, z1)), ((x0, z1), (x0, z0))):
        mid = ((xa + xb) / 2, (za + zb) / 2)
        length = math.hypot(xb - xa, zb - za)
        yaw = math.atan2(zb - za, xb - xa)
        b.box("roof", "timber", (mid[0], y - 0.06, -mid[1]), (length, 0.14, 0.05), yaw)


def _flat_roof_extras(b: Builder, top: Level, y: float) -> None:
    """The stair head-room and water tank, on a roof without a parapet."""
    stair = next((r for r in top.rooms if r.type is RoomType.STAIRCASE), None)
    if stair is not None:
        bb = stair.bbox
        b.box("roof", "plaster", (bb.centre.x, y + 0.18 + 1.3, -bb.centre.y), (bb.width, 2.6, bb.height))
        b.box("roof", "slab", (bb.centre.x, y + 0.18 + 2.66, -bb.centre.y), (bb.width + 0.3, 0.12, bb.height + 0.3))


def _flat_roof(b: Builder, plan: FloorPlan, top: Level, y: float, footprint, palette: Palette) -> None:
    pts = _poly_pts(footprint)
    if not pts:
        return
    b.slab("roof", "roof_flat", pts, y - SLAB, y)
    ring = pts + pts[:1]
    for a, c in zip(ring, ring[1:]):
        d = c - a
        if d.length < 0.05:
            continue
        mid = (a + c) * 0.5
        yaw = _yaw(d.normalised())
        _parapet(b, palette.parapet, a, c, mid, d, yaw, y)
    # Stair head-room and a water tank over it.
    stair = next((r for r in top.rooms if r.type is RoomType.STAIRCASE), None)
    if stair is not None:
        bb = stair.bbox
        b.box("roof", "plaster", (bb.centre.x, y + 1.3, -bb.centre.y), (bb.width, 2.6, bb.height))
        b.box("roof", "slab", (bb.centre.x, y + 2.66, -bb.centre.y), (bb.width + 0.3, 0.12, bb.height + 0.3))
        b.cylinder("roof", "water", (bb.centre.x, y + 2.72, -bb.centre.y), 0.65, 1.1, 16)
    if palette.deck == "garden":
        _roof_garden(b, top, footprint, y)
    if palette.pergola:
        env = top.envelope()
        # Timber slats over the half of the terrace away from the stair head-room.
        x0, x1 = env.min_x + 0.4, env.min_x + env.width * 0.45
        for k in range(int((x1 - x0) / 0.35) + 1):
            x = x0 + k * 0.35
            b.box("roof", "timber", (x, y + 2.6, -env.centre.y), (0.08, 0.16, env.height - 0.8))
        for z in (env.min_y + 0.4, env.max_y - 0.4):
            for x in (x0, x1):
                b.box("roof", "timber", (x, y + 1.3, -z), (0.15, 2.6, 0.15))


def _parapet(b: Builder, kind: str, a: Vec2, c: Vec2, mid: Vec2, d: Vec2, yaw: float, y: float) -> None:
    """One run of the parapet, the crown of a flat-roofed house: plain, a glass
    strip over a low wall, grooved bands, a CNC-cut screen, or stepped like a haveli's."""
    L = d.length
    if kind == "glass":
        b.box("roof", "plaster", (mid.x, y + 0.25, -mid.y), (L + 0.12, 0.5, 0.14), yaw)
        b.box("roof", "rail_glass", (mid.x, y + 0.82, -mid.y), (L, 0.62, 0.02), yaw)
        b.box("roof", "rail_metal", (mid.x, y + 1.15, -mid.y), (L + 0.1, 0.04, 0.06), yaw)
        return
    if kind == "screen":
        b.box("roof", "plaster", (mid.x, y + 0.12, -mid.y), (L + 0.12, 0.24, 0.12), yaw)
        u = d.normalised()
        k = max(2, int(L / 0.16))
        for i in range(k):
            p = a + u * ((i + 0.5) * L / k)
            b.box("roof", "slab", (p.x, y + 0.62, -p.y), (0.06, 0.76, 0.1), yaw)
        b.box("roof", "slab", (mid.x, y + PARAPET + 0.03, -mid.y), (L + 0.2, 0.06, 0.2), yaw)
        return
    b.box("roof", "plaster", (mid.x, y + PARAPET / 2, -mid.y), (L + 0.12, PARAPET, 0.12), yaw)
    b.box("roof", "slab", (mid.x, y + PARAPET + 0.03, -mid.y), (L + 0.2, 0.06, 0.2), yaw)
    if kind == "grooved":
        for gy in (y + 0.35, y + 0.65):
            b.box("roof", "frame", (mid.x, gy, -mid.y), (L + 0.13, 0.03, 0.125), yaw)
    elif kind == "stepped":
        u = d.normalised()
        k = max(1, int(L / 0.9))
        for i in range(k):
            p = a + u * ((i + 0.5) * L / k)
            b.box("roof", "plaster", (p.x, y + PARAPET + 0.25, -p.y), (0.45, 0.44, 0.16), yaw)
            b.box("roof", "slab", (p.x, y + PARAPET + 0.49, -p.y), (0.52, 0.05, 0.22), yaw)


def _roof_garden(b: Builder, top: Level, footprint, y: float) -> None:
    """A planted terrace: a lawn bed over most of the roof, planters round it."""
    from shapely.geometry import box as sbox

    bed = footprint.buffer(-1.0)
    stair = next((r for r in top.rooms if r.type is RoomType.STAIRCASE), None)
    if stair is not None:
        bb = stair.bbox
        bed = bed.difference(sbox(bb.min_x - 0.8, bb.min_y - 0.8, bb.max_x + 0.8, bb.max_y + 0.8))
    for g in getattr(bed, "geoms", [bed]):
        if g.is_empty or g.geom_type != "Polygon" or g.area < 2.0:
            continue
        b.slab("roof", "lawn", [Vec2(px, py) for px, py in list(g.exterior.coords)[:-1]], y, y + 0.12)
        ring_ = g.exterior
        k = max(2, int(ring_.length / 1.6))
        for i in range(k):
            q = ring_.interpolate(i / k, normalized=True)
            b.box("roof", "ex_concrete", (q.x, y + 0.25, -q.y), (0.5, 0.5, 0.5))
            b.blob("roof", "leaf" if i % 2 else "leaf2", (q.x, y + 0.7, -q.y), 0.38, 0.85)


def _yard(b: Builder, kind: str, c: Vec2, r: float) -> None:
    """One garden feature centred at c within radius r."""
    def ring(radius: float, n: int = 16) -> list[Vec2]:
        return [Vec2(c.x + radius * math.cos(2 * math.pi * i / n), c.y + radius * math.sin(2 * math.pi * i / n)) for i in range(n)]

    if kind == "tulsi":
        # The Vrindavan: a stepped plinth with the tulsi growing from its top.
        b.box("site", "sill", (c.x, 0.15, -c.y), (1.0, 0.3, 1.0))
        b.box("site", "plaster", (c.x, 0.55, -c.y), (0.7, 0.5, 0.7))
        b.box("site", "ex_accent", (c.x, 0.82, -c.y), (0.8, 0.06, 0.8))
        b.blob("site", "leaf", (c.x, 1.05, -c.y), 0.28, 0.9)
    elif kind == "jhoola":
        # A swing on a timber frame over a stone pad.
        b.slab("site", "paving", ring(r * 0.9, 12), 0.0, 0.04)
        for s in (-1, 1):
            b.box("site", "timber", (c.x + s * 1.1, 1.2, -c.y), (0.14, 2.4, 0.14))
        b.box("site", "timber", (c.x, 2.4, -c.y), (2.5, 0.16, 0.16))
        for s in (-1, 1):
            b.box("site", "rail_metal", (c.x + s * 0.55, 1.6, -c.y), (0.02, 1.6, 0.02))
        b.box("site", "timber", (c.x, 0.8, -c.y), (1.3, 0.06, 0.5))
    elif kind == "waterwall":
        # A stone wall with a sheet of water down its face into a basin.
        b.box("site", "clad", (c.x, 0.9, -c.y), (2.2, 1.8, 0.3))
        b.box("site", "pool_water", (c.x, 0.95, -(c.y - 0.17)), (1.6, 1.4, 0.02))
        b.slab("site", "sill", [Vec2(c.x - 1.15, c.y - 0.2), Vec2(c.x + 1.15, c.y - 0.2), Vec2(c.x + 1.15, c.y - 0.9), Vec2(c.x - 1.15, c.y - 0.9)], 0.0, 0.25)
        b.slab("site", "pool_water", [Vec2(c.x - 1.0, c.y - 0.3), Vec2(c.x + 1.0, c.y - 0.3), Vec2(c.x + 1.0, c.y - 0.8), Vec2(c.x - 1.0, c.y - 0.8)], 0.253, 0.27)
    elif kind == "koipond":
        # A round pond in a ring of boulders, stepping stones across it.
        # A dark tiled bed and the water over it, each clear of the other and of the lawn.
        b.slab("site", "pool_tile", ring(r * 0.85, 20), 0.004, 0.03)
        b.slab("site", "pool_water", ring(r * 0.84, 20), 0.033, 0.07)
        for p in ring(r * 0.92, 12):
            b.blob("site", "boulder", (p.x, 0.05, -p.y), 0.22, 0.6)
        for k in (-0.5, 0.0, 0.5):
            b.cylinder("site", "paving", (c.x + k * r, 0.0, -(c.y + 0.1 * k)), 0.22, 0.06, 10)
        b.blob("site", "leaf2", (c.x + r * 0.6, 0.2, -(c.y + r * 0.5)), 0.3, 0.8)
    elif kind == "gazebo":
        # An octagonal pavilion: eight posts and a tiled pyramid roof.
        b.slab("site", "paving", ring(1.7, 8), 0.0, 0.12)
        posts = ring(1.5, 8)
        for p in posts:
            b.box("site", "timber", (p.x, 1.25, -p.y), (0.12, 2.3, 0.12))
        top = (c.x, 3.3, -c.y)
        eaves = ring(1.9, 8)
        for a, d in zip(eaves, eaves[1:] + eaves[:1]):
            b.tri("site", "roof_tile", (a.x, 2.4, -a.y), (d.x, 2.4, -d.y), top)
    elif kind == "rockgarden":
        # A gravel bed with boulders and low planting, raked smooth.
        b.slab("site", "yard_gravel", ring(r, 14), 0.0, 0.04)
        for k, p in enumerate(ring(r * 0.55, 5)):
            b.blob("site", "boulder", (p.x, 0.12, -p.y), 0.22 + 0.08 * (k % 3), 0.65)
        b.blob("site", "leaf", (c.x, 0.2, -c.y), 0.3, 0.7)
    elif kind == "fountain":
        # A tiered stone fountain in a round basin: a coping of stone blocks, water inside, a bowl on a stem.
        R = r * 0.85
        b.slab("site", "pool_tile", ring(R - 0.08, 20), 0.004, 0.06)
        b.slab("site", "pool_water", ring(R - 0.1, 20), 0.063, 0.3)
        n = 16
        for i in range(n):
            a = 2 * math.pi * i / n
            q = Vec2(c.x + R * math.cos(a), c.y + R * math.sin(a))
            b.box("site", "sill", (q.x, 0.2, -q.y), (2 * math.pi * R / n + 0.04, 0.4, 0.2), a + math.pi / 2)
        b.cylinder("site", "sill", (c.x, 0.0, -c.y), 0.16, 1.05, 12)
        b.cylinder("site", "sill", (c.x, 1.0, -c.y), 0.5, 0.14, 16)
        b.cylinder("site", "pool_water", (c.x, 1.12, -c.y), 0.44, 0.035, 16)
        b.cylinder("site", "sill", (c.x, 1.14, -c.y), 0.07, 0.35, 8)
        b.cylinder("site", "pool_water", (c.x, 1.48, -c.y), 0.035, 0.18, 6)
    elif kind == "firepit":
        # A ring of stone round the embers on a paved circle, four timber chairs drawn up to it.
        b.slab("site", "paving", ring(r * 0.95, 16), 0.0, 0.05)
        for i in range(10):
            a = 2 * math.pi * i / 10
            q = Vec2(c.x + 0.55 * math.cos(a), c.y + 0.55 * math.sin(a))
            b.box("site", "clad", (q.x, 0.2, -q.y), (0.38, 0.32, 0.2), a + math.pi / 2)
        b.blob("site", "fire", (c.x, 0.22, -c.y), 0.26, 0.55)
        for i in range(4):
            a = math.pi / 4 + i * math.pi / 2
            q = Vec2(c.x + 1.3 * math.cos(a), c.y + 1.3 * math.sin(a))
            bk = Vec2(c.x + 1.58 * math.cos(a), c.y + 1.58 * math.sin(a))
            b.box("site", "timber", (q.x, 0.38, -q.y), (0.62, 0.07, 0.6), a + math.pi / 2)
            b.box("site", "timber", (q.x, 0.19, -q.y), (0.5, 0.36, 0.45), a + math.pi / 2)
            b.box("site", "timber", (bk.x, 0.68, -bk.y), (0.62, 0.6, 0.07), a + math.pi / 2)
    elif kind == "lounge":
        # A raised timber deck on the lawn: two loungers, a side table and a square parasol.
        b.box("site", "timber", (c.x, 0.08, -c.y), (3.2, 0.16, 2.3), 0.0)
        for s in (-1, 1):
            p = Vec2(c.x + s * 0.75, c.y - 0.15)
            b.box("site", "timber", (p.x, 0.28, -p.y), (0.6, 0.22, 1.7))
            b.box("site", "linen", (p.x, 0.43, -p.y), (0.58, 0.08, 1.65))
        b.box("site", "timber", (c.x, 0.4, -(c.y - 0.6)), (0.45, 0.45, 0.45))
        b.cylinder("site", "rail_metal", (c.x, 0.16, -(c.y + 0.7)), 0.03, 2.2, 6)
        b.box("site", "linen", (c.x, 2.36, -(c.y + 0.7)), (2.4, 0.06, 2.4))
    elif kind == "flowerbeds":
        # Three round beds of mixed flowers in dark soil, each with a little green at its heart.
        cols = ("flower_pink", "flower_yellow", "flower_white")
        for k in range(3):
            a = 2 * math.pi * k / 3 + 0.4
            q = Vec2(c.x + r * 0.5 * math.cos(a), c.y + r * 0.5 * math.sin(a))
            bed = [Vec2(q.x + 0.62 * math.cos(2 * math.pi * i / 14), q.y + 0.62 * math.sin(2 * math.pi * i / 14)) for i in range(14)]
            b.slab("site", "soil", bed, 0.0, 0.07)
            b.blob("site", "leaf2", (q.x, 0.2, -q.y), 0.26, 0.7)
            for i in range(7):
                t = 2 * math.pi * i / 7 + k
                f = Vec2(q.x + 0.38 * math.cos(t), q.y + 0.38 * math.sin(t))
                b.blob("site", cols[(i + k) % 3], (f.x, 0.17, -f.y), 0.12, 0.8)
    elif kind == "sitout":
        # A stone pad under a shade tree with two benches.
        b.slab("site", "paving", ring(r * 0.9, 12), 0.0, 0.05)
        for s in (-1, 1):
            b.box("site", "timber", (c.x + s * 0.9, 0.42, -c.y), (0.45, 0.08, 1.4))
            b.box("site", "plinth", (c.x + s * 0.9, 0.2, -c.y), (0.35, 0.4, 1.1))
        b.cylinder("site", "trunk", (c.x, 0.0, -(c.y + r * 0.6)), 0.12, 2.4, 8)
        b.blob("site", "leaf", (c.x, 3.0, -(c.y + r * 0.6)), 1.3, 0.85)


def _lawn_life(b: Builder, plot, footprint, gate_c: Vec2, pool, yard) -> None:
    """What makes a lawn a garden: low lamps lining the drive (they glow at
    night), and a stepping-stone path from the drive across the grass to the
    garden's feature - each kept off the house, the pool and the plot's edge."""
    from shapely.geometry import LineString, Point

    from aip.engines.experience.landscape import DRIVE_HALF, drive_line

    keep_off = footprint.buffer(0.5)
    if pool is not None:
        keep_off = keep_off.union(pool.buffer(1.0))
    inside = plot.buffer(-0.45)
    line = drive_line(footprint, gate_c)
    # Lamps about every 2.4 m down both sides of the drive, spaced evenly over however long it is.
    n = max(1, int(line.length / 2.4))
    d = Vec2(line.coords[-1][0] - line.coords[0][0], line.coords[-1][1] - line.coords[0][1]).normalised()
    side = Vec2(-d.y, d.x)
    for i in range(n):
        q = line.interpolate((i + 0.5) * line.length / n)
        for s_ in (-1, 1):
            p = Vec2(q.x + side.x * s_ * (DRIVE_HALF + 0.35), q.y + side.y * s_ * (DRIVE_HALF + 0.35))
            if not inside.contains(Point(p.x, p.y)) or keep_off.contains(Point(p.x, p.y)):
                continue
            b.cylinder("site", "rail_metal", (p.x, 0.0, -p.y), 0.05, 0.62, 8)
            b.box("site", "light", (p.x, 0.68, -p.y), (0.13, 0.12, 0.13))
    # Stepping stones from the drive to the feature, if there is one to walk to.
    if yard is None:
        return
    c, r = yard
    drive = line.buffer(DRIVE_HALF)
    start = drive.exterior.interpolate(drive.exterior.project(Point(c.x, c.y)))
    path = LineString([(start.x, start.y), (c.x, c.y)])
    stop = path.length - r - 0.2
    k = 0.45
    while k < stop:
        q = path.interpolate(k)
        if inside.contains(q) and not keep_off.contains(q) and not drive.contains(q):
            b.cylinder("site", "paving", (q.x, 0.0, -q.y), 0.26, 0.05, 10)
        k += 0.72


def _pool(b: Builder, rect) -> None:
    """A pool set into a stone deck a step above the lawn: the tank tiled,
    the water a hand's width below a stone coping, two loungers on the deck."""
    from aip.engines.experience.landscape import POOL_DECK

    DECK, WATER, COPE = 0.30, 0.20, 0.30       # deck top, water level, coping width
    x0, y0, x1, y1 = rect.bounds
    d = POOL_DECK

    def frame(mat: str, out: float, z0: float, z1: float, inset: float = 0.0) -> None:
        # Four boxes round the tank, so the tank itself stays open.
        a0, b0, a1, b1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
        for (u0, v0, u1, v1) in ((a0 - out, b0 - out, a1 + out, b0), (a0 - out, b1, a1 + out, b1 + out),
                                 (a0 - out, b0, a0, b1), (a1, b0, a1 + out, b1)):
            if u1 - u0 > 0.01 and v1 - v0 > 0.01:
                b.box("site", mat, ((u0 + u1) / 2, (z0 + z1) / 2, -(v0 + v1) / 2), (u1 - u0, z1 - z0, v1 - v0))

    frame("paving", d, 0.0, DECK)                       # the deck
    frame("sill", COPE, DECK - 0.03, DECK + 0.05)       # the coping, proud of the deck
    frame("pool_tile", 0.06, 0.0, DECK - 0.03, inset=0.06)   # the tank's tiled walls
    b.box("site", "pool_tile", ((x0 + x1) / 2, 0.01, -(y0 + y1) / 2), (x1 - x0, 0.02, y1 - y0))
    # The water clear of the tiles by a few millimetres, so no face is shared.
    b.box("site", "pool_water", ((x0 + x1) / 2, (0.026 + WATER) / 2, -(y0 + y1) / 2),
          (x1 - x0 - 0.13, WATER - 0.026, y1 - y0 - 0.13))
    # Two loungers on the deck, along the long side, clear of the coping.
    along_x = (x1 - x0) >= (y1 - y0)
    mid = (COPE + d) / 2
    for k in (0.3, 0.62):
        if along_x:
            p = Vec2(x0 + (x1 - x0) * k, y1 + mid)
            size, base = (0.55, 0.07, 1.75), (0.45, 0.2, 1.5)
        else:
            p = Vec2(x1 + mid, y0 + (y1 - y0) * k)
            size, base = (1.75, 0.07, 0.55), (1.5, 0.2, 0.45)
        b.box("site", "timber", (p.x, DECK + 0.1, -p.y), base)
        b.box("site", "linen", (p.x, DECK + 0.235, -p.y), size)


def _boundary(b: Builder, kind: str, a: Vec2, c: Vec2, mid: Vec2, length: float, yaw: float) -> None:
    """One run of the boundary: a full wall (plaster, stone, brick), a low
    wall under a clipped hedge, or a low wall under a metal grille."""
    if kind == "hedge":
        b.box("site", "compound", (mid.x, 0.3, -mid.y), (length, 0.6, 0.22), yaw)
        b.box("site", "slab", (mid.x, 0.62, -mid.y), (length + 0.05, 0.05, 0.28), yaw)
        k = max(1, int(length / 0.55))
        for i in range(k):
            p = a + (c - a) * ((i + 0.5) / k)
            b.blob("site", "leaf" if i % 2 else "leaf2", (p.x, 1.05, -p.y), 0.42, 0.95)
        return
    if kind == "grille":
        b.box("site", "compound", (mid.x, 0.35, -mid.y), (length, 0.7, 0.22), yaw)
        b.box("site", "slab", (mid.x, 0.72, -mid.y), (length + 0.05, 0.05, 0.28), yaw)
        b.box("site", "rail_metal", (mid.x, 1.62, -mid.y), (length, 0.05, 0.06), yaw)
        k = max(2, int(length / 0.14))
        for i in range(k + 1):
            p = a + (c - a) * (i / k)
            b.box("site", "rail_metal", (p.x, 1.18, -p.y), (0.025, 0.9, 0.025), yaw)
        return
    b.box("site", "compound", (mid.x, 0.75, -mid.y), (length, 1.5, 0.2), yaw)
    b.box("site", "slab", (mid.x, 1.53, -mid.y), (length + 0.05, 0.06, 0.28), yaw)


def _gate(b: Builder, kind: str, seg, at: Vec2) -> None:
    """A gate across the opening in the boundary: steel bars or timber boards."""
    from shapely.geometry import Point

    if kind not in ("sliding", "timber"):
        return
    (xa, ya), (xb, yb) = seg.coords[0], seg.coords[-1]
    d = Vec2(xb - xa, yb - ya).normalised()
    t = seg.project(Point(at.x, at.y))
    c = Vec2(xa, ya) + d * t
    yaw = math.atan2(d.y, d.x)
    w = 3.6
    if kind == "timber":
        b.box("site", "gate", (c.x, 0.85, -c.y), (w, 1.5, 0.06), yaw)
        for k in range(1, 6):
            b.box("site", "gate_steel", (c.x, 0.1 + k * 0.28, -c.y), (w, 0.02, 0.08), yaw)
    else:
        b.box("site", "gate_steel", (c.x, 1.55, -c.y), (w, 0.06, 0.06), yaw)
        b.box("site", "gate_steel", (c.x, 0.15, -c.y), (w, 0.06, 0.06), yaw)
        for k in range(int(w / 0.12) + 1):
            q = c + d * (-w / 2 + k * 0.12)
            b.box("site", "gate_steel", (q.x, 0.85, -q.y), (0.025, 1.4, 0.025), yaw)
    for s in (-1, 1):
        q = c + d * (s * (w / 2 + 0.12))
        b.box("site", "compound", (q.x, 0.85, -q.y), (0.3, 1.7, 0.3), yaw)


def _solar(b: Builder, top: Level, footprint, y: float) -> None:
    """Rows of panels over the roof, tilted to the sun, clear of the stair head-room."""
    from shapely.geometry import box as sbox

    if footprint is None or footprint.is_empty:
        return
    free = footprint.buffer(-0.9)
    stair = next((r for r in top.rooms if r.type is RoomType.STAIRCASE), None)
    if stair is not None:
        bb = stair.bbox
        free = free.difference(sbox(bb.min_x - 0.4, bb.min_y - 0.4, bb.max_x + 0.4, bb.max_y + 0.4))
    if free.is_empty:
        return
    x0, y0, x1, y1 = free.bounds
    pw, pd, rise = 1.0, 1.7, 0.42          # a panel, landscape across, and its tilt
    yy = y0
    while yy + pd * 0.95 <= y1:
        xx = x0
        while xx + pw <= x1:
            if free.contains(sbox(xx, yy, xx + pw, yy + pd * 0.95)):
                lo, hi = y + 0.25, y + 0.25 + rise
                a, bq, c, d = (xx, lo, -yy), (xx + pw, lo, -yy), (xx + pw, hi, -(yy + pd * 0.95)), (xx, hi, -(yy + pd * 0.95))
                b.quad_strip("roof", "solar", a, bq, c, d)
                b.box("roof", "solar_frame", (xx + pw / 2, lo - 0.02, -yy), (pw, 0.04, 0.04))
                for px in (xx + 0.1, xx + pw - 0.1):
                    b.box("roof", "solar_frame", (px, y + 0.12 + rise / 2, -(yy + pd * 0.9)), (0.04, rise + 0.2, 0.04))
            xx += pw + 0.05
        yy += pd + 0.6


def _site(b: Builder, plan: FloorPlan, footprint, road: Vec2 | None) -> None:
    from shapely.geometry import LineString, Point, Polygon

    if not plan.site.boundary:
        return
    plot = Polygon([(p.x, p.y) for p in plan.site.boundary]).buffer(0)
    from aip.engines.experience.landscape import ground_cover, simple_parts

    # The lawn the client asked for, exactly (see landscape.ground_cover); with
    # none asked for, the plot is paved and nothing of a lawn is laid on it.
    cover = ground_cover(plan)
    has_lawn = not cover["lawn"].is_empty
    b.slab("site", "lawn" if has_lawn else "terrace", [Vec2(x, y) for x, y in list(plot.exterior.coords)[:-1]], -0.12, 0.0)
    # Plinth under the building.
    if footprint is not None:
        b.slab("site", "plinth", _poly_pts(footprint.buffer(0.15, join_style=2)), 0.0, PLINTH)

    # Compound wall with a gate on the road.
    minx, miny, maxx, maxy = plot.bounds
    ring = list(plot.exterior.coords)
    gate_c = None
    if road is not None:
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        gate_c = Vec2(cx + road.x * (maxx - minx) / 2, cy + road.y * (maxy - miny) / 2)
    for (xa, ya), (xb, yb) in zip(ring, ring[1:]):
        seg = LineString([(xa, ya), (xb, yb)])
        pieces = [seg]
        if gate_c is not None and seg.distance(Point(gate_c.x, gate_c.y)) < 0.5:
            gate = Point(gate_c.x, gate_c.y).buffer(1.9)
            diff = seg.difference(gate)
            pieces = list(getattr(diff, "geoms", [diff]))
            _gate(b, getattr(b.p, "gate", ""), seg, gate_c)
        for pc in pieces:
            if pc.is_empty or pc.length < 0.1:
                continue
            (x0, y0), (x1, y1) = pc.coords[0], pc.coords[-1]
            mid = Vec2((x0 + x1) / 2, (y0 + y1) / 2)
            yaw = math.atan2(y1 - y0, x1 - x0)
            _boundary(b, getattr(b.p, "boundary", ""), Vec2(x0, y0), Vec2(x1, y1), mid, pc.length, yaw)

    # Drive from the gate to the building.
    drive = None
    if gate_c is not None and footprint is not None:
        from aip.engines.experience.landscape import DRIVE_HALF, drive_line

        drive = drive_line(footprint, gate_c).buffer(DRIVE_HALF, cap_style=2)
        drive = drive.intersection(plot).difference(footprint.buffer(0.15))
        for g in getattr(drive, "geoms", [drive]):
            if g.geom_type == "Polygon" and g.area > 0.5:
                b.slab("site", "paving", [Vec2(x, y) for x, y in list(g.exterior.coords)[:-1]], 0.0, 0.03)

    # The rest of the open ground is a paved terrace and walks round the house.
    for g in simple_parts(cover["paved"]):
        b.slab("site", "terrace", [Vec2(x, y) for x, y in list(g.exterior.coords)[:-1]], 0.0, 0.025)
    lawn_only = cover["lawn"] if not cover["paved"].is_empty else None

    # The pool the client asked for, in the open garden away from the road.
    from aip.engines.experience.landscape import pool_rect

    pool = pool_rect(plan)
    if pool is not None:
        _pool(b, pool[0])

    # The garden feature the design carries, in its traditional quarter.
    from aip.engines.experience.landscape import yard_spot

    yard = yard_spot(plan, getattr(b.p, "yard", "")) if getattr(b.p, "yard", "") else None
    if yard is not None:
        _yard(b, b.p.yard, yard[0], yard[1])

    # A lawn is lived on: lamps along the drive, and stones across the grass to the garden's feature.
    if has_lawn and getattr(b.p, "garden", "") != "none" and footprint is not None and gate_c is not None:
        _lawn_life(b, plot, footprint, gate_c, pool[0] if pool is not None else None, yard)

    # A lush garden plants the inside of the boundary too, which a tight
    # city plot has room for even when its setbacks take no tree.
    if getattr(b.p, "garden", "") == "lush":
        edge = plot.buffer(-0.5)
        keep_off = (footprint.buffer(0.6) if footprint is not None else Polygon()).union(
            drive.buffer(0.4) if drive is not None else Polygon())
        if gate_c is not None:
            keep_off = keep_off.union(Point(gate_c.x, gate_c.y).buffer(2.3))
        if pool is not None:
            keep_off = keep_off.union(pool[0].buffer(1.3))
        if not edge.is_empty and edge.geom_type == "Polygon":
            ring_ = edge.exterior
            k = int(ring_.length / 1.1)
            for i in range(k):
                q = ring_.interpolate(i / k, normalized=True)
                if keep_off.contains(q) or (lawn_only is not None and not lawn_only.contains(q)):
                    continue
                b.blob("site", "leaf" if i % 3 else "leaf2", (q.x, 0.45, -q.y), 0.48, 0.85)

    # Trees and shrubs in the free setback, kept off the building and drive.
    free = plot.buffer(-1.2)
    if footprint is not None:
        free = free.difference(footprint.buffer(2.4))
    if drive is not None:
        free = free.difference(drive.buffer(1.0))
    if pool is not None:
        free = free.difference(pool[0].buffer(2.6))       # no canopy over the water
    if yard is not None:
        free = free.difference(Point(yard[0].x, yard[0].y).buffer(yard[1] + 1.0))
    if lawn_only is not None:
        free = free.intersection(lawn_only.buffer(-0.6))   # trees grow in the lawn, not through the terrace
    if free.is_empty:
        return
    rng = random.Random(int(hashlib.md5(plan.id.encode()).hexdigest()[:8], 16))
    fx0, fy0, fx1, fy1 = free.bounds
    placed: list[Vec2] = []
    for _ in range(400):
        if len(placed) >= {"lush": 26, "minimal": 5, "none": 0}.get(getattr(b.p, "garden", ""), 14 + int(plan.site.garden_share * 30)):
            break
        p = Vec2(rng.uniform(fx0, fx1), rng.uniform(fy0, fy1))
        if not free.contains(Point(p.x, p.y)) or any(p.distance_to(q) < 3.2 for q in placed):
            continue
        placed.append(p)
        if rng.random() < 0.65:
            h = rng.uniform(3.2, 5.5)
            b.cylinder("site", "trunk", (p.x, 0.0, -p.y), 0.12, h * 0.55, 8)
            for k in range(3):
                a = rng.uniform(0, 2 * math.pi)
                r = rng.uniform(0.0, 0.5)
                b.blob("site", "leaf" if k % 2 else "leaf2",
                       (p.x + math.cos(a) * r, h * (0.62 + 0.12 * k), -(p.y + math.sin(a) * r)),
                       rng.uniform(0.9, 1.35), 0.85)
        else:
            b.blob("site", "leaf2", (p.x, 0.35, -p.y), rng.uniform(0.45, 0.7), 0.7)


# ---------------------------------------------------------------------------
# Furniture
# ---------------------------------------------------------------------------


def _furniture(b: Builder, item, base: float, node: str) -> None:
    """One catalogue item as a recognisable piece, in the item's local frame."""
    iid = item.item_id
    w, d, h = item.width, item.depth, item.height
    rot = math.radians(item.rotation)
    cx, cz = item.x, -item.y

    def part(m: str, u: float, v: float, y0: float, sw: float, sd: float, sh: float) -> None:
        """A box at (u across, v front-to-back from the back edge) in the item's frame."""
        # The engine puts an item's back on its local -y (rotation 0 is against a
        # south wall, facing north), so the back edge is at lz = -d/2.
        lx, lz = u, -(d / 2 - v - sd / 2)
        x = cx + lx * math.cos(rot) - lz * math.sin(rot)
        z = cz - (lx * math.sin(rot) + lz * math.cos(rot))
        b.box(node, m, (x, base + y0 + sh / 2, z), (sw, sh, sd), -rot)

    if iid.startswith("bed"):
        part("joinery", 0, 0, 0.0, w, d, 0.32)
        part("linen", 0, 0.08, 0.32, w - 0.06, d - 0.1, 0.2)
        part("joinery", 0, 0, 0.0, w + 0.04, 0.08, max(h, 1.0))
        pillows = 2 if w > 1.2 else 1
        for k in range(pillows):
            u = (k - (pillows - 1) / 2) * (w / pillows)
            part("ceramic", u, 0.12, 0.52, w / pillows - 0.12, 0.35, 0.12)
        part("accent", 0, d * 0.62, 0.52, w - 0.02, d * 0.3, 0.03)
    elif iid.startswith(("sofa", "sectional", "recliner")):
        part("uph", 0, 0.15, 0.0, w, d - 0.15, 0.42)
        part("uph", 0, 0, 0.0, w, 0.18, 0.82)
        for s in (-1, 1):
            part("uph", s * (w / 2 - 0.09), 0.15, 0.0, 0.18, d - 0.15, 0.6)
        part("accent", -w / 4, 0.2, 0.42, 0.4, 0.12, 0.35)
    elif iid.startswith(("accent_chair", "wing_chair", "armchair", "reading_chair")):
        part("uph", 0, 0.1, 0.0, w, d - 0.1, 0.42)
        part("uph", 0, 0, 0.0, w, 0.12, 0.9)
    elif iid.startswith(("coffee", "centre_table", "family_table")):
        part("joinery", 0, 0, 0.36, w, d, 0.05)
        for su in (-1, 1):
            for sv in (0, 1):
                part("metal", su * (w / 2 - 0.05), sv * (d - 0.06), 0.0, 0.04, 0.06, 0.36)
    elif iid.startswith(("dining", "table")):
        part("joinery", 0, 0, 0.72, w, d, 0.05)
        for su in (-1, 1):
            for sv in (0, 1):
                part("joinery", su * (w / 2 - 0.08), sv * (d - 0.1), 0.0, 0.07, 0.07, 0.72)
        seats = max(2, int(w / 0.6)) // 1
        for k in range(seats):
            u = -w / 2 + w * (k + 0.5) / seats
            for v in (-0.5, d + 0.05):
                part("uph", u, v, 0.0, 0.45, 0.45, 0.46)
    elif iid.startswith(("wardrobe", "tall_unit", "crockery", "storage", "shoe_unit", "bookshelf",
                         "bookwall", "shelving", "sideboard")):
        part("joinery", 0, 0, 0.0, w, d, h)
        n = max(1, int(w / 0.5))
        for k in range(1, n):
            part("metal", -w / 2 + w * k / n, d - 0.01, h * 0.45, 0.012, 0.012, 0.25)
    elif iid.startswith(("tv_unit", "family_tv", "media", "screen_wall")):
        part("joinery", 0, 0, 0.0, w, d, min(h, 0.45))
        part("screen", 0, 0.02, 1.0, min(1.45, w * 0.7), 0.04, 0.82)
    elif iid.startswith("counter_run"):
        part("joinery", 0, 0, 0.0, w, d, 0.86)
        part("counter", 0, 0, 0.86, w + 0.02, d + 0.02, 0.04)
        part("joinery", 0, 0, 1.45, w, 0.35, 0.7)
        part("metal", -w / 4, 0.15, 0.9, 0.6, 0.45, 0.02)
        part("appliance", w / 4, 0.12, 0.9, 0.5, 0.4, 0.02)
    elif iid.startswith("fridge"):
        part("appliance", 0, 0, 0.0, w, d, h)
    elif iid.startswith(("desk", "study_desk", "console", "mirror_console", "dresser")):
        part("joinery", 0, 0, 0.72, w, d, 0.04)
        part("joinery", -w / 2 + 0.25, 0, 0.0, 0.45, d, 0.72)
        part("joinery", w / 2 - 0.03, 0, 0.0, 0.04, d, 0.72)
        if iid.startswith(("dresser", "mirror_console")):
            part("glass", 0, 0.01, 1.0, w * 0.7, 0.02, 0.8)
    elif iid.startswith("task_chair"):
        part("uph", 0, 0.05, 0.42, 0.48, 0.45, 0.08)
        part("uph", 0, 0, 0.5, 0.45, 0.06, 0.5)
        part("metal", 0, 0.25, 0.0, 0.06, 0.06, 0.42)
    elif iid.startswith("nightstand"):
        part("joinery", 0, 0, 0.0, w, d, h)
        part("light", 0, d / 2 - 0.08, h, 0.18, 0.18, 0.3)
    elif iid.startswith(("wc",)):
        part("ceramic", 0, 0, 0.0, w * 0.75, d * 0.7, 0.4)
        part("ceramic", 0, 0, 0.0, w * 0.75, 0.18, 0.8)
    elif iid.startswith(("basin", "utility_sink")):
        part("counter", 0, 0, 0.82, w, d, 0.04)
        part("joinery", 0, 0, 0.3, w, d, 0.5)
        part("ceramic", 0, 0.1, 0.86, w * 0.5, d * 0.6, 0.12)
        part("glass", 0, 0.0, 1.15, w * 0.8, 0.02, 0.75)
    elif iid.startswith("shower"):
        part("f_tile", 0, 0, 0.0, w, d, 0.04)
        part("glass", 0, d - 0.02, 0.04, w, 0.012, 2.0)
    elif iid.startswith(("washer",)):
        part("appliance", 0, 0, 0.0, w, d, h)
    elif iid.startswith("mandir"):
        part("joinery", 0, 0, 0.0, w, d, 0.8)
        part("brass", 0, 0.05, 0.8, w * 0.8, d * 0.7, 0.9)
        part("joinery", 0, 0, 1.7, w + 0.05, d + 0.05, 0.08)
    else:
        part("joinery", 0, 0, 0.0, w, d, max(h, 0.1))


def _interiors(b: Builder, plan: FloorPlan, bases: list[float]) -> None:
    try:
        from aip.engines.interior.engine import design_interior

        scheme = design_interior(plan)
    except Exception as exc:  # noqa: BLE001 - a model without furniture beats no model
        log_event(logger, "arch3d.interior_failed", plan=plan.id, error=str(exc))
        return
    room_level = {r.id: lv.index for lv in plan.levels for r in lv.rooms}
    for ri in scheme.rooms:
        li = room_level.get(ri.room_id)
        if li is None or li >= len(bases):
            continue
        node = f"level_{li}/furniture"
        for item in ri.furniture:
            try:
                _furniture(b, item, bases[li], node)
            except Exception:  # noqa: BLE001 - one odd item must not lose the room
                continue


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _road(plan: FloorPlan) -> Vec2 | None:
    dirs = plan.site.road_directions
    if not dirs:
        return None
    bearing = math.radians((dirs[0].bearing + plan.site.north_angle) % 360)
    return Vec2(math.sin(bearing), math.cos(bearing))


def build_scene(plan: FloorPlan, *, include_furniture: bool = True, include_ground: bool = True,
                palette_id: str | None = None, colour_text: str | None = None,
                design_id: str | None = None):
    """The full presentation model as a trimesh Scene.

    Coloured with `palette_id` if given, otherwise with the scheme the palette
    ranking recommends for this plan; `colour_text` (the client's own words)
    adds liked and avoided colours and exact per-surface overrides.
    """
    from aip.engines.experience.palettes import preferences_from_text, resolve

    prefs = preferences_from_text(colour_text) if colour_text else None
    try:
        scheme = resolve(plan, palette_id, prefs)
    except Exception:  # noqa: BLE001 - colour must never stop the model being built
        scheme = None
    palette = Palette(plan.style or "contemporary", scheme)
    b = Builder(palette)
    road = _road(plan)
    ground_fp = _footprint(plan.levels[0]) if plan.levels else None

    from aip.engines.experience import exteriors, facades

    ex = exteriors.Exterior.parse(design_id)
    if ex is None and design_id not in facades.DESIGNS:
        ex = exteriors.generate(plan, 1)[0]
    # The outside face of each floor's walls takes the design's skin.
    if ex is not None:
        ex, _ = ex.fitted(len(plan.levels) <= 1)
    palette.skins = exteriors.skins(ex, len(plan.levels)) if ex is not None else {}
    if ex is not None:
        if ex.roof == "slab":
            # A slab roof plate is concrete until the design tints it.
            palette.m["ex_roof"] = Material("roof_plate", palette.m["slab"].rgb, 0.9)
        exteriors.recolour(palette, ex)
    # The site after the design: its boundary wall is part of the design.
    if include_ground:
        _site(b, plan, ground_fp, road)

    bases: list[float] = []
    dressed: list[tuple[Level, float, Any]] = []
    y = PLINTH
    for level in plan.levels:
        bases.append(y)
        node = f"level_{level.index}"
        fp = _footprint(level)
        dressed.append((level, y, fp))
        pts = _poly_pts(fp)
        if pts:
            # Floor slab with a projecting band at the edge.
            from shapely.geometry import Polygon

            band = _poly_pts(Polygon([(p.x, p.y) for p in pts]).buffer(DRIP, join_style=2))
            if level.index > 0:
                b.slab(f"{node}/structure", "slab", band, y - SLAB, y)
        for room in level.rooms:
            if room.type is RoomType.SHAFT or len(room.polygon) < 3:
                continue
            b.slab(f"{node}/floors", _room_floor_material(room), room.polygon, y, y + 0.02)
            if room.type not in _OPEN_TO_SKY and room.type not in _RAILED and room.area > 2.0:
                c = room.centre
                b.cylinder(f"{node}/lights", "light", (c.x, y + level.floor_to_floor - SLAB - 0.06, -c.y),
                           0.22, 0.04, 16)
        _walls(b, plan, level, y, f"{node}/structure", road)
        for room in level.rooms:
            if room.type is RoomType.STAIRCASE and level.index < len(plan.levels) - 1:
                _stair(b, room, y, level.floor_to_floor, f"{node}/structure")
        y += level.floor_to_floor

    # The facade: the exterior grammar's design, or a named legacy language.

    try:
        if ex is not None:
            over = exteriors.apply(b, plan, ex, dressed, road, y)
        else:
            over = facades.apply(b, plan, facades.choose(plan, design_id), dressed, road, y)
    except Exception as exc:  # noqa: BLE001 - a plain facade beats no model
        log_event(logger, "arch3d.facade_failed", plan=plan.id, design=design_id, error=str(exc))
        over = {}
    roof_kind = over.get("roof", palette.roof_kind)
    if plan.levels:
        top = plan.levels[-1]
        fp = _footprint(top)
        if roof_kind in ("slab", "butterfly", "gable", "vault", "sawtooth"):
            b.slab("roof", "slab", _poly_pts(fp), y - SLAB, y)
            exteriors.roof(b, roof_kind, fp, y, road, slab_mat="ex_roof" if ex is not None else "slab")
            if roof_kind == "slab":
                _flat_roof_extras(b, top, y)
        elif roof_kind == "pitch":
            b.slab("roof", "slab", _poly_pts(fp), y - SLAB, y)
            facades.pitch_roof(b, fp, y, road)
        elif roof_kind == "hip":
            env = top.envelope()
            b.slab("roof", "slab", _poly_pts(fp), y - SLAB, y)
            _hip_roof(b, env, y)
        else:
            _flat_roof(b, plan, top, y, fp, palette)
        if palette.solar and roof_kind in ("flat", "slab"):
            _solar(b, top, fp, y + (0.18 if roof_kind == "slab" else 0.0))
    if include_furniture:
        _interiors(b, plan, bases)
    return b.scene()


def export_presentation_glb(plan: FloorPlan, **options: Any) -> bytes:  # options: see build_scene
    scene = build_scene(plan, **options)
    buffer = io.BytesIO()
    scene.export(buffer, file_type="glb")
    data = buffer.getvalue()
    log_event(logger, "arch3d.exported", plan=plan.id, bytes=len(data), nodes=len(scene.geometry))
    return data
