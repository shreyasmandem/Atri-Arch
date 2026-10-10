"""A small steady flow solver, so the airflow picture is computed, not drawn.

Sketching arrows on a plan is easy and worthless: the arrows go where whoever
drew them thought air ought to go. This solves for the flow instead, so the
picture can disagree with the designer - which is the only reason to draw it.

**The model.** Incompressible, irrotational, two-dimensional: a stream function
psi with laplace(psi) = 0 inside the room, and velocity taken as its curl, so
u = d(psi)/dy and v = -d(psi)/dx. Any field of that form conserves mass exactly,
which is what stops the picture showing air appearing in the middle of a room.

**Where the physics enters.** Entirely through the boundary. Walk the room's
perimeter and hold psi constant along solid wall - a constant psi contour *is* a
streamline, which is precisely the statement that air does not pass through
masonry. Across an opening, ramp psi by the volume flow. The difference between
the two ventilation modes is then not a special case in the code but a different
boundary condition:

* two openings on opposed faces - psi ramps up across the inlet and back down
  across the outlet, so there is net transport through the room;
* one opening - psi ramps up over the windward half of that aperture and back
  down over the leeward half, because with a single opening the air must leave
  through the way it came. The recirculation cell and the still region behind it
  are consequences of that, not decoration.

**What it is not.** Potential flow carries no viscosity and no turbulence, so it
will not give you a boundary layer, a separation point, or a mixing rate. It is
honest about the shape and reach of the flow and silent about everything else,
which is the right trade for a concept-stage drawing. The numbers a designer
should act on come from the ventilation analysis; this shows them what those
numbers mean.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import diags, identity, kron
from scipy.sparse.linalg import spsolve

from aip.domain.geometry import Vec2

#: Grid resolution along the room's longer side. Enough to resolve the
#: recirculation cell; small enough that a whole floor solves in well under a
#: second, because a drawing nobody waits for is a drawing nobody looks at.
RESOLUTION = 56
MIN_CELLS = 12


@dataclass(slots=True)
class FlowField:
    """A solved velocity field over a room's bounding box."""

    origin: Vec2
    cell: float            # metres per cell
    u: np.ndarray          # (ny, nx) velocity, x component
    v: np.ndarray          # (ny, nx) velocity, y component
    speed: np.ndarray      # (ny, nx) magnitude, normalised to [0, 1]

    @property
    def shape(self) -> tuple[int, int]:
        return self.speed.shape

    def at(self, point: Vec2) -> tuple[float, float]:
        """Velocity at a point in model space, nearest-cell."""
        ny, nx = self.speed.shape
        i = int((point.y - self.origin.y) / self.cell)
        j = int((point.x - self.origin.x) / self.cell)
        if not (0 <= i < ny and 0 <= j < nx):
            return 0.0, 0.0
        return float(self.u[i, j]), float(self.v[i, j])


def _perimeter_samples(nx: int, ny: int) -> list[tuple[int, int]]:
    """Boundary cells in order, walking the rectangle anticlockwise.

    The order matters: psi is assigned by accumulating flux as we walk, so the
    walk has to be a single continuous circuit or the stream function ends up
    multivalued and the solve produces nonsense.
    """
    cells: list[tuple[int, int]] = []
    for j in range(nx):                       # bottom, left to right
        cells.append((0, j))
    for i in range(1, ny):                    # right, upward
        cells.append((i, nx - 1))
    for j in range(nx - 2, -1, -1):           # top, right to left
        cells.append((ny - 1, j))
    for i in range(ny - 2, 0, -1):            # left, downward
        cells.append((i, 0))
    return cells


def _boundary_position(i: int, j: int, nx: int, ny: int, cell: float, origin: Vec2) -> Vec2:
    return Vec2(origin.x + (j + 0.5) * cell, origin.y + (i + 0.5) * cell)


def solve(
    width: float,
    height: float,
    origin: Vec2,
    openings: list[tuple[Vec2, float]],
    *,
    through_flow: bool,
) -> FlowField | None:
    """Solve the stream function for one room.

    `openings` are (centre, width) pairs in model space, already known to serve
    this room. `through_flow` says whether they sit on opposed faces, which is
    the single fact that decides whether air crosses the room or turns back.
    """
    if width <= 0 or height <= 0 or not openings:
        return None

    longest = max(width, height)
    resolution = max(40, min(80, int(round(longest * 7))))
    cell = longest / resolution
    nx = max(MIN_CELLS, int(round(width / cell)))
    ny = max(MIN_CELLS, int(round(height / cell)))
    if nx * ny > 20_000:                       # guard against a pathological room
        return None

    boundary = _perimeter_samples(nx, ny)
    psi_boundary = np.zeros(len(boundary))

    # Assign each boundary cell to an opening, if it lies within one.
    assigned: list[int | None] = []
    for i, j in boundary:
        point = _boundary_position(i, j, nx, ny, cell, origin)
        hit: int | None = None
        for index, (centre, opening_width) in enumerate(openings):
            if point.distance_to(centre) <= max(opening_width, cell * 1.5) / 2 + cell:
                hit = index
                break
        assigned.append(hit)

    # Walk the perimeter accumulating flux. Solid wall holds psi; an opening
    # ramps it. With one opening the ramp goes up then straight back down, which
    # is what makes the air return through the aperture it entered by.
    flux = 1.0
    if through_flow and len({a for a in assigned if a is not None}) >= 2:
        first = next(a for a in assigned if a is not None)
        counts = {
            index: sum(1 for a in assigned if a == index)
            for index in {a for a in assigned if a is not None}
        }
        widths = {
            index: width
            for index, (centre, width) in enumerate(openings)
            if index in {a for a in assigned if a is not None}
        }
        total_width = sum(widths.values())
        running = 0.0
        for k, owner in enumerate(assigned):
            if owner is not None:
                step = flux * (widths[owner] / total_width) / max(counts[owner], 1)
                running += step if owner == first else -step
            psi_boundary[k] = running
    else:
        owner = next((a for a in assigned if a is not None), None)
        if owner is None:
            return None
        indices = [k for k, a in enumerate(assigned) if a == owner]
        half = max(len(indices) // 2, 1)
        running = 0.0
        step = flux / half
        for k, a in enumerate(assigned):
            if a == owner:
                position = indices.index(k)
                running += step if position < half else -step
                running = max(running, 0.0)
            psi_boundary[k] = running

    # Solve laplace(psi) = 0 on the interior with those Dirichlet values. A
    # direct sparse solve rather than relaxation: the system is small, and an
    # exact answer removes any question of whether the picture is a converged
    # result or an artefact of stopping early.
    psi = np.zeros((ny, nx))
    for k, (i, j) in enumerate(boundary):
        psi[i, j] = psi_boundary[k]

    ny_i, nx_i = ny - 2, nx - 2
    if ny_i < 1 or nx_i < 1:
        return None

    # The five-point Laplacian as a Kronecker sum of two tridiagonals. Building
    # it this way rather than assigning coefficients cell by cell is the
    # difference between a drawing that appears while the client is looking at
    # it and one that arrives four seconds later.
    def tridiagonal(n: int):
        return diags([np.ones(n - 1), -2 * np.ones(n), np.ones(n - 1)], [-1, 0, 1])

    laplacian = (
        kron(identity(ny_i), tridiagonal(nx_i)) + kron(tridiagonal(ny_i), identity(nx_i))
    ).tocsr()

    # Known boundary values move to the right-hand side.
    rhs = np.zeros((ny_i, nx_i))
    rhs[0, :] -= psi[0, 1:-1]
    rhs[-1, :] -= psi[-1, 1:-1]
    rhs[:, 0] -= psi[1:-1, 0]
    rhs[:, -1] -= psi[1:-1, -1]

    psi[1:-1, 1:-1] = spsolve(laplacian, rhs.ravel()).reshape(ny_i, nx_i)

    # Velocity is the curl of the stream function, so mass is conserved by
    # construction rather than by hoping the discretisation behaves.
    v_comp, u_comp = np.gradient(psi, cell)
    u = u_comp
    v = -v_comp

    speed = np.hypot(u, v)
    ceiling = float(np.percentile(speed, 99.0)) or 1.0
    speed = np.clip(speed / ceiling, 0.0, 1.0)

    return FlowField(origin=origin, cell=cell, u=u, v=v, speed=speed)


def streamline(field: FlowField, start: Vec2, steps: int = 90) -> list[Vec2]:
    """Trace a path through the solved field with midpoint integration.

    Particles follow this, so they move the way the field says rather than along
    a curve chosen to look plausible. Where the field is still, the path stalls -
    which is exactly what should be visible in a room that does not ventilate.
    """
    ny, nx = field.shape
    step = field.cell * 0.9
    path = [start]
    point = start
    for _ in range(steps):
        ux, uy = field.at(point)
        magnitude = (ux * ux + uy * uy) ** 0.5
        if magnitude < 1e-6:
            break
        half = Vec2(point.x + ux / magnitude * step * 0.5,
                    point.y + uy / magnitude * step * 0.5)
        mx, my = field.at(half)
        m = (mx * mx + my * my) ** 0.5
        if m < 1e-6:
            break
        point = Vec2(point.x + mx / m * step, point.y + my / m * step)

        j = int((point.x - field.origin.x) / field.cell)
        i = int((point.y - field.origin.y) / field.cell)
        if not (0 <= i < ny and 0 <= j < nx):
            break
        path.append(point)
    return path
