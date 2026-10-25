"""Room temperatures through a day: how hot each room gets, when, and why.

The airflow solve says where the breeze goes; this says what it does for the
people inside. Each indoor room is a small thermal model run hour by hour
through a design day of the nearest Indian city's climate:

**Two nodes per room.** The room air, and the thermal mass around it (brick
walls, the RCC floor and ceiling). Heat reaches the mass first - the sun on an
outside wall or the roof is conducted in through it - and the mass hands it to
the air later, which is the afternoon-to-evening lag every Indian home with a
west wall or an exposed roof slab knows: the slab passes the sun on about
4.5 hours late and the brick about 7, each with its swing cut down (CIBSE time
lag and decrement factor). Glass, ventilation and people act on the air directly.

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
#: minimum (C), as IMD publishes them in its 1991-2020 climatological normals
#: for each city's main observatory (Kochi: its airport, the only 1991-2020
#: station), and an approximate daily mean relative humidity (%), which sits
#: above IMD's dry 17:30 reading. For a design decision, not a weather record.
#: city -> (lat, lon, max x12, min x12, RH x12)
CITIES: dict[str, tuple[float, float, tuple, tuple, tuple]] = {
    "Chennai": (13.08, 80.27, (29.3, 30.9, 32.9, 34.5, 37.1, 37.0, 35.3, 34.7, 34.2, 32.1, 29.9, 28.9),
                (21.2, 22.2, 24.2, 26.6, 28.0, 27.5, 26.4, 25.9, 25.6, 24.6, 23.1, 21.9), (70, 68, 68, 70, 64, 58, 63, 66, 70, 77, 79, 75)),
    "Bengaluru": (12.97, 77.59, (28.4, 30.9, 33.4, 34.1, 33.1, 29.7, 28.3, 28.1, 28.6, 28.5, 27.4, 26.9),
                  (16.1, 17.6, 20.2, 22.1, 21.8, 20.6, 20.1, 20.0, 20.0, 19.8, 18.3, 16.4), (60, 52, 48, 55, 64, 75, 79, 79, 76, 74, 71, 66)),
    "Hyderabad": (17.39, 78.49, (28.6, 31.8, 35.2, 37.6, 38.8, 34.4, 30.5, 29.6, 30.1, 30.4, 28.8, 27.8),
                  (13.9, 15.5, 20.3, 24.1, 26.0, 23.9, 22.5, 22.0, 21.7, 20.0, 16.4, 13.1), (55, 46, 39, 39, 39, 62, 73, 76, 74, 66, 60, 58)),
    "Mumbai": (19.08, 72.88, (31.2, 31.7, 33.1, 33.4, 33.7, 32.5, 30.4, 30.2, 30.9, 33.6, 34.1, 32.6),
               (16.9, 18.1, 21.1, 24.2, 27.0, 26.6, 25.5, 25.2, 24.9, 23.9, 21.4, 18.4), (62, 62, 65, 69, 70, 79, 85, 85, 82, 74, 64, 61)),
    "Pune": (18.52, 73.86, (29.8, 32.2, 35.6, 37.9, 37.3, 32.0, 28.3, 27.8, 29.5, 31.5, 30.7, 29.5),
             (11.2, 12.7, 16.0, 19.9, 22.9, 23.1, 22.4, 21.7, 21.0, 19.0, 15.1, 11.8), (56, 48, 42, 47, 57, 75, 83, 84, 79, 66, 58, 57)),
    "Delhi": (28.61, 77.21, (20.1, 24.2, 29.9, 36.5, 39.9, 39.0, 35.6, 34.2, 34.1, 33.0, 28.4, 22.8),
              (7.5, 10.6, 15.6, 21.3, 25.8, 27.7, 27.5, 26.7, 25.0, 19.5, 13.0, 8.4), (75, 66, 55, 39, 38, 51, 72, 76, 70, 59, 62, 71)),
    "Kolkata": (22.57, 88.36, (25.5, 29.4, 33.7, 35.4, 35.5, 34.1, 32.5, 32.3, 32.6, 32.3, 30.2, 26.7),
                (14.3, 18.1, 22.9, 25.7, 26.8, 27.1, 26.7, 26.6, 26.3, 24.4, 20.1, 15.5), (67, 63, 63, 70, 74, 80, 84, 85, 83, 78, 71, 68)),
    "Ahmedabad": (23.02, 72.57, (27.9, 31.0, 35.8, 39.7, 41.8, 39.0, 33.7, 32.3, 33.6, 35.6, 33.1, 29.5),
                  (12.4, 14.6, 19.6, 24.2, 27.3, 27.7, 26.1, 25.3, 24.9, 21.8, 17.2, 13.6), (50, 43, 38, 42, 52, 65, 78, 80, 73, 55, 47, 51)),
    "Jaipur": (26.91, 75.79, (22.5, 26.1, 32.0, 37.6, 41.1, 39.7, 34.8, 32.7, 34.2, 34.1, 29.6, 25.1),
               (8.4, 12.0, 17.4, 22.8, 27.1, 27.9, 26.2, 24.9, 24.0, 20.1, 14.4, 9.9), (55, 46, 35, 26, 30, 46, 68, 74, 65, 45, 45, 52)),
    "Kochi": (9.93, 76.27, (33.7, 34.6, 34.8, 34.4, 33.2, 30.7, 30.0, 30.2, 30.9, 31.8, 32.6, 32.9),
              (20.6, 21.8, 23.9, 24.7, 24.5, 23.5, 23.1, 23.3, 23.3, 23.2, 22.9, 21.8), (70, 72, 73, 75, 77, 86, 88, 86, 84, 83, 79, 72)),
    "Thiruvananthapuram": (8.52, 76.94, (32.4, 32.8, 33.5, 33.3, 32.6, 30.4, 30.1, 30.3, 30.9, 30.9, 31.0, 32.0),
                           (22.3, 22.9, 24.3, 25.1, 25.1, 23.8, 23.3, 23.4, 23.5, 23.5, 23.2, 22.6), (71, 71, 72, 75, 78, 84, 84, 82, 80, 82, 81, 75)),
    "Lucknow": (26.85, 80.95, (21.4, 26.2, 32.2, 38.2, 39.9, 38.3, 34.2, 33.4, 33.4, 32.8, 29.0, 23.6),
                (7.8, 11.0, 15.4, 21.0, 24.8, 26.7, 26.0, 25.6, 24.4, 19.5, 13.3, 8.9), (75, 65, 50, 38, 42, 60, 79, 83, 79, 68, 66, 73)),
    "Bhopal": (23.26, 77.41, (24.9, 28.4, 33.9, 38.7, 41.1, 37.4, 30.9, 28.9, 31.3, 32.7, 29.9, 26.7),
               (10.6, 13.1, 17.6, 22.4, 26.6, 26.0, 23.8, 23.0, 22.2, 19.1, 15.0, 11.2), (52, 42, 30, 25, 26, 55, 80, 85, 75, 55, 50, 52)),
    "Nagpur": (21.15, 79.09, (28.9, 31.9, 36.4, 40.6, 43.1, 38.1, 31.9, 30.8, 32.4, 33.2, 31.3, 29.3),
               (14.1, 16.0, 19.7, 25.1, 28.1, 26.6, 24.4, 23.5, 23.4, 21.4, 17.1, 13.2), (55, 44, 33, 28, 28, 55, 79, 82, 76, 62, 55, 56)),
    "Coimbatore": (11.02, 76.96, (30.9, 33.2, 35.6, 36.4, 35.0, 32.4, 31.5, 31.8, 32.5, 31.7, 30.2, 29.5),
                   (19.2, 20.3, 22.3, 24.1, 24.0, 23.0, 22.4, 22.4, 22.5, 22.3, 21.5, 19.7), (65, 58, 55, 62, 67, 70, 72, 72, 71, 75, 77, 72)),
    "Visakhapatnam": (17.69, 83.22, (28.1, 29.6, 31.2, 32.1, 33.3, 32.8, 31.4, 31.5, 31.6, 31.5, 30.3, 28.7),
                      (20.5, 22.1, 24.6, 26.5, 27.8, 27.4, 26.4, 26.2, 26.0, 25.2, 23.2, 21.0), (69, 71, 74, 76, 74, 72, 76, 76, 78, 74, 68, 67)),
    "Chandigarh": (30.73, 76.78, (18.2, 22.6, 28.0, 34.6, 38.6, 37.7, 34.1, 33.2, 32.9, 32.0, 27.0, 22.1),
                   (7.2, 10.4, 14.7, 20.3, 24.7, 26.7, 26.9, 26.2, 24.4, 18.4, 12.3, 8.0), (75, 68, 58, 40, 36, 48, 75, 80, 72, 60, 65, 74)),
    "Guwahati": (26.14, 91.74, (23.9, 27.0, 30.5, 31.2, 31.8, 32.6, 32.8, 33.2, 32.5, 31.3, 28.5, 25.4),
                 (10.8, 13.0, 16.5, 20.3, 22.9, 25.2, 25.9, 25.8, 24.9, 22.3, 17.2, 12.6), (78, 68, 62, 72, 79, 84, 85, 84, 84, 82, 80, 80)),
    "Panaji": (15.49, 73.83, (32.5, 32.4, 32.6, 33.4, 33.8, 30.9, 29.3, 29.5, 30.2, 32.0, 33.5, 33.1),
               (20.0, 20.6, 23.3, 25.4, 26.3, 24.9, 24.2, 24.2, 24.0, 24.0, 22.7, 20.9), (64, 67, 70, 72, 73, 85, 88, 87, 84, 77, 67, 63)),
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
# How a heavy wall or slab passes the day's outdoor swing on to the inside:
# late by its time lag, and shrunk by its decrement factor (CIBSE Guide A).
LAG_ROOF, DEC_ROOF = 4.5, 0.6   # h, -: 150 mm RCC slab
LAG_WALL, DEC_WALL = 7.0, 0.4   # h, -: 230 mm brick, plastered both sides
SKY_ROOF = 4.0        # K: a flat roof's long-wave loss to the sky (ASHRAE, horizontal)
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
    sill: float = 0.9


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
                        wins.append(_Window(at(max(t0, c - o.width / 2)), at(min(t1, c + o.width / 2)), o.area, o.height,
                                            o.sill_height))
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


def _damped(series: list[float], lag: float, decrement: float) -> list[float]:
    """A periodic day's series as it arrives through a heavy layer: shifted
    `lag` steps later and its swing about the daily mean scaled by `decrement`."""
    n = len(series)
    mean = sum(series) / n
    lo, w = int(lag), lag - int(lag)
    return [mean + decrement * ((1 - w) * series[(k - lo) % n] + w * series[(k - lo - 1) % n] - mean) for k in range(n)]


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
        ua_roof = z.roof * u_roof
        ua_glass = sum(f.glass for f in z.faces) * U_GLASS
        kind = _KIND.get(r.type)
        tm = (climate["max"] + climate["min"]) / 2 + 1.5
        # The sun on each face and the roof through the day, and what reaches
        # the inner mass of it: the sol-air temperature, late and damped.
        face_sun_all = [[_irradiance(alt, az, f.bearing, clear) for (_h, _to, alt, az, _rb, _rd) in sky] for f in z.faces]
        face_sa = [[to + ABS_WALL * (b + df) / H_OUT for (b, df), (_h, to, *_r) in zip(fs, sky)] for fs in face_sun_all]
        roof_sa = [to + a_roof * (rb + rd) / H_OUT - SKY_ROOF for (_h, to, _a, _z, rb, rd) in sky]
        face_te = [_damped(sa, LAG_WALL * steps, DEC_WALL) for sa in face_sa]
        roof_te = _damped(roof_sa, LAG_ROOF * steps, DEC_ROOF)
        hours = []
        for d in range(4):                 # three days to settle, keep the fourth
            for k, (h, to, alt, az, rb, rd) in enumerate(sky):
                hour = int(h)
                keep = d == 3 and k % steps == 0
                q_glass = q_wall_sol = 0.0
                face_sun = []
                for i, f in enumerate(z.faces):
                    beam, dif = face_sun_all[i][k]
                    shade = _shaded(alt, az, f.bearing, opt.chajja, f.glass_h) if f.glass else 0
                    q_glass += f.glass * SHGC * (beam * (1 - shade) + dif)
                    q_wall_sol += f.area * U_WALL * (face_te[i][k] - tm)
                    if keep and surfaces:
                        face_sun.append((beam, dif, shade))
                q_roof_sol = ua_roof * (roof_te[k] - tm)
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
                q_mass = q_wall_sol + q_roof_sol + hm * (ti - tm) + to_mass
                if keep:
                    x = {"t": ti, "to": to, "load": load,
                         "parts": {"roof": q_roof_sol,
                                   "walls": q_wall_sol,
                                   "windows": q_glass + ua_glass * (to - ti),
                                   "people": q_int, "air": ua_vent * (to - ti)}}
                    if surfaces:
                        faces = []
                        for i, (f, (beam, dif, shade)) in enumerate(zip(z.faces, face_sun)):
                            tsa = face_sa[i][k]
                            # Glass: halfway between in and out, plus the sun patch it lets in.
                            win = ti + 0.5 * (to - ti) + SHGC * (beam * (1 - shade) + dif) * 0.012
                            faces.append({"in": tm + (face_te[i][k] - tm) * U_WALL / H_IN,
                                          "out": tsa - (tsa - tm) * U_WALL / H_OUT, "win": win})
                        x["faces"] = faces
                        # The slab's underside follows its damped, late sol-air.
                        x["ceiling"] = tm + (roof_te[k] - tm) * u_roof / H_IN if z.roof else None
                        x["mass"] = tm
                        x["sun"] = (alt, az)
                        x["beam"] = [(b, sh) for b, _d, sh in face_sun]
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


# ---------------------------------------------------------------------------
# Inside a room: the temperature across its floor
# ---------------------------------------------------------------------------

#: Heat sources among the furniture: item id prefix -> (watts, hours in use, spread m).
_SOURCES = {
    "bed": (150.0, set(range(22, 24)) | set(range(0, 7)), 0.7),       # two people asleep
    "sofa": (150.0, set(range(18, 22)), 0.7),                          # the family in the evening
    "tv": (120.0, set(range(19, 23)), 0.45),
    "fridge": (90.0, set(range(24)), 0.4),                             # its back runs warm all day
    "study_desk": (90.0, set(range(10, 13)) | set(range(15, 19)), 0.45),
    "washer": (200.0, {8, 9}, 0.4),
    "dining_table": (225.0, {8, 13, 20}, 0.7),
}
#: How hot a source makes the air it sits in, per watt, at its centre.
_SOURCE_K = 0.008
#: Floor in direct sun: degrees warmer per W/m2 of beam through the glass.
_PATCH_K = 0.016
FIELD_CELL = 0.12


def _stove(room: Room, faces: list[_Face]) -> tuple[float, float] | None:
    """Where the hob is: along the kitchen's longest outside wall (Indian
    kitchens put the counter there, under the window), 0.35 m in."""
    if not faces:
        return None
    f = max(faces, key=lambda f: math.dist(f.a, f.b))
    mx, my = (f.a[0] + f.b[0]) / 2, (f.a[1] + f.b[1]) / 2
    cx, cy = room.centre.x, room.centre.y
    d = math.hypot(cx - mx, cy - my) or 1.0
    return mx + (cx - mx) / d * 0.35, my + (cy - my) / d * 0.35


def _seg_dist(px, py, a, b):
    import numpy as np

    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy or 1e-9
    t = np.clip(((px - ax) * dx + (py - ay) * dy) / L2, 0, 1)
    return np.hypot(px - ax - t * dx, py - ay - t * dy)


def room_fields(plan: FloorPlan, level_index: int, opt: Options | None = None) -> dict:
    """The temperature across the floor of every room on one level, hour by
    hour: what a thermal camera looking down into the room would see.

    Each room's air temperature (from the room model) is shaped by what is
    around it: the inside face of each outside wall and the glass, the sun
    patch the windows throw on the floor at that hour (traced from the sun's
    altitude and bearing through each opening, less what the chajja shades),
    a hot roof slab overhead, the breeze where it runs through the room (from
    the wind solve), and the people and appliances among the furniture."""
    import base64

    import numpy as np
    import shapely
    from shapely.geometry import Polygon

    from aip.engines.architecture.windflow import solve_level

    opt = opt or Options()
    city, plan = _where(plan)
    month = opt.month or season_month(city, opt.season)
    climate = month_climate(city, month)
    wind, speed = _wind(plan, climate)
    zones = [z for z in _zones(plan, wind, speed) if z.level == level_index]
    if not zones:
        return {"level": level_index, "cell": FIELD_CELL, "rooms": []}
    sky = _sky(plan, climate, 4)
    runs = _run(zones, plan, opt, climate, sky=sky, surfaces=True)
    north = float(plan.site.north_angle or 0.0)

    # The breeze: air speed across the floor, from the wind solve.
    flow = solve_level(plan, level_index, wind=wind, speed=speed)
    g = flow["grid"]
    fu = np.frombuffer(base64.b64decode(flow["u"]), dtype="<f2").astype(float).reshape(g["ny"], g["nx"])
    fv = np.frombuffer(base64.b64decode(flow["v"]), dtype="<f2").astype(float).reshape(g["ny"], g["nx"])
    fmag = np.hypot(fu, fv)

    # The furniture, for its outlines and its heat.
    furniture: dict[str, list] = {}
    try:
        from aip.engines.interior.engine import design_interior

        for ri in design_interior(plan, room_ids={z.room.id for z in zones}).rooms:
            furniture[ri.room_id] = list(ri.furniture)
    except Exception:  # noqa: BLE001 - a field without furniture beats no field
        pass

    out = []
    for res in runs:
        z, hs = res["zone"], res["hours"]
        r = z.room
        xs, ys = [p.x for p in r.polygon], [p.y for p in r.polygon]
        x0, y0 = min(xs), min(ys)
        nx = max(2, int(math.ceil((max(xs) - x0) / FIELD_CELL)))
        ny = max(2, int(math.ceil((max(ys) - y0) / FIELD_CELL)))
        px = x0 + (np.arange(nx) + 0.5) * FIELD_CELL
        py = y0 + (np.arange(ny) + 0.5) * FIELD_CELL
        PX, PY = np.meshgrid(px, py)
        inside = shapely.contains_xy(Polygon([(p.x, p.y) for p in r.polygon]).buffer(1e-6), PX, PY)

        # Distances, worked out once: to each outside face and window, and to the room's edge.
        face_d = [_seg_dist(PX, PY, f.a, f.b) for f in z.faces]
        win_d = [[_seg_dist(PX, PY, w.a, w.b) for w in f.windows] for f in z.faces]
        edge_d = np.min([_seg_dist(PX, PY, (r.polygon[i].x, r.polygon[i].y),
                                   (r.polygon[(i + 1) % len(r.polygon)].x, r.polygon[(i + 1) % len(r.polygon)].y))
                         for i in range(len(r.polygon))], axis=0)
        # Breeze speed at each cell.
        gi = np.clip(((PY - g["y0"]) / g["cell"]).astype(int), 0, g["ny"] - 1)
        gj = np.clip(((PX - g["x0"]) / g["cell"]).astype(int), 0, g["nx"] - 1)
        breeze = fmag[gi, gj]

        # Heat sources.
        sources = []
        items = []
        for it in furniture.get(r.id, []):
            fp = it.footprint
            items.append({"id": it.item_id, "name": it.name,
                          "box": [round(fp.min_x, 2), round(fp.min_y, 2), round(fp.max_x, 2), round(fp.max_y, 2)]})
            for key, (watts, hours, spread) in _SOURCES.items():
                if it.item_id.startswith(key):
                    sources.append((it.x, it.y, watts, hours, spread, it.name))
                    break
        if r.type is RoomType.KITCHEN:
            st = _stove(r, z.faces)
            if st:
                cook = {h for h in range(24) if _gains("kitchen", h) > 500}
                sources.append((st[0], st[1], 1400.0, cook, 0.55, "Hob"))
                items.append({"id": "hob", "name": "Hob", "box": [round(st[0] - 0.35, 2), round(st[1] - 0.3, 2),
                                                                 round(st[0] + 0.35, 2), round(st[1] + 0.3, 2)]})
        src_d2 = [(PX - sx) ** 2 + (PY - sy) ** 2 for sx, sy, *_ in sources]

        frames = []
        for hour, x in enumerate(hs):
            ti, to, tm = x["t"], x["to"], x["mass"]
            T = np.full((ny, nx), ti)
            # Interior walls hold near the mass; outside walls at their inside surface.
            T += (tm - ti) * 0.35 * np.exp(-edge_d / 0.3)
            for f, d, fs in zip(z.faces, face_d, x["faces"]):
                T += (fs["in"] - ti) * 0.7 * np.exp(-d / 0.4)
            for f, wds, fs in zip(z.faces, win_d, x["faces"]):
                for wd in wds:
                    T += (fs["win"] - ti) * 0.6 * np.exp(-wd / 0.45)
            if x.get("ceiling") is not None:
                T += (x["ceiling"] - ti) * 0.22
            # Sun patches: trace the beam through each window onto the floor.
            alt, az = x["sun"]
            if alt > 2:
                rad = math.radians(az - north)
                sx, sy = math.sin(rad), math.cos(rad)            # toward the sun, in plan
                cot = 1 / math.tan(math.radians(alt))
                for f, fs, (beam, shade) in zip(z.faces, x["faces"], x["beam"]):
                    if beam <= 5 or not f.windows:
                        continue
                    for w in f.windows:
                        head = w.sill + w.height * (1 - shade)
                        if head <= w.sill + 0.05:
                            continue
                        near, far = w.sill * cot, head * cot
                        ax_, ay_ = w.a
                        ex, ey = w.b[0] - ax_, w.b[1] - ay_
                        # p = a + t*e + u*(-s): solve for t, u at each cell.
                        det = ex * (-sy) - ey * (-sx)
                        if abs(det) < 1e-6:
                            continue
                        qx, qy = PX - ax_, PY - ay_
                        t = (qx * (-sy) - qy * (-sx)) / det
                        u = (ex * qy - ey * qx) / det
                        lit = (t >= 0) & (t <= 1) & (u >= min(near, 0.0)) & (u <= far)
                        # Only light that falls inside the room, beyond the wall.
                        T += np.where(lit & (u > 0.05), beam * SHGC * _PATCH_K * np.exp(-np.maximum(u - far * 0.7, 0) / 1.5), 0)
            # People and appliances.
            for (sx_, sy_, watts, hours, spread, _n), d2 in zip(sources, src_d2):
                if hour in hours:
                    T += watts * _SOURCE_K * np.exp(-d2 / (2 * spread ** 2))
            # The breeze: where air moves, the room runs toward the outdoor air.
            if _open(opt.windows, hour):
                T += (to - T) * np.clip(breeze / max(speed, 0.5) * 1.1, 0, 0.75)
            T = np.where(inside, T, np.nan)
            frames.append(T)
        stack = np.stack(frames)
        lo, hi = float(np.nanmin(stack)), float(np.nanmax(stack))
        enc = np.where(np.isnan(stack), -32768, np.round(stack * 10)).astype("<i2")
        out.append({
            "id": r.id, "name": r.display_name(), "x0": round(x0, 3), "y0": round(y0, 3), "nx": nx, "ny": ny,
            "polygon": [[round(p.x, 3), round(p.y, 3)] for p in r.polygon],
            "temps": base64.b64encode(enc.tobytes()).decode("ascii"), "lo": round(lo, 1), "hi": round(hi, 1),
            "furniture": items,
            "windows": [{"a": w.a, "b": w.b} for f in z.faces for w in f.windows],
            "walls": [{"a": f.a, "b": f.b} for f in z.faces],
            "sources": [{"name": n, "x": round(sx_, 2), "y": round(sy_, 2), "hours": sorted(h)} for sx_, sy_, _w, h, _s, n in sources],
        })
    return {"level": level_index, "cell": FIELD_CELL, "month": month, "city": city, "rooms": out,
            "encoding": "int16 tenths of a degree, [hour][row][col], rows from y0 upward; -32768 outside the room"}


def _compass(bearing: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int(((bearing % 360) + 22.5) // 45) % 8]


__all__ = ["CITIES", "MONTHS", "Options", "SEASONS", "month_climate", "nearest_city", "room_fields", "season_month", "thermal", "thermal_year"]
