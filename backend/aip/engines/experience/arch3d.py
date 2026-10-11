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
            "lawn": Material("lawn", (0.33, 0.47, 0.24), 1.0),
            "paving": Material("paving", (0.70, 0.67, 0.62), 0.9),
            "compound": Material("compound_wall", (0.86, 0.84, 0.80), 0.95),
            "trunk": Material("tree_trunk", (0.33, 0.24, 0.17), 0.95),
            "leaf": Material("foliage", (0.24, 0.42, 0.20), 0.9),
            "leaf2": Material("foliage_light", (0.36, 0.52, 0.26), 0.9),
            "water": Material("water_tank", (0.20, 0.20, 0.21), 0.6),
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
            label = f"{node}/{mat.name}".replace("/", "__")
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


def _walls(b: Builder, plan: FloorPlan, level: Level, base: float, node: str, road: Vec2 | None) -> None:
    by_id = {r.id: r for r in level.rooms}
    accents = _accent_walls(level)
    centre = level.envelope().centre
    height = level.floor_to_floor - SLAB
    for wall in _merged_walls(level):
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
        for o in sorted(wall.openings, key=lambda o: o.position):
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
        hx, hz = cx + out.x * (t / 2 + CHAJJA_DEPTH / 2), cz - out.y * (t / 2 + CHAJJA_DEPTH / 2)
        b.box(node, "slab", (hx, base + head + 0.12, hz), (w + 0.3, 0.075, CHAJJA_DEPTH), yaw)


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
    cdepth = 1.4
    c = mid + out * (cdepth / 2)
    b.box("level_0/facade", "slab", (c.x, base + head + 0.25, -c.y), (width + 1.6, 0.12, cdepth), yaw)


def _railing(b: Builder, node: str, a: Vec2, c: Vec2, base: float, out: Vec2) -> None:
    d = c - a
    length = d.length
    yaw = _yaw(d.normalised())
    mid = (a + c) * 0.5
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
        b.box("roof", "plaster", (mid.x, y + PARAPET / 2, -mid.y), (d.length + 0.12, PARAPET, 0.12), yaw)
        b.box("roof", "slab", (mid.x, y + PARAPET + 0.03, -mid.y), (d.length + 0.2, 0.06, 0.2), yaw)
    # Stair head-room and a water tank over it.
    stair = next((r for r in top.rooms if r.type is RoomType.STAIRCASE), None)
    if stair is not None:
        bb = stair.bbox
        b.box("roof", "plaster", (bb.centre.x, y + 1.3, -bb.centre.y), (bb.width, 2.6, bb.height))
        b.box("roof", "slab", (bb.centre.x, y + 2.66, -bb.centre.y), (bb.width + 0.3, 0.12, bb.height + 0.3))
        b.cylinder("roof", "water", (bb.centre.x, y + 2.72, -bb.centre.y), 0.65, 1.1, 16)
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


def _site(b: Builder, plan: FloorPlan, footprint, road: Vec2 | None) -> None:
    from shapely.geometry import LineString, Point, Polygon

    if not plan.site.boundary:
        return
    plot = Polygon([(p.x, p.y) for p in plan.site.boundary]).buffer(0)
    b.slab("site", "lawn", [Vec2(x, y) for x, y in list(plot.exterior.coords)[:-1]], -0.12, 0.0)
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
        for pc in pieces:
            if pc.is_empty or pc.length < 0.1:
                continue
            (x0, y0), (x1, y1) = pc.coords[0], pc.coords[-1]
            mid = Vec2((x0 + x1) / 2, (y0 + y1) / 2)
            yaw = math.atan2(y1 - y0, x1 - x0)
            b.box("site", "compound", (mid.x, 0.75, -mid.y), (pc.length, 1.5, 0.2), yaw)
            b.box("site", "slab", (mid.x, 1.53, -mid.y), (pc.length + 0.05, 0.06, 0.28), yaw)

    # Drive from the gate to the building.
    drive = None
    if gate_c is not None and footprint is not None:
        near = footprint.exterior.interpolate(footprint.exterior.project(Point(gate_c.x, gate_c.y)))
        drive = LineString([(gate_c.x, gate_c.y), (near.x, near.y)]).buffer(1.6, cap_style=2)
        drive = drive.intersection(plot).difference(footprint.buffer(0.15))
        for g in getattr(drive, "geoms", [drive]):
            if g.geom_type == "Polygon" and g.area > 0.5:
                b.slab("site", "paving", [Vec2(x, y) for x, y in list(g.exterior.coords)[:-1]], 0.0, 0.03)

    # Trees and shrubs in the free setback, kept off the building and drive.
    free = plot.buffer(-1.2)
    if footprint is not None:
        free = free.difference(footprint.buffer(2.4))
    if drive is not None:
        free = free.difference(drive.buffer(1.0))
    if free.is_empty:
        return
    rng = random.Random(int(hashlib.md5(plan.id.encode()).hexdigest()[:8], 16))
    fx0, fy0, fx1, fy1 = free.bounds
    placed: list[Vec2] = []
    for _ in range(400):
        if len(placed) >= 14:
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
    if include_ground:
        _site(b, plan, ground_fp, road)

    from aip.engines.experience import exteriors, facades

    ex = exteriors.Exterior.parse(design_id)
    if ex is None and design_id not in facades.DESIGNS:
        ex = exteriors.generate(plan, 1)[0]
    # The outside face of each floor's walls takes the design's skin.
    palette.skins = exteriors.skins(ex, len(plan.levels)) if ex is not None else {}

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
        if roof_kind in ("slab", "butterfly", "gable"):
            b.slab("roof", "slab", _poly_pts(fp), y - SLAB, y)
            exteriors.roof(b, roof_kind, fp, y, road)
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
