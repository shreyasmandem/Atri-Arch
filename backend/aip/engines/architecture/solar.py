"""Solar geometry.

Daylight and thermal performance are the two building-physics questions a
generative design tool most often gets wrong, because "put a window on the south
wall" is climate-specific advice that inverts across the equator and is actively
harmful in the Indian tropics.

Everything here is computed from first principles using the NOAA solar position
algorithm - no API, no dataset download, no cost, and accurate to well under a
degree, which is far finer than any decision the layout optimiser makes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from aip.domain.geometry import Direction, normalise_bearing

# Representative days: the solstices, the equinoxes, and the shoulder months.
# Sampling eight days x hourly is enough to characterise annual exposure to the
# precision the optimiser needs, and it runs in microseconds.
REPRESENTATIVE_DAYS: tuple[int, ...] = (15, 46, 80, 111, 172, 213, 266, 355)


@dataclass(frozen=True, slots=True)
class SunPosition:
    altitude: float      # degrees above horizon
    azimuth: float       # degrees clockwise from north
    day_of_year: int
    hour: float

    @property
    def is_up(self) -> bool:
        return self.altitude > 0.0


def solar_declination(day_of_year: int) -> float:
    """Declination in degrees (Cooper's equation, +/-0.5 deg of NOAA)."""
    return 23.45 * math.sin(math.radians(360.0 * (284 + day_of_year) / 365.0))


def equation_of_time(day_of_year: int) -> float:
    """Minutes of correction between apparent and mean solar time."""
    b = math.radians(360.0 * (day_of_year - 81) / 364.0)
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def sun_position(latitude: float, longitude: float, day_of_year: int, local_hour: float,
                 timezone_offset: float | None = None) -> SunPosition:
    """Sun altitude and azimuth for a place and moment.

    `timezone_offset` defaults to the nearest standard meridian, which is right
    for India (UTC+5:30, meridian 82.5E) and adequate everywhere else.
    """
    if timezone_offset is None:
        timezone_offset = round(longitude / 15.0 * 2) / 2.0

    standard_meridian = 15.0 * timezone_offset
    time_correction = 4.0 * (longitude - standard_meridian) + equation_of_time(day_of_year)
    solar_time = local_hour + time_correction / 60.0
    hour_angle = math.radians(15.0 * (solar_time - 12.0))

    lat = math.radians(latitude)
    dec = math.radians(solar_declination(day_of_year))

    sin_alt = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.degrees(math.asin(sin_alt))

    cos_alt = math.cos(math.asin(sin_alt))
    if abs(cos_alt) < 1e-9:
        azimuth = 180.0
    else:
        cos_az = (math.sin(dec) - math.sin(lat) * sin_alt) / (math.cos(lat) * cos_alt)
        cos_az = max(-1.0, min(1.0, cos_az))
        azimuth = math.degrees(math.acos(cos_az))
        if math.sin(hour_angle) > 0:      # afternoon
            azimuth = 360.0 - azimuth

    return SunPosition(altitude=altitude, azimuth=normalise_bearing(azimuth),
                       day_of_year=day_of_year, hour=local_hour)


@lru_cache(maxsize=256)
def annual_orientation_exposure(latitude: float, longitude: float) -> dict[Direction, float]:
    """Relative annual solar energy on a vertical surface, by orientation.

    Returns values normalised to [0, 1] across the 16 compass sectors. The result
    correctly captures that in the northern tropics a north wall receives useful
    diffuse light with little heat gain, while west walls take a punishing
    late-afternoon load - the single most important orientation fact for Indian
    residential design, and the one generic models most reliably miss.
    """
    totals: dict[Direction, float] = {d: 0.0 for d in Direction if d is not Direction.CENTRE}

    for day in REPRESENTATIVE_DAYS:
        for step in range(int(4.5 * 4), int(19.5 * 4)):   # 04:30-19:30 in 15 min steps
            hour = step / 4.0
            sun = sun_position(latitude, longitude, day, hour)
            if not sun.is_up:
                continue
            # Clear-sky beam irradiance with a simple air-mass attenuation.
            zenith = 90.0 - sun.altitude
            air_mass = 1.0 / max(0.05, math.cos(math.radians(min(zenith, 89.0))))
            beam = 1367.0 * 0.7 ** (air_mass**0.678)
            for direction in totals:
                incidence = math.cos(math.radians(sun.altitude)) * math.cos(
                    math.radians(sun.azimuth - direction.bearing)
                )
                if incidence > 0:
                    totals[direction] += beam * incidence

    peak = max(totals.values()) or 1.0
    return {d: round(v / peak, 4) for d, v in totals.items()}


@lru_cache(maxsize=256)
def daylight_quality_by_orientation(latitude: float) -> dict[Direction, float]:
    """Desirability of each orientation for *daylight* rather than raw energy.

    Distinct from `annual_orientation_exposure` because good daylight means
    steady, glare-free illuminance - not maximum insolation. In the tropics the
    north face is the premium daylight orientation; the west face is the worst,
    delivering low-angle glare and peak cooling load simultaneously.
    """
    tropical = abs(latitude) < 30.0
    if latitude >= 0:
        base = {
            Direction.N: 1.00 if tropical else 0.55,
            Direction.NNE: 0.96 if tropical else 0.58,
            Direction.NE: 0.92 if tropical else 0.66,
            Direction.ENE: 0.86,
            Direction.E: 0.84,
            Direction.ESE: 0.76,
            Direction.SE: 0.72 if tropical else 0.88,
            Direction.SSE: 0.66 if tropical else 0.94,
            Direction.S: 0.60 if tropical else 1.00,
            Direction.SSW: 0.52 if tropical else 0.92,
            Direction.SW: 0.42 if tropical else 0.80,
            Direction.WSW: 0.34,
            Direction.W: 0.30,
            Direction.WNW: 0.38,
            Direction.NW: 0.52,
            Direction.NNW: 0.74,
        }
    else:
        # Mirror north/south for the southern hemisphere.
        northern = daylight_quality_by_orientation(abs(latitude))
        base = {d: northern[_mirror_ns(d)] for d in northern}
    return base


def _mirror_ns(direction: Direction) -> Direction:
    mapping = {
        Direction.N: Direction.S, Direction.NNE: Direction.SSE, Direction.NE: Direction.SE,
        Direction.ENE: Direction.ESE, Direction.E: Direction.E, Direction.ESE: Direction.ENE,
        Direction.SE: Direction.NE, Direction.SSE: Direction.NNE, Direction.S: Direction.N,
        Direction.SSW: Direction.NNW, Direction.SW: Direction.NW, Direction.WSW: Direction.WNW,
        Direction.W: Direction.W, Direction.WNW: Direction.WSW, Direction.NW: Direction.SW,
        Direction.NNW: Direction.SSW,
    }
    return mapping.get(direction, direction)


def average_daylight_factor(
    glazed_area: float,
    floor_area: float,
    *,
    visible_sky_angle: float = 65.0,
    glass_transmittance: float = 0.72,
    maintenance_factor: float = 0.9,
    mean_surface_reflectance: float = 0.5,
) -> float:
    """BRE average daylight factor, as a percentage.

        DF = (T x A_w x theta x M) / (A_total x (1 - R^2))

    A residential living space is generally considered well daylit above 2%,
    adequate above 1%, and gloomy below that - the thresholds the critic uses.
    """
    if floor_area <= 0 or glazed_area <= 0:
        return 0.0
    denominator = floor_area * (1 - mean_surface_reflectance**2)
    if denominator <= 0:
        return 0.0
    df = (glass_transmittance * glazed_area * visible_sky_angle * maintenance_factor) / denominator
    return round(df, 3)


def overheating_risk(direction: Direction, latitude: float, shading_factor: float = 0.0) -> float:
    """Risk in [0, 1] that a glazed opening on this orientation overheats.

    `shading_factor` is the fraction of the opening protected by an overhang,
    fin, chajja or verandah. West glazing is penalised hardest because low-angle
    afternoon sun is the case a horizontal overhang cannot fix.
    """
    exposure = annual_orientation_exposure(latitude, 78.0)
    raw = exposure.get(direction, 0.5)
    west_penalty = {
        Direction.W: 0.30, Direction.WSW: 0.26, Direction.WNW: 0.22,
        Direction.SW: 0.18, Direction.NW: 0.12,
    }.get(direction, 0.0)
    if latitude < 0:
        west_penalty = {
            Direction.W: 0.30, Direction.WNW: 0.26, Direction.WSW: 0.22,
            Direction.NW: 0.18, Direction.SW: 0.12,
        }.get(direction, 0.0)
    # A horizontal overhang is far more effective against high-angle sun.
    effective_shading = shading_factor * (0.4 if west_penalty > 0.15 else 0.95)
    return round(max(0.0, min(1.0, (raw + west_penalty) * (1 - effective_shading))), 4)


def recommended_overhang_depth(
    opening_height: float, direction: Direction, latitude: float
) -> float:
    """Chajja / overhang projection that shades an opening at summer noon.

    Sizing to the summer solstice noon altitude is the standard rule of thumb for
    tropical residential work, and it is what the generator uses when it places
    sun-shades automatically.
    """
    summer_day = 172 if latitude >= 0 else 355
    noon = sun_position(latitude, 78.0, summer_day, 12.0)
    altitude = max(15.0, noon.altitude)
    depth = opening_height / math.tan(math.radians(altitude))

    facing = abs(((direction.bearing - (180.0 if latitude >= 0 else 0.0)) + 180) % 360 - 180)
    if facing > 75:      # east/west facing: overhangs help far less
        depth *= 0.55
    return round(max(0.3, min(depth, 1.8)), 2)


def prevailing_wind(latitude: float, longitude: float) -> tuple[Direction, Direction]:
    """Coarse (summer, winter) prevailing wind directions.

    Derived from large-scale circulation: the Indian subcontinent's south-west
    summer monsoon and north-east winter retreat dominate residential ventilation
    strategy. Good enough to orient openings; a site-specific wind rose can be
    supplied via site metadata to override it.
    """
    if 5.0 <= latitude <= 37.0 and 65.0 <= longitude <= 98.0:
        return Direction.SW, Direction.NE
    if latitude >= 0:
        return Direction.SW, Direction.NW
    return Direction.NW, Direction.SE


def sun_path_polyline(latitude: float, longitude: float, day_of_year: int) -> list[tuple[float, float]]:
    """(azimuth, altitude) samples for drawing a sun-path diagram in the UI."""
    points: list[tuple[float, float]] = []
    for step in range(0, 24 * 4):
        hour = step / 4.0
        sun = sun_position(latitude, longitude, day_of_year, hour)
        if sun.is_up:
            points.append((round(sun.azimuth, 2), round(sun.altitude, 2)))
    return points


def daylight_hours(latitude: float, day_of_year: int) -> float:
    """Hours between sunrise and sunset."""
    dec = math.radians(solar_declination(day_of_year))
    lat = math.radians(latitude)
    cos_omega = -math.tan(lat) * math.tan(dec)
    if cos_omega >= 1.0:
        return 0.0
    if cos_omega <= -1.0:
        return 24.0
    return round(2 * math.degrees(math.acos(cos_omega)) / 15.0, 2)
