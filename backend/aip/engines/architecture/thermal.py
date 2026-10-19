"""Room temperatures through a day: how hot each room gets, when, and why.

The airflow solve says where the breeze goes; this says what it does for the
people inside. Each indoor room is a small thermal model run hour by hour
through a design day of the nearest Indian city's climate:

**Two nodes per room.** The room air, and the thermal mass around it (brick
walls, the RCC floor and ceiling). Heat reaches the mass first - the sun on an
outside wall or the roof is conducted in through it - and the mass hands it to
the air later, which is the afternoon-to-evening lag every Indian home with a
west wall or an exposed roof slab knows. Glass, ventilation and people act on
the air directly.

**What drives it.**

* Outdoor air: the city's design-day maximum and minimum for the season,
  spread over 24 hours by the ASHRAE daily-range profile (coolest near dawn,
  hottest about 3 pm).
* Sun: position from the NOAA algorithm in `solar`, clear-sky beam and diffuse
  on each wall by its real compass facing, and on the roof. Walls and roofs
  take it as sol-air temperature; windows let it straight in, less what the
  chajja above them shades at that hour's sun angle.
* Air changes: from the floor's wind solve (`windflow`) under the season's
  prevailing wind, so a cross-ventilated room really is cooled by its breeze
  and a sealed one is not. When the windows are open, outdoor air replaces the
  room air at that rate.
* People, lights and cooking, on a typical Indian household's day.

**Comfort.** India's own adaptive comfort model (IMAC, Manu et al. 2016):
neutral temperature 0.54 x outdoor running mean + 12.83 C, with +/-2.4 C for
90% acceptability. Moving air (the breeze, or a ceiling fan) feels cooler, so
the "feels like" temperature takes off the cooling effect of the air speed.

**Cooling.** Holding a room at 26 C with the windows shut gives the sensible
cooling load, which sizes the AC.

It is a concept-stage model: it ranks rooms correctly and shows the size of
each fix, and it is not a substitute for a full simulation (EnergyPlus).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from aip.domain.geometry import Direction
from aip.domain.plan import FloorPlan, OpeningKind, Room, RoomType, WallKind
from aip.engines.architecture.solar import prevailing_wind, sun_position

#: Monthly climate normals, January to December: mean daily maximum and
#: minimum (C) and mean relative humidity (%), after IMD's 1991-2020
#: climatological normals for each city's observatory, rounded to the half
#: degree. Approximate: for a design decision, not a weather record.
#: city -> (lat, lon, max x12, min x12, RH x12)
CITIES: dict[str, tuple[float, float, tuple, tuple, tuple]] = {
    "Chennai": (13.08, 80.27, (29.5, 31.0, 33.0, 35.0, 38.0, 37.5, 35.5, 34.5, 34.0, 32.0, 29.5, 28.5),
                (21.0, 22.0, 24.0, 26.5, 28.0, 27.5, 26.5, 26.0, 25.5, 24.5, 23.0, 22.0), (70, 68, 68, 70, 64, 58, 63, 66, 70, 77, 79, 75)),
    "Bengaluru": (12.97, 77.59, (28.0, 30.5, 33.0, 34.0, 33.0, 29.5, 28.0, 27.5, 28.5, 28.5, 27.0, 26.5),
                  (16.0, 17.5, 20.0, 22.0, 21.5, 20.5, 20.0, 20.0, 19.5, 19.5, 18.0, 16.0), (60, 52, 48, 55, 64, 75, 79, 79, 76, 74, 71, 66)),
    "Hyderabad": (17.39, 78.49, (29.0, 32.0, 35.5, 38.5, 39.5, 34.0, 30.5, 30.0, 30.5, 30.5, 29.0, 28.0),
                  (15.5, 18.0, 21.0, 24.5, 26.5, 24.5, 23.0, 22.5, 22.0, 20.5, 17.0, 14.5), (55, 46, 39, 39, 39, 62, 73, 76, 74, 66, 60, 58)),
    "Mumbai": (19.08, 72.88, (30.5, 31.5, 32.5, 33.0, 33.5, 32.0, 30.0, 29.5, 30.5, 33.0, 33.5, 32.0),
               (17.0, 18.0, 20.5, 23.5, 26.5, 26.0, 25.0, 25.0, 24.5, 23.5, 21.0, 18.5), (62, 62, 65, 69, 70, 79, 85, 85, 82, 74, 64, 61)),
    "Pune": (18.52, 73.86, (30.5, 32.5, 35.5, 37.5, 36.5, 31.0, 28.0, 27.0, 29.0, 31.5, 30.5, 29.5),
             (11.0, 12.0, 15.5, 19.5, 22.0, 22.5, 21.5, 21.0, 20.5, 18.0, 13.5, 11.0), (56, 48, 42, 47, 57, 75, 83, 84, 79, 66, 58, 57)),
    "Delhi": (28.61, 77.21, (20.5, 24.5, 30.5, 36.5, 40.5, 39.5, 35.5, 34.0, 34.0, 33.0, 28.0, 23.0),
              (7.5, 10.0, 15.0, 21.0, 25.5, 27.5, 27.0, 26.5, 24.5, 19.5, 13.0, 8.5), (75, 66, 55, 39, 38, 51, 72, 76, 70, 59, 62, 71)),
    "Kolkata": (22.57, 88.36, (26.5, 29.5, 34.0, 36.0, 35.5, 34.0, 32.0, 32.0, 32.0, 31.5, 30.0, 27.5),
                (14.0, 17.5, 22.0, 25.0, 26.5, 26.5, 26.0, 26.0, 25.5, 24.0, 19.0, 14.5), (67, 63, 63, 70, 74, 80, 84, 85, 83, 78, 71, 68)),
    "Ahmedabad": (23.02, 72.57, (28.5, 31.0, 36.0, 40.0, 41.5, 38.5, 33.5, 32.5, 34.0, 36.0, 33.0, 30.0),
                  (12.0, 14.5, 19.5, 23.5, 26.5, 27.5, 26.0, 25.5, 25.0, 21.5, 17.0, 13.0), (50, 43, 38, 42, 52, 65, 78, 80, 73, 55, 47, 51)),
    "Jaipur": (26.91, 75.79, (22.5, 26.0, 31.5, 37.5, 41.0, 39.5, 35.0, 33.0, 33.5, 33.5, 29.0, 24.5),
               (8.5, 10.5, 15.5, 21.5, 25.5, 27.0, 26.0, 24.5, 23.0, 19.0, 13.5, 9.5), (55, 46, 35, 26, 30, 46, 68, 74, 65, 45, 45, 52)),
    "Kochi": (9.93, 76.27, (31.5, 32.0, 32.5, 33.0, 32.5, 29.5, 29.0, 29.0, 30.0, 30.5, 31.0, 31.5),
              (23.0, 24.0, 25.5, 26.0, 25.5, 24.0, 23.5, 24.0, 24.0, 24.0, 24.0, 23.5), (70, 72, 73, 75, 77, 86, 88, 86, 84, 83, 79, 72)),
    "Thiruvananthapuram": (8.52, 76.94, (31.5, 32.0, 33.0, 32.5, 31.5, 29.5, 29.0, 29.5, 30.0, 30.0, 30.5, 31.0),
                           (22.5, 23.5, 24.5, 25.5, 25.5, 24.0, 23.5, 23.5, 24.0, 23.5, 23.5, 23.0), (71, 71, 72, 75, 78, 84, 84, 82, 80, 82, 81, 75)),
    "Lucknow": (26.85, 80.95, (22.5, 26.5, 32.5, 38.5, 40.5, 38.5, 34.0, 33.5, 33.5, 32.5, 29.0, 24.5),
                (7.5, 10.5, 15.0, 20.5, 25.0, 27.5, 26.5, 26.0, 24.5, 19.5, 13.0, 8.5), (75, 65, 50, 38, 42, 60, 79, 83, 79, 68, 66, 73)),
    "Bhopal": (23.26, 77.41, (25.5, 29.0, 34.0, 38.5, 41.5, 36.5, 30.5, 28.5, 30.5, 31.5, 29.0, 26.5),
               (10.5, 12.5, 17.0, 22.0, 26.5, 25.5, 23.5, 23.0, 22.0, 18.5, 14.0, 10.5), (52, 42, 30, 25, 26, 55, 80, 85, 75, 55, 50, 52)),
    "Nagpur": (21.15, 79.09, (28.5, 32.0, 36.5, 41.0, 43.0, 37.5, 31.5, 30.5, 32.0, 32.5, 30.5, 28.5),
               (12.5, 15.0, 19.5, 24.0, 28.0, 27.0, 24.5, 24.0, 23.5, 19.5, 14.5, 12.0), (55, 44, 33, 28, 28, 55, 79, 82, 76, 62, 55, 56)),
    "Coimbatore": (11.02, 76.96, (30.0, 32.5, 35.0, 35.0, 33.0, 30.5, 30.0, 30.5, 31.5, 30.5, 29.0, 28.5),
                   (19.0, 19.5, 21.5, 23.0, 23.0, 22.0, 21.5, 21.5, 21.5, 21.5, 20.5, 19.5), (65, 58, 55, 62, 67, 70, 72, 72, 71, 75, 77, 72)),
    "Visakhapatnam": (17.69, 83.22, (28.5, 30.5, 33.0, 33.5, 34.5, 33.5, 32.0, 32.0, 32.0, 31.5, 30.0, 28.5),
                      (18.0, 20.0, 23.0, 26.0, 27.5, 27.0, 26.0, 26.0, 25.5, 24.0, 21.0, 18.5), (69, 71, 74, 76, 74, 72, 76, 76, 78, 74, 68, 67)),
    "Chandigarh": (30.73, 76.78, (19.5, 23.0, 28.0, 34.5, 38.5, 38.0, 33.5, 32.5, 32.5, 31.5, 27.0, 21.5),
                   (6.0, 8.5, 13.0, 18.0, 22.5, 24.5, 24.5, 24.0, 22.0, 16.5, 10.5, 6.5), (75, 68, 58, 40, 36, 48, 75, 80, 72, 60, 65, 74)),
    "Guwahati": (26.14, 91.74, (24.0, 27.0, 30.5, 31.5, 32.0, 32.0, 32.0, 32.5, 31.5, 30.5, 28.0, 25.0),
                 (10.5, 12.5, 16.5, 20.0, 22.5, 24.5, 25.5, 25.5, 24.5, 21.5, 16.5, 12.0), (78, 68, 62, 72, 79, 84, 85, 84, 84, 82, 80, 80)),
    "Panaji": (15.49, 73.83, (31.5, 31.5, 32.0, 33.0, 33.5, 30.5, 29.0, 29.0, 30.0, 32.0, 33.0, 32.5),
               (19.5, 20.5, 23.0, 25.0, 26.5, 25.0, 24.5, 24.0, 24.0, 24.0, 22.0, 20.5), (64, 67, 70, 72, 73, 85, 88, 87, 84, 77, 67, 63)),
}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
SEASONS = ("summer", "monsoon", "winter")
SEASON_NAMES = {"summer": "Hottest month", "monsoon": "Wettest month", "winter": "Coolest month"}


def season_month(city: str, season: str) -> int:
    """The month (1-12) that stands for a season in this city: its hottest,
    its most humid monsoon month, or its coldest."""
    _lat, _lon, tmax, tmin, rh = CITIES[city]
    if season == "summer":
        return max(range(12), key=lambda m: tmax[m]) + 1
    if season == "winter":
        return min(range(12), key=lambda m: tmin[m]) + 1
    return max(range(5, 12), key=lambda m: rh[m]) + 1


def month_climate(city: str, month: int) -> dict:
    """The design day for a month: its averages, a representative day of the
    year, the share of clear-sky sun the clouds let through, and the wind."""
    _lat, _lon, tmax, tmin, rh = CITIES[city]
    i = month - 1
    return {"max": tmax[i], "min": tmin[i], "humidity": rh[i], "day": int(15 + 30.44 * i),
            "clear": max(0.4, min(1.0, 1.0 - max(0, rh[i] - 62) / 45)),
            "monsoon": 6 <= month <= 9, "winter": month in (11, 12, 1, 2)}


#: ASHRAE fraction of the daily range below the maximum, hour 0..23.
_RANGE = (0.82, 0.87, 0.92, 0.96, 0.99, 1.00, 0.98, 0.93, 0.84, 0.71, 0.56, 0.39,
          0.23, 0.11, 0.03, 0.00, 0.03, 0.10, 0.21, 0.34, 0.47, 0.58, 0.68, 0.76)

#: Building physics (Indian construction defaults).
U_WALL = 2.1          # W/m2K: 230 mm brick, plastered both sides
U_ROOF = 3.0          # 150 mm RCC slab with finishes, no insulation
U_ROOF_COOL = 1.2     # with a reflective coat and 50 mm insulation / brick-bat coba
U_GLASS = 5.7         # single clear glass
SHGC = 0.6            # single clear glass with a light curtain
ABS_WALL = 0.5        # light-coloured plaster
ABS_ROOF = 0.75       # grey RCC
ABS_ROOF_COOL = 0.25  # white reflective roof coat
H_OUT = 17.0          # outside surface coefficient, W/m2K
H_MASS = 3.5          # mass-to-air convective coefficient
C_MASS = 120e3        # J/m2K of exposed mass area (first ~80 mm of brick/RCC)
RHO_CP = 1200.0       # J/m3K of air
INFILTRATION = 0.6    # air changes an hour with everything shut
MAX_ACH = 30.0        # beyond this the room is at outdoor temperature anyway
SETPOINT = 26.0       # AC setpoint, BEE default
FAN_SPEED = 0.8       # m/s under a running ceiling fan
KITCHEN_EXHAUST = 10.0  # air changes an hour from a kitchen chimney or exhaust fan

#: Where people are, hour by hour: (rooms, start, end, people, extra watts).
_SCHEDULE = {
    "bed": ((22, 24, 2, 20), (0, 7, 2, 0)),
    "living": ((7, 9, 2, 60), (18, 22, 4, 150)),
    "dining": ((8, 9, 3, 40), (13, 14, 3, 40), (20, 21, 4, 60)),
    "kitchen": ((6, 9, 1, 900), (12, 14, 1, 900), (19, 21, 1, 1100)),
    "study": ((10, 13, 1, 120), (15, 19, 1, 120)),
}
_KIND = {
    RoomType.MASTER_BEDROOM: "bed", RoomType.BEDROOM: "bed", RoomType.GUEST_BEDROOM: "bed",
    RoomType.CHILDREN_BEDROOM: "bed", RoomType.LIVING: "living", RoomType.FAMILY: "living",
    RoomType.DRAWING: "living", RoomType.HOME_THEATRE: "living", RoomType.DINING: "dining",
    RoomType.KITCHEN: "kitchen", RoomType.STUDY: "study", RoomType.HOME_OFFICE: "study",
    RoomType.LIBRARY: "study", RoomType.GYM: "study",
}
PERSON_W = 75.0       # sensible heat of a resting adult


@dataclass(slots=True)
class Options:
    season: str = "summer"      # summer | monsoon | winter: the city's hottest, wettest or coolest month
    month: int | None = None    # 1-12: a month in particular, in place of the season
    windows: str = "open"       # open | night | shut
    fans: bool = True
    cool_roof: bool = False
    chajja: float = 0.6         # overhang depth over windows, metres


@dataclass(slots=True)
class _Window:
    a: tuple[float, float]
    b: tuple[float, float]
    area: float
    height: float


@dataclass(slots=True)
class _Face:
    """The stretch of one outside wall that bounds one room."""

    a: tuple[float, float]      # plan coordinates of its ends
    b: tuple[float, float]
    area: float                 # opaque area, m2
    bearing: float              # outward facing, degrees from north
    windows: list[_Window] = field(default_factory=list)

    @property
    def glass(self) -> float:
        return sum(w.area for w in self.windows)

    @property
    def glass_h(self) -> float:
        return max((w.height for w in self.windows), default=1.5)


@dataclass(slots=True)
class _Zone:
    room: Room
    level: int
    faces: list[_Face] = field(default_factory=list)
    roof: float = 0.0
    ach: float = 0.0
    speed: float = 0.0
    mode: str = "sealed"


#: Other names a client may give, and suburbs that share a city's climate.
ALIASES = {
    "bangalore": "Bengaluru", "bombay": "Mumbai", "navi mumbai": "Mumbai", "thane": "Mumbai",
    "calcutta": "Kolkata", "howrah": "Kolkata", "madras": "Chennai", "secunderabad": "Hyderabad",
    "gurgaon": "Delhi", "gurugram": "Delhi", "noida": "Delhi", "ghaziabad": "Delhi", "faridabad": "Delhi",
    "new delhi": "Delhi", "mohali": "Chandigarh", "panchkula": "Chandigarh", "cochin": "Kochi",
    "ernakulam": "Kochi", "trivandrum": "Thiruvananthapuram", "vizag": "Visakhapatnam", "goa": "Panaji",
    "margao": "Panaji", "gandhinagar": "Ahmedabad", "mysore": "Bengaluru", "mysuru": "Bengaluru",
}


def nearest_city(lat: float, lon: float, locality: str = "") -> str:
    """The climate to use: the city the client named, else the nearest."""
    words = (locality or "").lower()
    for name in CITIES:
        if name.lower() in words:
            return name
    for alias, name in ALIASES.items():
        if alias in words:
            return name
    return min(CITIES, key=lambda c: (CITIES[c][0] - lat) ** 2 + (CITIES[c][1] - lon) ** 2)


def _outdoor(tmax: float, tmin: float, hour: float) -> float:
    h0 = int(hour) % 24
    f = _RANGE[h0] + (_RANGE[(h0 + 1) % 24] - _RANGE[h0]) * (hour - int(hour))
    return tmax - f * (tmax - tmin)


def _irradiance(alt: float, az: float, bearing: float | None, clear: float) -> tuple[float, float]:
    """(beam, diffuse) W/m2 on a surface: a wall facing `bearing`, or the
    roof (None). Meinel clear-sky beam, a tenth of it as sky diffuse."""
    if alt <= 0:
        return 0.0, 0.0
    am = 1 / max(math.sin(math.radians(alt)), 0.05)
    dni = 1353 * 0.7 ** (am ** 0.678) * clear
    dif = 0.1 * 1353 * 0.7 ** (am ** 0.678) + (1 - clear) * 180 * math.sin(math.radians(alt))
    if bearing is None:
        return dni * math.sin(math.radians(alt)), dif
    cos_i = math.cos(math.radians(alt)) * math.cos(math.radians(az - bearing))
    ground = 0.2 * (dni * math.sin(math.radians(alt)) + dif) * 0.5
    return dni * max(cos_i, 0.0), dif * 0.5 + ground


def _shaded(alt: float, az: float, bearing: float, depth: float, height: float) -> float:
    """Share of a window a horizontal chajja of `depth` shades from the beam."""
    rel = math.radians(az - bearing)
    if math.cos(rel) <= 0 or alt <= 0:
        return 1.0
    profile = math.atan(math.tan(math.radians(alt)) / max(math.cos(rel), 1e-3))
    return min(1.0, depth * math.tan(profile) / max(height, 0.3))


def _zones(plan: FloorPlan, wind: Direction, speed: float) -> list[_Zone]:
    from aip.engines.architecture.windflow import solve_level

    north = float(plan.site.north_angle or 0.0)
    zones: list[_Zone] = []
    levels = sorted(plan.levels, key=lambda lv: lv.index)
    for k, level in enumerate(levels):
        above = levels[k + 1] if k + 1 < len(levels) else None
        try:
            flow = {r["id"]: r for r in solve_level(plan, level.index, wind=wind, speed=speed)["rooms"]}
        except (ValueError, IndexError):
            flow = {}
        for r in level.rooms:
            if len(r.polygon) < 3 or r.type.is_outdoor or r.type in (RoomType.SHAFT, RoomType.STAIRCASE):
                continue
            z = _Zone(r, level.index)
            for w in level.walls:
                if w.kind is not WallKind.EXTERIOR or r.id not in w.rooms or w.length < 0.05:
                    continue
                # Only the stretch of the wall along this room: project the
                # room's corners onto the wall and keep the overlap.
                L = w.length
                ux, uy = (w.end.x - w.start.x) / L, (w.end.y - w.start.y) / L
                ts = [(p.x - w.start.x) * ux + (p.y - w.start.y) * uy for p in r.polygon]
                t0, t1 = max(0.0, min(ts)), min(L, max(ts))
                if t1 - t0 < 0.1:
                    continue
                n = w.outward_normal(r.centre)
                at = lambda t: (round(w.start.x + ux * t, 3), round(w.start.y + uy * t, 3))  # noqa: E731
                wins = []
                for o in w.openings:
                    if not (o.kind.is_glazed or o.kind is OpeningKind.SLIDING_DOOR):
                        continue
                    c = o.position * L
                    if t0 <= c <= t1:
                        wins.append(_Window(at(max(t0, c - o.width / 2)), at(min(t1, c + o.width / 2)), o.area, o.height))
                opaque = (t1 - t0) * r.ceiling_height - sum(x.area for x in wins)
                z.faces.append(_Face(at(t0), at(t1), max(opaque, 0.0),
                                     (math.degrees(math.atan2(n.x, n.y)) + north) % 360, wins))
            covered = above is not None and any(o.contains(r.centre) for o in above.rooms if len(o.polygon) >= 3)
            z.roof = 0.0 if covered else r.area
            f = flow.get(r.id, {})
            z.ach, z.speed, z.mode = float(f.get("ach", 0.0)), float(f.get("mean_speed", 0.0)), f.get("mode", "sealed")
            zones.append(z)
    return zones


def _gains(kind: str | None, hour: int) -> float:
    for start, end, people, extra in _SCHEDULE.get(kind or "", ()):
        if start <= hour < end:
            return people * PERSON_W + extra
    return 15.0 if kind else 0.0


def _open(windows: str, hour: int) -> bool:
    return windows == "open" or (windows == "night" and (hour >= 19 or hour < 8))


def _cooling_effect(v: float) -> float:
    """Degrees cooler moving air feels (ASHRAE 55 elevated air speed, approx.)."""
    return 0.0 if v <= 0.15 else min(3.5, 4.2 * (v - 0.15))


#: Inside surface of a wall or the roof slab: how far it sits from the mass
#: toward the sol-air temperature outside (U / inside surface coefficient).
H_IN = 8.0


def _sky(plan: FloorPlan, climate: dict, steps: int) -> list[tuple]:
    """Each time step of the design day: (hour, outdoor air, sun altitude,
    sun azimuth, beam and diffuse on the roof). Shared by every room."""
    lat, lon = plan.site.latitude, plan.site.longitude
    out = []
    for k in range(24 * steps):
        h = k / steps
        sun = sun_position(lat, lon, climate["day"], h + 0.5 / steps)
        rb, rd = _irradiance(sun.altitude, sun.azimuth, None, climate["clear"])
        out.append((h, _outdoor(climate["max"], climate["min"], h), sun.altitude, sun.azimuth, rb, rd))
    return out


def _run(zones: list[_Zone], plan: FloorPlan, opt: Options, climate: dict,
         hold: float | None = None, sky: list[tuple] | None = None, surfaces: bool = False) -> list[dict]:
    """Hourly results per zone. `hold` pins the air at a setpoint (windows
    shut) and returns the cooling it takes instead. With `surfaces`, also the
    temperature of each wall face inside and out, each window, the ceiling."""
    steps = 4                              # quarter-hours
    dt = 3600.0 / steps
    sky = sky or _sky(plan, climate, steps)
    clear = climate["clear"]
    u_roof = U_ROOF_COOL if opt.cool_roof else U_ROOF
    a_roof = ABS_ROOF_COOL if opt.cool_roof else ABS_ROOF
    out = []
    for z in zones:
        r = z.room
        vol = r.area * r.ceiling_height
        a_mass = 2 * r.area + r.perimeter_length * r.ceiling_height * 0.6
        hm = H_MASS * a_mass
        cm = C_MASS * a_mass
        ua_wall = sum(f.area for f in z.faces) * U_WALL
        ua_roof = z.roof * u_roof
        ua_glass = sum(f.glass for f in z.faces) * U_GLASS
        kind = _KIND.get(r.type)
        tm = (climate["max"] + climate["min"]) / 2 + 1.5
        hours = []
        for d in range(4):                 # three days to settle, keep the fourth
            for k, (h, to, alt, az, rb, rd) in enumerate(sky):
                hour = int(h)
                keep = d == 3 and k % steps == 0
                q_glass = q_wall_sol = 0.0
                face_sun = []
                for f in z.faces:
                    beam, dif = _irradiance(alt, az, f.bearing, clear)
                    shade = _shaded(alt, az, f.bearing, opt.chajja, f.glass_h) if f.glass else 0
                    q_glass += f.glass * SHGC * (beam * (1 - shade) + dif)
                    q_wall_sol += f.area * U_WALL * ABS_WALL * (beam + dif) / H_OUT
                    if keep and surfaces:
                        face_sun.append((beam, dif, shade))
                # Night sky: a roof radiates to it and runs a few degrees under the air.
                roof_sol = a_roof * (rb + rd) / H_OUT - (0 if alt > 0 else 3.0)
                q_roof_sol = ua_roof * roof_sol
                q_int = _gains(kind, hour)
                ach = (min(z.ach, MAX_ACH) + INFILTRATION) if (hold is None and _open(opt.windows, hour)) else INFILTRATION
                if kind == "kitchen" and q_int > 500:
                    ach = max(ach, KITCHEN_EXHAUST)      # the chimney or exhaust runs while cooking
                ua_vent = RHO_CP * vol * ach / 3600.0
                # Sun on the glass lands mostly on the floor (the mass) and some in the air.
                to_air = 0.4 * q_glass + q_int
                to_mass = 0.6 * q_glass
                if hold is None:
                    ti = (ua_vent * to + ua_glass * to + hm * tm + to_air) / (ua_vent + ua_glass + hm)
                    load = 0.0
                else:
                    ti = hold
                    load = max(0.0, ua_vent * (to - ti) + ua_glass * (to - ti) + hm * (tm - ti) + to_air)
                q_mass = (ua_wall * (to - tm) + q_wall_sol + ua_roof * (to - tm) + q_roof_sol
                          + hm * (ti - tm) + to_mass)
                if keep:
                    x = {"t": ti, "to": to, "load": load,
                         "parts": {"roof": ua_roof * (to - tm) + q_roof_sol,
                                   "walls": ua_wall * (to - tm) + q_wall_sol,
                                   "windows": q_glass + ua_glass * (to - ti),
                                   "people": q_int, "air": ua_vent * (to - ti)}}
                    if surfaces:
                        faces = []
                        for f, (beam, dif, shade) in zip(z.faces, face_sun):
                            tsa = to + ABS_WALL * (beam + dif) / H_OUT
                            # Glass: halfway between in and out, plus the sun patch it lets in.
                            win = ti + 0.5 * (to - ti) + SHGC * (beam * (1 - shade) + dif) * 0.012
                            faces.append({"in": tm + (tsa - tm) * U_WALL / H_IN,
                                          "out": tsa - (tsa - tm) * U_WALL / H_OUT, "win": win})
                        x["faces"] = faces
                        # The slab stores much of the day's heat itself, so its underside
                        # moves less than a thin wall's would (about 0.6 of U / h_in).
                        x["ceiling"] = tm + (to + roof_sol - tm) * 0.6 * u_roof / H_IN if z.roof else None
                    hours.append(x)
                tm += q_mass * dt / cm
        out.append({"zone": z, "hours": hours})
    return out


def _tons(watts: float) -> float:
    for t in (0.75, 1.0, 1.5, 2.0, 2.5, 3.0):
        if watts * 1.25 <= t * 3517:          # 25% for latent load and pull-down
            return t
    return round(watts * 1.25 / 3517 * 2) / 2


def _where(plan: FloorPlan) -> tuple[str, FloorPlan]:
    """The city whose climate applies, and the plan placed there: the sun and
    the wind follow the named city when the plot has no coordinates of its own."""
    city = nearest_city(plan.site.latitude, plan.site.longitude, plan.site.locality)
    if nearest_city(plan.site.latitude, plan.site.longitude) != city:
        lat, lon = CITIES[city][:2]
        plan = plan.model_copy(update={"site": plan.site.model_copy(update={"latitude": lat, "longitude": lon})})
    return city, plan


def _wind(plan: FloorPlan, climate: dict) -> tuple[Direction, float]:
    summer_w, winter_w = prevailing_wind(plan.site.latitude, plan.site.longitude)
    return (winter_w if climate["winter"] else summer_w), (3.0 if climate["monsoon"] else 2.0)


def _comfort(climate: dict) -> tuple[float, float]:
    """IMAC neutral temperature for the month's mean outdoor air, and the band."""
    return 0.54 * (climate["max"] + climate["min"]) / 2 + 12.83, 2.4


def _feels(z: _Zone, hs: list[dict], opt: Options, neutral: float, band: float) -> list[float]:
    r = z.room
    occupied = {h for h in range(24) if _gains(_KIND.get(r.type), h) > 20} or set(range(24))
    fan = opt.fans and r.type.is_habitable
    out = []
    for h, x in enumerate(hs):
        v = z.speed if _open(opt.windows, h) else 0.05
        # Fans go on when the room is warm, not on a cool winter morning.
        if fan and h in occupied and x["t"] > neutral:
            v = max(v, FAN_SPEED)
        elif x["t"] < neutral - band:
            v = min(v, 0.2)                      # windows pulled to against a cold draught
        out.append(round(x["t"] - _cooling_effect(v), 1))
    return out


def _headline(rooms: list[dict]) -> tuple[float, float]:
    hab = [r for r in rooms if r["habitable"]] or rooms
    return (round(max((r["peak"] for r in hab), default=0), 1),
            round(sum(r["comfort_hours"] for r in hab) / max(len(hab), 1), 1))


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def thermal(plan: FloorPlan, opt: Options | None = None, *, with_fixes: bool = True) -> dict:
    """Each room's temperature through a design day of its city's month, its
    comfort, what heats it, the AC it would need and the temperature of every
    surface (for the thermal-camera view); plus what each fix would change."""
    opt = opt or Options()
    if opt.season not in SEASONS:
        raise ValueError(f"Unknown season '{opt.season}'.")
    city, plan = _where(plan)
    month = opt.month or season_month(city, opt.season)
    if not 1 <= month <= 12:
        raise ValueError(f"Unknown month {month}.")
    climate = month_climate(city, month)
    wind, speed = _wind(plan, climate)
    zones = _zones(plan, wind, speed)
    neutral, band = _comfort(climate)
    sky = _sky(plan, climate, 4)

    def summarise(runs, loads, detail=False):
        rooms = []
        for res, ld in zip(runs, loads):
            z, hs = res["zone"], res["hours"]
            r = z.room
            temps = [round(h["t"], 1) for h in hs]
            feels = _feels(z, hs, opt, neutral, band)
            comfy = sum(1 for f in feels if neutral - band <= f <= neutral + band)
            peak = max(range(24), key=lambda h: temps[h])
            cool_w = max(h["load"] for h in ld["hours"]) if ld else 0.0
            room = {
                "id": r.id, "name": r.display_name(), "type": r.type.value, "level": z.level,
                "polygon": [[round(p.x, 3), round(p.y, 3)] for p in r.polygon],
                "centre": [round(r.centre.x, 3), round(r.centre.y, 3)],
                "area": round(r.area, 1), "habitable": r.type.is_habitable,
                "temps": temps, "feels": feels, "peak": temps[peak], "peak_hour": peak, "low": min(temps),
                "comfort_hours": comfy, "ach": round(min(z.ach, MAX_ACH), 1), "breeze": round(z.speed, 2),
                "ventilation": z.mode, "roof_exposed": z.roof > 0,
                "facing": sorted({_compass(f.bearing) for f in z.faces if f.glass}),
                "at_peak": {k: round(v) for k, v in hs[peak]["parts"].items()}, "cooling_w": round(cool_w),
                "ac_tons": _tons(cool_w) if r.type.is_habitable and cool_w > 0 else 0,
            }
            if detail:
                room["faces"] = [{"a": f.a, "b": f.b, "facing": _compass(f.bearing),
                                  "inside": [_r(h["faces"][i]["in"]) for h in hs],
                                  "outside": [_r(h["faces"][i]["out"]) for h in hs],
                                  "windows": [{"a": w.a, "b": w.b} for w in f.windows],
                                  "glass": [_r(h["faces"][i]["win"]) for h in hs] if f.windows else None}
                                 for i, f in enumerate(z.faces)]
                room["ceiling"] = [_r(h["ceiling"]) for h in hs] if z.roof else None
            rooms.append(room)
        return rooms

    runs = _run(zones, plan, opt, climate, sky=sky, surfaces=True)
    loads = _run(zones, plan, opt, climate, hold=SETPOINT, sky=sky)
    rooms = summarise(runs, loads, detail=True)
    habitable = [r for r in rooms if r["habitable"]] or rooms
    outdoor = [round(_outdoor(climate["max"], climate["min"], h), 1) for h in range(24)]
    sun, ground = [], []
    for h in range(24):
        _h, to, alt, az, rb, rd = sky[h * 4]
        sun.append({"altitude": round(alt, 1), "azimuth": round(az, 1)})
        # Open ground round the house: grass and paving in the sun, cooling to the sky at night.
        ground.append(round(to + 0.4 * (rb + rd) / H_OUT - (0 if alt > 0 else 2.0), 1))

    peak, comfort = _headline(rooms)
    fixes = []
    if with_fixes and zones:
        trials = [("cool_roof", "Cool roof: a white reflective coat and insulation on the terrace", {"cool_roof": True}),
                  ("chajja", "Deeper chajjas: 0.9 m sunshades over the windows", {"chajja": 0.9}),
                  ("night", "Shut windows through the hot day and open them at night", {"windows": "night"}),
                  ("open", "Keep windows open for the breeze", {"windows": "open"}),
                  ("fans", "Ceiling fans in every room", {"fans": True})]
        for key, label, change in trials:
            if all(getattr(opt, k) == v for k, v in change.items()):
                continue
            o2 = replace(opt, **change)
            p2, c2 = _headline(summarise(_run(zones, plan, o2, climate, sky=sky), loads))
            if p2 < peak - 0.15 or c2 > comfort + 0.4:
                fixes.append({"id": key, "label": label, "change": change,
                              "peak_drop": round(peak - p2, 1), "comfort_gain": round(c2 - comfort, 1)})
        fixes.sort(key=lambda f: (-f["peak_drop"], -f["comfort_gain"]))

    hottest = max(habitable, key=lambda r: r["peak"]) if habitable else None
    coolest = min(habitable, key=lambda r: r["peak"]) if habitable else None
    lat, lon, tmaxs, tmins, rhs = CITIES[city]
    return {
        "city": city, "season": opt.season if not opt.month else None, "month": month, "month_name": MONTHS[month - 1],
        "season_name": SEASON_NAMES[opt.season] if not opt.month else MONTHS[month - 1],
        "options": {"windows": opt.windows, "fans": opt.fans, "cool_roof": opt.cool_roof, "chajja": opt.chajja},
        "climate": {"max": climate["max"], "min": climate["min"], "humidity": climate["humidity"],
                    "wind": wind.value, "wind_speed": speed, "sun_share": round(climate["clear"], 2)},
        # The city's averages through the year, for the month strip.
        "normals": [{"month": m + 1, "name": MONTHS[m][:3], "max": tmaxs[m], "min": tmins[m], "humidity": rhs[m]}
                    for m in range(12)],
        "comfort": {"neutral": round(neutral, 1), "low": round(neutral - band, 1), "high": round(neutral + band, 1),
                    "model": "IMAC 2016, naturally ventilated, 90% acceptable"},
        "outdoor": outdoor, "ground": ground, "sun": sun, "north_angle": float(plan.site.north_angle or 0.0),
        "rooms": rooms,
        "summary": {
            "hottest": hottest and {"name": hottest["name"], "peak": hottest["peak"], "hour": hottest["peak_hour"]},
            "coolest": coolest and {"name": coolest["name"], "peak": coolest["peak"]},
            "peak": peak, "comfort_hours": comfort, "outdoor_peak": climate["max"],
            "indoor_over_outdoor": round(peak - climate["max"], 1),
            "ac_tons": round(sum(r["ac_tons"] for r in habitable), 2),
        },
        "fixes": fixes,
    }


def thermal_year(plan: FloorPlan, opt: Options | None = None) -> dict:
    """The house through its city's year: each month's averages beside the
    hottest room and the comfortable hours a day, under the same set-up."""
    opt = opt or Options()
    city, plan = _where(plan)
    zones_for: dict[tuple, list[_Zone]] = {}
    months = []
    for m in range(1, 13):
        climate = month_climate(city, m)
        wind, speed = _wind(plan, climate)
        zones = zones_for.get((wind, speed))
        if zones is None:
            zones = zones_for[(wind, speed)] = _zones(plan, wind, speed)
        neutral, band = _comfort(climate)
        rooms = []
        for res in _run(zones, plan, opt, climate):
            z, hs = res["zone"], res["hours"]
            temps = [h["t"] for h in hs]
            feels = _feels(z, hs, opt, neutral, band)
            rooms.append({"habitable": z.room.type.is_habitable, "peak": round(max(temps), 1),
                          "comfort_hours": sum(1 for f in feels if neutral - band <= f <= neutral + band)})
        peak, comfort = _headline(rooms)
        months.append({"month": m, "name": MONTHS[m - 1][:3], "max": climate["max"], "min": climate["min"],
                       "humidity": climate["humidity"], "indoor_peak": peak, "comfort_hours": comfort})
    return {"city": city, "months": months}


def _compass(bearing: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int(((bearing % 360) + 22.5) // 45) % 8]


__all__ = ["CITIES", "MONTHS", "Options", "SEASONS", "month_climate", "nearest_city", "season_month", "thermal", "thermal_year"]
