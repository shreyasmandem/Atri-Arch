"""Whole-floor wind flow: the house as one domain, not rooms in isolation.

The per-room solve in `cfd` answers "how does air move inside this room once
it is in". It cannot answer the question a client actually asks - "if the
breeze comes from the south-west, which rooms does it reach?" - because that
depends on the doors between rooms as much as the windows in them. Air that
enters the living room and leaves through the bedroom on the far side is cross
ventilation for both; a room the breeze cannot find a way out of is dead.

**The model.** A horizontal slice at window height through the floor and the
ground around it, rasterised to a grid. Walls are solid; windows, ventilators,
balcony doors and (by default) interior doors are cut through them. Outside the
building the wind is a uniform stream from the chosen direction. Inside, the
velocity is the gradient of a potential with Laplace's equation holding on
every fluid cell and no flux into any solid one, so:

* mass is conserved cell by cell - air never appears or vanishes in a room;
* air can only enter a room through an opening and must leave through another;
* a room whose openings all face one way receives far less flow than one with
  openings on opposed faces, because the pressure difference across it is small.

Potential flow carries no viscosity, so it will not show separation bubbles or
turbulent mixing. It shows where the breeze goes and roughly how hard, which is
the concept-stage question. Air changes per hour are computed from the solved
flux through each room's openings, scaled by their real height and a discharge
coefficient, so the number beside a room is a property of the solve, not a
rule of thumb.
"""

from __future__ import annotations

import base64
import math
import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve
from shapely.geometry import Polygon
from shapely.ops import unary_union

from aip.domain.geometry import Direction
from aip.domain.plan import FloorPlan, Level, OpeningKind

#: Ground clearance drawn around the building, metres: enough for the stream
#: to bend round the house before it meets the domain edge.
MARGIN = 4.0
#: Aim for this many cells along the longer side; clamped to a cell size range
#: that still resolves a 230 mm wall and a 600 mm ventilator.
TARGET_CELLS = 340
MIN_CELL, MAX_CELL = 0.07, 0.2
#: Discharge coefficient of a sharp-edged opening (CIBSE AM10).
CD = 0.61
#: Reference wind at window height in a suburban plot, m/s. Met-office speeds
#: at 10 m over open ground roughly halve by the time they reach a ground floor
#: window between houses.
DEFAULT_SPEED = 2.0
#: A cut a few cells thick has almost no resistance of its own; a real
#: opening loses most of the wind's pressure in the contracting jet. This
#: scales the cut's conductance so a standard cross-ventilated room lands on
#: the orifice equation (Q = Cd A U sqrt(dCp)) within about 20%.
ORIFICE = 0.04
#: Indoor air speed a seated person notices as a cooling breeze.
COMFORT_SPEED = 0.15
#: Below this fraction of the free stream a cell counts as still air.
STILL = 0.025

_OPEN_KINDS = {OpeningKind.WINDOW, OpeningKind.FRENCH_WINDOW, OpeningKind.VENTILATOR,
               OpeningKind.SLIDING_DOOR, OpeningKind.ARCH}


@dataclass(slots=True)
class Grid:
    ox: float
    oy: float
    cell: float
    nx: int
    ny: int

    def to_px(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.ox) / self.cell, (y - self.oy) / self.cell


def wind_vector(bearing_from: float, north_angle: float = 0.0) -> tuple[float, float]:
    """Unit vector the air moves along, in plan coordinates.

    `bearing_from` is the compass bearing the wind blows from; `north_angle` is
    the bearing of the plan's +Y axis.
    """
    a = math.radians(bearing_from - north_angle)
    return -math.sin(a), -math.cos(a)


def _rect(a, b, half: float, t0: float, t1: float) -> list[tuple[float, float]]:
    """The rectangle of a wall segment between parameters t0..t1, `half` either side."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    nx_, ny_ = -uy * half, ux * half
    p0 = (a[0] + ux * t0, a[1] + uy * t0)
    p1 = (a[0] + ux * t1, a[1] + uy * t1)
    return [(p0[0] + nx_, p0[1] + ny_), (p1[0] + nx_, p1[1] + ny_),
            (p1[0] - nx_, p1[1] - ny_), (p0[0] - nx_, p0[1] - ny_)]


def _is_open(kind: OpeningKind, doors_open: bool) -> bool:
    if kind in _OPEN_KINDS:
        return True
    if kind is OpeningKind.DOOR:
        return doors_open
    return False  # the main door stays shut; skylights are not in the slice


def _rasterise(polys, grid: Grid, value: int, img: Image.Image) -> None:
    draw = ImageDraw.Draw(img)
    for pts in polys:
        draw.polygon([grid.to_px(x, y) for x, y in pts], fill=value)


def _level_geometry(level: Level, doors_open: bool, cell: float):
    """Solid wall polygons and the opening cuts through them, in model space."""
    solids, cuts, openings = [], [], []
    for w in level.walls:
        a, b = (w.start.x, w.start.y), (w.end.x, w.end.y)
        length = w.length
        if length < 1e-6:
            continue
        half = max(w.thickness / 2, cell * 0.75)
        solids.append(_rect(a, b, half, -half * 0.5, length + half * 0.5))
        for o in w.openings:
            c = o.position * length
            t0, t1 = max(0.0, c - o.width / 2), min(length, c + o.width / 2)
            open_ = _is_open(o.kind, doors_open)
            if open_:
                # An opening is not a hole through the whole storey: it is
                # `height` of a `w.height` wall, and its edges contract the jet.
                k = max(0.005, min(1.0, CD * o.height / max(w.height, o.height) * ORIFICE))
                cuts.append((_rect(a, b, half + cell * 1.2, t0, t1), k))
            p = w.point_at(o.position)
            openings.append({
                "id": o.id, "kind": o.kind.value, "x": round(p.x, 3), "y": round(p.y, 3),
                "width": o.width, "height": o.height, "open": open_,
                "exterior": w.kind.value == "exterior" or len(w.rooms) < 2,
                "rooms": list(w.rooms), "wall": [a, b], "t": (t0, t1),
            })
    return solids, cuts, openings


def solve_level(plan: FloorPlan, level_index: int, *, wind: Direction | float | None = None,
                speed: float = DEFAULT_SPEED, doors_open: bool = True) -> dict:
    """Solve the wind through one floor and return the field plus per-room numbers."""
    t_start = time.perf_counter()
    level = next((lv for lv in plan.levels if lv.index == level_index), None)
    if level is None:
        raise IndexError(level_index)

    if wind is None:
        from aip.engines.architecture.solar import prevailing_wind
        wind = prevailing_wind(plan.site.latitude, plan.site.longitude)[0]
    bearing = wind.bearing if isinstance(wind, Direction) else float(wind)
    north = float(getattr(plan.site, "north_angle", 0.0) or 0.0)
    wx, wy = wind_vector(bearing, north)

    # Domain: the floor plus a margin of open ground.
    pts = [(w.start.x, w.start.y) for w in level.walls] + [(w.end.x, w.end.y) for w in level.walls]
    pts += [(p.x, p.y) for r in level.rooms for p in r.polygon]
    if not pts:
        raise ValueError("empty level")
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0, x1, y1 = min(xs) - MARGIN, min(ys) - MARGIN, max(xs) + MARGIN, max(ys) + MARGIN
    cell = min(MAX_CELL, max(MIN_CELL, max(x1 - x0, y1 - y0) / TARGET_CELLS))
    nx, ny = int(math.ceil((x1 - x0) / cell)), int(math.ceil((y1 - y0) / cell))
    grid = Grid(x0, y0, cell, nx, ny)

    solids, cuts, openings = _level_geometry(level, doors_open, cell)
    img = Image.new("L", (nx, ny), 250)
    _rasterise(solids, grid, 0, img)
    for poly_, k in cuts:
        _rasterise([poly_], grid, int(round(k * 250)), img)
    cond = np.asarray(img, dtype=np.float64) / 250.0   # [row=y, col=x]
    fluid = cond > 0

    # Fluid that cannot reach open air (a sealed room) has no flow at all. It is
    # removed from the solve, or the system would be singular.
    labels, _ = ndimage.label(fluid)
    border = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    live = np.isin(labels, list(border))
    sealed = fluid & ~live

    # Laplace on live cells; Dirichlet free-stream potential on the domain edge.
    X = x0 + (np.arange(nx) + 0.5) * cell
    Y = y0 + (np.arange(ny) + 0.5) * cell
    phi_free = speed * (wx * X[None, :] + wy * Y[:, None])
    edge = np.zeros_like(live)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    unknown = live & ~edge
    idx = -np.ones((ny, nx), dtype=np.int64)
    idx[unknown] = np.arange(int(unknown.sum()))
    n = int(unknown.sum())

    rows, cols, vals = [], [], []
    rhs = np.zeros(n)
    diag = np.zeros(n)
    ui, uj = np.nonzero(unknown)
    me = idx[ui, uj]
    c_me = cond[ui, uj]
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ni, nj = ui + di, uj + dj
        ok = live[ni, nj]
        c_nb = cond[ni, nj]
        g = np.where(ok, 2 * c_me * c_nb / np.maximum(c_me + c_nb, 1e-12), 0.0)
        diag += g
        nb_unknown = ok & unknown[ni, nj]
        rows.append(me[nb_unknown]); cols.append(idx[ni[nb_unknown], nj[nb_unknown]])
        vals.append(-g[nb_unknown])
        nb_edge = ok & edge[ni, nj]
        np.add.at(rhs, me[nb_edge], g[nb_edge] * phi_free[ni[nb_edge], nj[nb_edge]])
    rows.append(np.arange(n)); cols.append(np.arange(n)); vals.append(diag)
    A = coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
    phi = np.where(live, phi_free, 0.0)
    if n:
        phi[unknown] = spsolve(A, rhs)

    # Face velocities, zero across any solid face, averaged to cell centres.
    fx = np.zeros((ny, nx + 1)); fy = np.zeros((ny + 1, nx))
    def face(ca, cb):
        return np.where((ca > 0) & (cb > 0), 2 * ca * cb / np.maximum(ca + cb, 1e-12), 0.0)
    cl = np.where(live, cond, 0.0)
    fx[:, 1:-1] = face(cl[:, 1:], cl[:, :-1]) * (phi[:, 1:] - phi[:, :-1]) / cell
    fy[1:-1, :] = face(cl[1:, :], cl[:-1, :]) * (phi[1:, :] - phi[:-1, :]) / cell
    # The domain edge carries the free stream.
    fx[:, 0], fx[:, -1] = fx[:, 1], fx[:, -2]
    fy[0, :], fy[-1, :] = fy[1, :], fy[-2, :]
    u = np.where(live, 0.5 * (fx[:, 1:] + fx[:, :-1]), 0.0)
    v = np.where(live, 0.5 * (fy[1:, :] + fy[:-1, :]), 0.0)
    mag = np.hypot(u, v)

    # Rooms: rasterise each, then measure the flux across its edge.
    rooms_out = []
    room_mask = np.zeros((ny, nx), dtype=np.int32)
    order = [r for r in level.rooms if len(r.polygon) >= 3]
    for k, r in enumerate(order, start=1):
        im = Image.new("L", (nx, ny), 0)
        _rasterise([[(p.x, p.y) for p in r.polygon]], grid, 1, im)
        m = np.asarray(im, dtype=bool) & fluid
        room_mask[m & (room_mask == 0)] = k
    for k, r in enumerate(order, start=1):
        m = room_mask == k
        inside = m & live
        # Inflow per metre of slice: faces where flow crosses into the room.
        inflow = 0.0
        # x faces between column j (left) and j+1 (right)
        flx = fx[:, 1:-1]
        ml, mr = m[:, :-1], m[:, 1:]
        inflow += float(np.clip(flx[~ml & mr], 0, None).sum() + np.clip(-flx[ml & ~mr], 0, None).sum()) * cell
        fly = fy[1:-1, :]
        mb, mt = m[:-1, :], m[1:, :]
        inflow += float(np.clip(fly[~mb & mt], 0, None).sum() + np.clip(-fly[mb & ~mt], 0, None).sum()) * cell
        rops = [o for o in openings if r.id in o["rooms"] and o["open"]]
        ext = [o for o in rops if o["exterior"]]
        # The slice flux is already storey-averaged (openings are resistances
        # sized by their height), so it scales by the full ceiling height.
        q = inflow * r.ceiling_height                              # m3/s
        volume = max(r.area, 0.5) * r.ceiling_height
        ach = q * 3600.0 / volume
        cells = int(m.sum()) or 1
        mean = float(mag[inside].mean()) if inside.any() else 0.0
        still = float((mag[m] < STILL * speed).sum()) / cells
        faces = {_face(o, r) for o in ext}
        mode = ("sealed" if not inside.any() or not rops else
                "cross" if len(faces) >= 2 or (len(rops) >= 2 and ach >= 6) else
                "single" if ext else "borrowed")
        verdict = ("good" if mean >= COMFORT_SPEED * speed / DEFAULT_SPEED and still < 0.5 else
                   "fair" if mean >= 0.05 * speed / DEFAULT_SPEED or ach >= 15 else "poor")
        if r.type.is_outdoor:
            verdict = "open"
        rooms_out.append({
            "id": r.id, "name": r.display_name(), "type": r.type.value, "area": round(r.area, 1),
            "polygon": [[round(p.x, 3), round(p.y, 3)] for p in r.polygon],
            "centre": [round(r.centre.x, 3), round(r.centre.y, 3)],
            "ach": round(ach, 1), "flow_m3h": round(q * 3600, 0), "mean_speed": round(mean, 2),
            "still_share": round(still, 2), "mode": mode, "verdict": verdict,
            "habitable": r.type.is_habitable,
        })

    # Per opening: net flow through it, signed into the first room it serves.
    for o in openings:
        if not o["open"]:
            o["flow"] = 0.0
            continue
        (ax, ay), (bx, by) = o["wall"]
        L = math.hypot(bx - ax, by - ay) or 1.0
        ux_, uy_ = (bx - ax) / L, (by - ay) / L
        nxn, nyn = -uy_, ux_
        tot = 0.0
        steps = max(2, int((o["t"][1] - o["t"][0]) / cell))
        for s in range(steps):
            t = o["t"][0] + (s + 0.5) * (o["t"][1] - o["t"][0]) / steps
            px, py = ax + ux_ * t, ay + uy_ * t
            j, i = int((px - x0) / cell), int((py - y0) / cell)
            if 0 <= i < ny and 0 <= j < nx:
                tot += (u[i, j] * nxn + v[i, j] * nyn) * (o["t"][1] - o["t"][0]) / steps
        o["flow"] = round(tot * 3.0, 3)
        o["normal"] = [round(nxn, 3), round(nyn, 3)]
    for o in openings:
        o.pop("wall", None); o.pop("t", None)

    walls = unary_union([Polygon(p) for p in solids]).difference(unary_union([Polygon(p) for p, _k in cuts]))
    wall_polys = [g for g in getattr(walls, "geoms", [walls]) if not g.is_empty]

    habitable = [r for r in rooms_out if r["habitable"]]
    comfort = COMFORT_SPEED * speed / DEFAULT_SPEED
    score = (sum(min(r["mean_speed"] / comfort, 1.0) * (1 - r["still_share"] * 0.5) for r in habitable)
             / len(habitable)) if habitable else 0.0

    def b64(a: np.ndarray, dtype) -> str:
        return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode("ascii")

    return {
        "level": level_index,
        "grid": {"x0": x0, "y0": y0, "cell": cell, "nx": nx, "ny": ny},
        "wind": {"from": bearing, "speed": speed, "vector": [wx, wy],
                 "label": wind.value if isinstance(wind, Direction) else f"{bearing:.0f}°"},
        "doors_open": doors_open,
        "u": b64(u, "<f2"), "v": b64(v, "<f2"),
        "mask": b64(np.where(sealed, 2, np.where(live, 1, 0)), "u1"),
        "walls": [[[round(x, 3), round(y, 3)] for x, y in g.exterior.coords] for g in wall_polys],
        "rooms": rooms_out,
        "openings": openings,
        "summary": {
            "score": round(score, 3),
            "cross_ventilated": sum(1 for r in habitable if r["mode"] == "cross"),
            "habitable": len(habitable),
            "poor": [r["name"] for r in habitable if r["verdict"] == "poor"],
            "max_speed": round(float(mag.max()), 2),
            "solve_ms": round((time.perf_counter() - t_start) * 1000),
        },
    }


def _face(o: dict, room) -> str:
    """Which side of the room an opening sits on: N/S/E/W of its centre."""
    c = room.centre
    dx, dy = o["x"] - c.x, o["y"] - c.y
    return ("E" if dx > 0 else "W") if abs(dx) > abs(dy) else ("N" if dy > 0 else "S")


def best_wind(plan: FloorPlan, level_index: int, **kw) -> list[dict]:
    """Score the floor for each of the eight winds: which breeze suits this plan."""
    out = []
    for d in (Direction.N, Direction.NE, Direction.E, Direction.SE, Direction.S, Direction.SW, Direction.W, Direction.NW):
        s = solve_level(plan, level_index, wind=d, **kw)["summary"]
        out.append({"wind": d.value, "score": s["score"], "cross": s["cross_ventilated"]})
    return out


__all__ = ["best_wind", "solve_level", "wind_vector"]
