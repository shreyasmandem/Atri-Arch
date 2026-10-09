"""Analytical performance metrics for a floorplan.

These functions are the platform's ground truth. They are deterministic, exact,
instantaneous and free - no model is consulted - which is what lets the critic
committee anchor a language model's aesthetic judgement to physical reality.

Each analysis returns per-room detail alongside an aggregate score in [0, 1] and
a list of located findings, so a low score can always be traced to the specific
room or wall responsible.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass, field

from aip.agents.base import Evidence, EvidenceKind, Finding, Severity
from aip.domain.brief import ClientBrief
from aip.domain.geometry import (
    Direction,
    Vec2,
    bearing_to_direction,
    distance_point_to_segment,
    segments_intersect,
)
from aip.domain.plan import FloorPlan, OpeningKind, Room, RoomType, Wall
from aip.engines.architecture.solar import (
    average_daylight_factor,
    daylight_quality_by_orientation,
    overheating_risk,
    prevailing_wind,
    recommended_overhang_depth,
)


@dataclass(slots=True)
class MetricReport:
    """Uniform result shape for every analysis."""

    axis: str
    score: float
    per_room: dict[str, float] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    detail: dict[str, object] = field(default_factory=dict)
    summary: str = ""

    def worst_rooms(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(self.per_room.items(), key=lambda kv: kv[1])[:n]


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _room_walls(plan: FloorPlan, room: Room) -> list[Wall]:
    level = plan.level_at(room.level)
    if level is None:
        return []
    return [w for w in level.walls if room.id in w.rooms]


def _opening_direction(plan: FloorPlan, wall: Wall) -> Direction:
    """Compass direction an opening in this wall looks out toward."""
    normal = wall.outward_normal(plan.centre)
    bearing = math.degrees(math.atan2(normal.x, normal.y)) + plan.site.north_angle
    return bearing_to_direction(bearing)


# ---------------------------------------------------------------------------
# Natural light
# ---------------------------------------------------------------------------


def daylight_analysis(plan: FloorPlan) -> MetricReport:
    """Average daylight factor per habitable room, orientation-corrected."""
    lat = plan.site.latitude
    quality = daylight_quality_by_orientation(lat)
    per_room: dict[str, float] = {}
    findings: list[Finding] = []
    evidence: list[Evidence] = []
    detail: dict[str, object] = {}

    habitable = [r for r in plan.all_rooms if r.type.is_habitable]
    if not habitable:
        return MetricReport("daylight", 0.5, summary="No habitable rooms to assess.")

    for room in habitable:
        walls = _room_walls(plan, room)
        glazed = 0.0
        weighted_quality = 0.0
        orientations: dict[str, float] = {}
        overheat = 0.0

        for wall in walls:
            direction = _opening_direction(plan, wall)
            for opening in wall.openings:
                if not opening.kind.is_glazed:
                    continue
                area = opening.area
                glazed += area
                q = quality.get(direction, 0.6)
                weighted_quality += area * q
                orientations[direction.value] = orientations.get(direction.value, 0.0) + area
                shading = float(room.metadata.get("shading_factor", 0.0))
                overheat = max(overheat, overheating_risk(direction, lat, shading) * min(1.0, area / 2.0))

        df = average_daylight_factor(glazed, room.area)
        orientation_score = (weighted_quality / glazed) if glazed > 0 else 0.0

        # 2% average daylight factor is the well-lit benchmark for living space.
        adequacy = _clamp(df / 2.0)
        score = _clamp(0.62 * adequacy + 0.38 * orientation_score - 0.25 * overheat)
        per_room[room.id] = round(score, 4)
        detail[room.id] = {
            "name": room.display_name(),
            "glazed_area_m2": round(glazed, 3),
            "window_to_floor_ratio": round(glazed / room.area, 4) if room.area else 0.0,
            "average_daylight_factor_pct": df,
            "orientation_quality": round(orientation_score, 3),
            "overheating_risk": round(overheat, 3),
            "orientations": orientations,
        }

        wfr = glazed / room.area if room.area else 0.0
        if glazed <= 0:
            findings.append(
                Finding(
                    code="DAY.NO_GLAZING",
                    severity=Severity.CRITICAL if room.type.is_habitable else Severity.MAJOR,
                    message=f"{room.display_name()} is a habitable room with no window.",
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="glazed_area_m2",
                    actual=0.0,
                    expected=round(room.area * 0.10, 2),
                    remedy="Add glazing of at least 10% of the floor area on an external wall.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.STANDARD,
                            source="NBC of India 2016, Part 3",
                            detail="Habitable rooms require openings of not less than one-tenth of the floor area.",
                            locator=room.id,
                        )
                    ],
                )
            )
        elif wfr < 0.10:
            findings.append(
                Finding(
                    code="DAY.UNDER_GLAZED",
                    severity=Severity.MAJOR,
                    message=(
                        f"{room.display_name()} is under-glazed: window area is "
                        f"{wfr:.1%} of floor area against the 10% statutory minimum."
                    ),
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="window_to_floor_ratio",
                    actual=round(wfr, 4),
                    expected=0.10,
                    remedy=f"Increase glazing by about {max(0.0, room.area * 0.10 - glazed):.2f} m2.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.STANDARD,
                            source="NBC of India 2016, Part 3, Cl. 4.2",
                            locator=room.id,
                        )
                    ],
                )
            )
        elif df < 1.0:
            findings.append(
                Finding(
                    code="DAY.LOW_DF",
                    severity=Severity.MODERATE,
                    message=(
                        f"{room.display_name()} has an average daylight factor of "
                        f"{df:.2f}%, below the 2% benchmark for a well-lit room."
                    ),
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="average_daylight_factor_pct",
                    actual=df,
                    expected=2.0,
                    remedy="Enlarge or reposition openings, or borrow light through a courtyard or clerestory.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.COMPUTED,
                            source="BRE average daylight factor",
                            detail=f"DF computed from {glazed:.2f} m2 glazing over {room.area:.1f} m2 floor.",
                            locator=room.id,
                        )
                    ],
                )
            )

        if overheat > 0.55:
            worst = max(orientations, key=lambda k: orientations[k]) if orientations else "W"
            opening_height = max(
                (o.height for w in walls for o in w.openings if o.kind.is_glazed), default=1.5
            )
            depth = recommended_overhang_depth(opening_height, Direction(worst), lat)
            findings.append(
                Finding(
                    code="DAY.OVERHEAT",
                    severity=Severity.MODERATE,
                    message=(
                        f"{room.display_name()} carries a high solar gain risk from "
                        f"{worst}-facing glazing."
                    ),
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="overheating_risk",
                    actual=round(overheat, 3),
                    expected=0.4,
                    remedy=f"Add a {depth:.2f} m projection, deep reveals or vertical fins to the {worst} glazing.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.COMPUTED,
                            source="Clear-sky irradiance model",
                            detail=f"Latitude {lat:.2f}, orientation {worst}.",
                            locator=room.id,
                        )
                    ],
                )
            )

    score = sum(per_room.values()) / len(per_room)
    evidence.append(
        Evidence(
            kind=EvidenceKind.COMPUTED,
            source="Solar position model (NOAA)",
            detail=(
                f"Orientation preferences computed for latitude {lat:.2f}. "
                f"Best daylight orientation: "
                f"{max(quality, key=lambda d: quality[d]).value}."
            ),
            value=round(score, 3),
        )
    )
    return MetricReport(
        axis="daylight",
        score=round(score, 4),
        per_room=per_room,
        findings=findings,
        evidence=evidence,
        detail=detail,
        summary=(
            f"Mean daylight score {score:.2f} across {len(per_room)} habitable rooms; "
            f"{sum(1 for f in findings if f.severity.weight >= 0.75)} serious issue(s)."
        ),
    )


# ---------------------------------------------------------------------------
# Ventilation
# ---------------------------------------------------------------------------


#: Fraction of an aperture that actually opens, by opening type. Frame and
#: track losses mean the hole in the wall always exceeds the free area, and
#: getting this wrong is the difference between a compliant and a stuffy room.
OPENABLE_FRACTION: dict[OpeningKind, float] = {
    OpeningKind.WINDOW: 0.75,            # casement / top-hung
    OpeningKind.FRENCH_WINDOW: 0.80,
    OpeningKind.SLIDING_DOOR: 0.50,      # two-track sliders expose half
    OpeningKind.VENTILATOR: 0.60,
    OpeningKind.SKYLIGHT: 0.50,
}


def ventilation_analysis(plan: FloorPlan) -> MetricReport:
    """Cross-ventilation potential, openable area and wind alignment.

    Cross ventilation - openings on two differently-oriented walls so air can
    actually traverse the room - is worth more in a hot-humid climate than any
    amount of glazing on a single wall, so it dominates the score.
    """
    per_room: dict[str, float] = {}
    findings: list[Finding] = []
    detail: dict[str, object] = {}
    summer_wind, winter_wind = prevailing_wind(plan.site.latitude, plan.site.longitude)

    rooms = [r for r in plan.all_rooms if r.type.is_habitable or r.type.is_wet]
    if not rooms:
        return MetricReport("ventilation", 0.5, summary="No rooms requiring ventilation.")

    for room in rooms:
        walls = _room_walls(plan, room)
        openable = 0.0
        directions: set[Direction] = set()
        wind_alignment = 0.0
        internal_doors = 0
        external_openings = 0
        face_areas: dict[Direction, float] = {}

        for wall in walls:
            direction = _opening_direction(plan, wall)
            for opening in wall.openings:
                if opening.kind.is_door and opening.kind is not OpeningKind.SLIDING_DOOR:
                    internal_doors += 1
                    continue
                if opening.kind is OpeningKind.SKYLIGHT:
                    openable += opening.area * 0.5    # stack effect only
                    continue
                if not (opening.kind.is_glazed or opening.kind is OpeningKind.SLIDING_DOOR):
                    continue
                area = opening.area * OPENABLE_FRACTION.get(opening.kind, 0.6)
                openable += area
                face_areas[direction] = face_areas.get(direction, 0.0) + area
                external_openings += 1
                directions.add(direction)
                delta = abs(((direction.bearing - summer_wind.bearing) + 180) % 360 - 180)
                wind_alignment = max(wind_alignment, math.cos(math.radians(min(delta, 90))))

        # Inlet/outlet balance
        if len(face_areas) >= 2:
            sorted_areas = sorted(face_areas.values(), reverse=True)
            area_balance = sorted_areas[-1] / sorted_areas[0] if sorted_areas[0] > 0 else 0.0
        else:
            area_balance = 1.0  # single-sided, balance not applicable

        # Cross ventilation needs an inlet and an outlet on meaningfully
        # different pressure faces. Two opposed external openings is the ideal.
        # A single external opening plus an internal door still ventilates -
        # the escape path runs through the rest of the house - but markedly less
        # effectively, which is why it scores well below a true cross-flow.
        opposing = _has_opposing_pair(directions)
        has_external = bool(directions)
        if opposing:
            cross = 1.0
        elif len(directions) >= 2:
            cross = 0.6
        elif has_external and internal_doors:
            cross = 0.45
        else:
            cross = 0.0

        # NBC: aggregate openable area not less than one-sixth of the floor area.
        ratio = openable / room.area if room.area else 0.0
        adequacy = _clamp(ratio / (1 / 6))

        # How far the air actually reaches. Openable area governs how much air
        # can pass; the mode and the room's depth govern whether it reaches the
        # back wall. A deep room with a single window has a stagnant zone no
        # amount of extra glazing on that one wall will clear.
        mode = ventilation_mode(directions, external_openings)
        depth = _flow_depth(room, directions)
        reach = VENTILATION_DEPTH_LIMIT[mode] * room.ceiling_height
        stagnant = _clamp(1.0 - reach / depth) if depth > 1e-6 else 0.0
        reach_score = 1.0 - stagnant

        score = _clamp(
            0.30 * cross + 0.25 * adequacy + 0.13 * wind_alignment
            + 0.22 * reach_score + 0.10 * area_balance
        )
        per_room[room.id] = round(score, 4)
        has_skylight = any(
            o.kind is OpeningKind.SKYLIGHT
            for w in walls for o in w.openings
        )
        detail[room.id] = {
            "name": room.display_name(),
            "openable_area_m2": round(openable, 3),
            "openable_ratio": round(ratio, 4),
            "orientations": sorted(d.value for d in directions),
            "cross_ventilated": bool(opposing),
            "ventilation_mode": mode,
            "flow_depth_m": round(depth, 2),
            "effective_reach_m": round(reach, 2),
            "stagnant_fraction": round(stagnant, 3),
            "wind_alignment": round(wind_alignment, 3),
            "inlet_area_m2": round(sorted(face_areas.values(), reverse=True)[0], 3) if face_areas else 0.0,
            "outlet_area_m2": round(sorted(face_areas.values(), reverse=True)[-1], 3) if len(face_areas) >= 2 else 0.0,
            "area_balance": round(area_balance, 3),
            "has_skylight": has_skylight,
            "estimated_ach": round(_estimate_ach(
                openable, room.volume, opposing, wind_alignment,
                ceiling_height=room.ceiling_height, has_skylight=has_skylight,
            ), 2),
        }

        if openable <= 0:
            findings.append(
                Finding(
                    code="VENT.NONE",
                    severity=Severity.CRITICAL if room.type.is_habitable else Severity.MAJOR,
                    message=f"{room.display_name()} has no openable ventilation.",
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="openable_area_m2",
                    actual=0.0,
                    expected=round(room.area / 6, 2),
                    remedy="Add an openable window or, for internal wet areas, a mechanical extract.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.STANDARD,
                            source="NBC of India 2016, Part 8",
                            detail="Aggregate openable area not less than one-sixth of floor area.",
                            locator=room.id,
                        )
                    ],
                )
            )
        elif ratio < 1 / 6 - 1e-4 and room.type.is_habitable:
            deficit = max(0.0, room.area / 6 - openable)
            # A deficit that rounds to zero is a floating-point artefact, not a
            # defect worth reporting - and "add about 0.00 m2" reads as a bug.
            if deficit >= 0.05:
                findings.append(
                    Finding(
                        code="VENT.INSUFFICIENT",
                        severity=Severity.MAJOR if deficit > 0.4 else Severity.MINOR,
                        message=(
                            f"{room.display_name()} has {ratio:.1%} openable area against "
                            f"the 16.7% requirement."
                        ),
                        target_id=room.id,
                        target_label=room.display_name(),
                        metric="openable_ratio",
                        actual=round(ratio, 4),
                        expected=round(1 / 6, 4),
                        remedy=f"Add about {deficit:.2f} m2 of openable area.",
                        evidence=[
                            Evidence(
                                kind=EvidenceKind.STANDARD,
                                source="NBC of India 2016, Part 8",
                                locator=room.id,
                            )
                        ],
                    )
                )
        elif not opposing and room.type.is_habitable:
            findings.append(
                Finding(
                    code="VENT.NO_CROSS",
                    severity=Severity.MODERATE,
                    message=f"{room.display_name()} lacks cross ventilation; openings are on one side only.",
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="cross_ventilated",
                    actual="no",
                    expected="yes",
                    remedy=(
                        f"Add an opening on an opposite or adjacent wall, ideally facing "
                        f"{summer_wind.value} to catch the prevailing summer wind."
                    ),
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.COMPUTED,
                            source="Opening orientation analysis",
                            detail=f"Openings found on: {sorted(d.value for d in directions) or 'none'}.",
                            locator=room.id,
                        )
                    ],
                )
            )

        # Area is not reach. A room can satisfy the one-sixth openable-area rule
        # and still have a dead zone at the back, because the code governs how
        # much opening there is and says nothing about where it is.
        if stagnant > 0.15 and room.type.is_habitable:
            dead = depth - reach
            findings.append(
                Finding(
                    code="VENT.REACH",
                    severity=Severity.MAJOR if stagnant > 0.35 else Severity.MINOR,
                    message=(
                        f"{room.display_name()} is {depth:.1f} m deep but "
                        f"{mode.replace('_', ' ')} ventilation carries air only about "
                        f"{reach:.1f} m in; the far {dead:.1f} m recirculates rather "
                        f"than flushes."
                    ),
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="stagnant_fraction",
                    actual=f"{stagnant:.0%} of depth",
                    expected="under 15%",
                    remedy=(
                        "Add an opening on a different face so the air has a path "
                        "through. On a single wall, more glazing does not buy more "
                        "depth - it enlarges the same recirculation cell."
                    ),
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.COMPUTED,
                            source="BS 5925 / CIBSE AM10 effective-depth rule",
                            detail=(
                                f"{mode.replace('_', ' ')} ventilation reaches "
                                f"{VENTILATION_DEPTH_LIMIT[mode]:.1f} x the "
                                f"{room.ceiling_height:.2f} m ceiling height."
                            ),
                            locator=room.id,
                        )
                    ],
                )
            )

    score = sum(per_room.values()) / len(per_room)
    return MetricReport(
        axis="ventilation",
        score=round(score, 4),
        per_room=per_room,
        findings=findings,
        evidence=[
            Evidence(
                kind=EvidenceKind.COMPUTED,
                source="Prevailing wind model",
                detail=f"Summer wind from {summer_wind.value}, winter from {winter_wind.value}.",
                value=round(score, 3),
            )
        ],
        detail=detail,
        summary=(
            f"Mean ventilation score {score:.2f}; "
            f"{sum(1 for d in detail.values() if isinstance(d, dict) and d.get('cross_ventilated'))}"
            f"/{len(per_room)} rooms cross-ventilated."
        ),
    )


#: Effective ventilation depth, as a multiple of floor-to-ceiling height.
#:
#: From BS 5925 and CIBSE AM10. The numbers encode what the CFD shows: with one
#: opening, air enters and leaves through the same aperture, so a recirculation
#: cell forms and the far end of the room is never flushed. Give the air a second
#: opening on a different pressure face and the path becomes a through-flow that
#: reaches more than twice as far.
#:
#: This is why a room can satisfy the one-sixth openable-area rule and still be
#: stuffy: the code governs how *much* opening there is, and says nothing about
#: where it is. Area is necessary and not sufficient.
VENTILATION_DEPTH_LIMIT: dict[str, float] = {
    "cross": 5.0,                  # opposed openings, clear path through
    "single_sided_double": 2.5,    # two openings, same face, separated
    "single_sided": 2.0,           # one opening: enters and leaves the same way
    "none": 0.0,
}


def ventilation_mode(directions: set[Direction], opening_count: int) -> str:
    """Classify how a room ventilates, which fixes how deep it can be."""
    if not directions or opening_count == 0:
        return "none"
    if _has_opposing_pair(directions):
        return "cross"
    if opening_count >= 2:
        return "single_sided_double"
    return "single_sided"


def _flow_depth(room: Room, directions: set[Direction]) -> float:
    """Room dimension along the direction the air has to travel.

    For a through-flow that is the span between the two opposed faces; for
    single-sided it is how far the room extends away from its only opening. Both
    reduce to a bounding-box dimension chosen by the axis the openings sit on.
    """
    box = room.bbox
    if not directions:
        return max(box.width, box.height)
    # North/south facing openings drive flow along Y; east/west along X. A
    # direction is north-south facing when its bearing is nearer the N-S axis
    # than the E-W one, which is exactly a comparison of |cos| against |sin|.
    north_south = sum(
        1 for d in directions
        if abs(math.cos(math.radians(d.bearing))) >= abs(math.sin(math.radians(d.bearing)))
    )
    east_west = len(directions) - north_south
    return box.height if north_south >= east_west else box.width


def _has_opposing_pair(directions: set[Direction]) -> bool:
    """True when two openings face sufficiently different ways to drive flow."""
    bearings = [d.bearing for d in directions]
    for i, a in enumerate(bearings):
        for b in bearings[i + 1 :]:
            delta = abs(((a - b) + 180) % 360 - 180)
            if delta >= 80:
                return True
    return False


def _estimate_ach(
    openable: float, volume: float, cross: bool, wind_alignment: float,
    ceiling_height: float = 3.0, has_skylight: bool = False,
) -> float:
    """Rough air changes per hour from wind-driven and stack-effect flow.

    Uses Q = C x A x V with an empirical discharge coefficient. Stack effect
    adds buoyancy-driven ventilation for tall rooms and skylights.
    Indicative only - enough to distinguish a stuffy room from a breezy one.
    """
    if volume <= 0 or openable <= 0:
        return 0.0
    wind_speed = 2.2  # m/s, typical urban residential
    coefficient = 0.6 if cross else 0.25
    flow = coefficient * openable * wind_speed * (0.55 + 0.45 * wind_alignment)
    wind_ach = (flow * 3600) / volume

    # Stack effect: buoyancy-driven flow from temperature difference
    delta_t = 3.0  # K, typical indoor/outdoor ΔT
    stack_height = ceiling_height * (1.4 if has_skylight else 0.7)
    stack_velocity = 0.4 * (9.81 * stack_height * delta_t / 293.0) ** 0.5
    stack_flow = 0.25 * openable * stack_velocity
    stack_ach = (stack_flow * 3600) / volume

    return wind_ach + stack_ach


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def privacy_analysis(plan: FloorPlan) -> MetricReport:
    """Visual and topological privacy for private rooms.

    Combines three ideas architects use intuitively:

    * **Topological depth** - how many thresholds separate the entrance from a
      bedroom. Depth 1 (bedroom door straight off the foyer) is poor.
    * **Direct sightline** - whether someone at the main door can see into a
      private room, tested by ray-casting against the wall set.
    * **Wet-room exposure** - a WC door opening directly onto a living or dining
      space, which is both a privacy and a cultural failure in Indian homes.
    """
    per_room: dict[str, float] = {}
    findings: list[Finding] = []
    detail: dict[str, object] = {}

    private = [r for r in plan.all_rooms if r.type.is_private]
    if not private:
        return MetricReport("privacy", 0.75, summary="No private rooms to assess.")

    entry_point = _entry_point(plan)
    walls = plan.all_walls

    for level in plan.levels:
        connectivity = plan.connectivity(level.index)
        entry_room = _entry_room(plan, level.index)
        depths = _bfs_depths(connectivity, entry_room) if entry_room else {}

        for room in level.rooms:
            if not room.type.is_private:
                continue
            depth = depths.get(room.id, 3)
            depth_score = _clamp((depth - 1) / 2.5)

            sightline_blocked = True
            if entry_point is not None:
                sightline_blocked = not _has_clear_sightline(entry_point, room.centre, walls, room.id)
            sight_score = 1.0 if sightline_blocked else 0.25

            # Does a WC / bathroom open onto a social room?
            exposure_penalty = 0.0
            if room.type in {RoomType.BATHROOM, RoomType.TOILET}:
                for neighbour_id in connectivity.get(room.id, set()):
                    neighbour = plan.room_by_id(neighbour_id)
                    if neighbour and neighbour.type in {
                        RoomType.LIVING, RoomType.DINING, RoomType.DRAWING, RoomType.KITCHEN
                    }:
                        exposure_penalty = 0.45
                        findings.append(
                            Finding(
                                code="PRIV.WC_ONTO_SOCIAL",
                                severity=Severity.MAJOR,
                                message=(
                                    f"{room.display_name()} opens directly onto "
                                    f"{neighbour.display_name()}."
                                ),
                                target_id=room.id,
                                target_label=room.display_name(),
                                remedy="Interpose a lobby or turn the door to face circulation space.",
                                evidence=[
                                    Evidence(
                                        kind=EvidenceKind.COMPUTED,
                                        source="Door connectivity graph",
                                        locator=f"{room.id}->{neighbour.id}",
                                    )
                                ],
                            )
                        )
                        break

            score = _clamp(0.4 * depth_score + 0.6 * sight_score - exposure_penalty)
            per_room[room.id] = round(score, 4)
            detail[room.id] = {
                "name": room.display_name(),
                "topological_depth": depth,
                "sightline_from_entry_blocked": sightline_blocked,
                "exposure_penalty": exposure_penalty,
            }

            if not sightline_blocked:
                findings.append(
                    Finding(
                        code="PRIV.DIRECT_SIGHTLINE",
                        severity=Severity.MODERATE,
                        message=f"{room.display_name()} is directly visible from the main entrance.",
                        target_id=room.id,
                        target_label=room.display_name(),
                        metric="sightline",
                        actual="open",
                        expected="screened",
                        remedy="Introduce a foyer screen, a turn in the circulation, or relocate the door.",
                        evidence=[
                            Evidence(
                                kind=EvidenceKind.COMPUTED,
                                source="Ray-cast visibility test from entrance",
                                locator=room.id,
                            )
                        ],
                    )
                )
            if depth <= 1 and room.type in {RoomType.MASTER_BEDROOM, RoomType.BEDROOM}:
                findings.append(
                    Finding(
                        code="PRIV.SHALLOW_DEPTH",
                        severity=Severity.MINOR,
                        message=f"{room.display_name()} opens off the entrance with no intervening space.",
                        target_id=room.id,
                        target_label=room.display_name(),
                        metric="topological_depth",
                        actual=depth,
                        expected=2,
                        remedy="Route the bedroom off a passage or family space rather than the foyer.",
                    )
                )

    if not per_room:
        return MetricReport("privacy", 0.75, summary="No private rooms on any level.")

    score = sum(per_room.values()) / len(per_room)
    return MetricReport(
        axis="privacy",
        score=round(score, 4),
        per_room=per_room,
        findings=findings,
        detail=detail,
        summary=f"Mean privacy score {score:.2f} across {len(per_room)} private rooms.",
    )


def _entry_point(plan: FloorPlan) -> Vec2 | None:
    for wall in plan.all_walls:
        for opening in wall.openings:
            if opening.kind is OpeningKind.MAIN_DOOR:
                return wall.point_at(opening.position)
    return None


def _entry_room(plan: FloorPlan, level_index: int) -> str | None:
    level = plan.level_at(level_index)
    if level is None:
        return None
    for wall in level.walls:
        for opening in wall.openings:
            if opening.kind is OpeningKind.MAIN_DOOR:
                if opening.connects:
                    for room_id in opening.connects:
                        if room_id and plan.room_by_id(room_id):
                            return room_id
                if wall.rooms:
                    return wall.rooms[0]
    foyer = next((r for r in level.rooms if r.type in {RoomType.FOYER, RoomType.LOBBY}), None)
    if foyer:
        return foyer.id
    living = next((r for r in level.rooms if r.type is RoomType.LIVING), None)
    return living.id if living else (level.rooms[0].id if level.rooms else None)


def _bfs_depths(graph: dict[str, set[str]], start: str | None) -> dict[str, int]:
    if not start or start not in graph:
        return {}
    depths = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbour in graph.get(node, set()):
            if neighbour not in depths:
                depths[neighbour] = depths[node] + 1
                queue.append(neighbour)
    return depths


def _has_clear_sightline(origin: Vec2, target: Vec2, walls: list[Wall], target_room_id: str) -> bool:
    """True when no wall blocks the straight line from origin to target."""
    for wall in walls:
        if target_room_id in wall.rooms and _wall_has_door(wall):
            continue
        if not segments_intersect(origin, target, wall.start, wall.end):
            continue
        # A doorway in the intersected wall may leave the line open.
        blocked = True
        for opening in wall.openings:
            if not opening.kind.is_door:
                continue
            centre = wall.point_at(opening.position)
            if distance_point_to_segment(centre, origin, target) < opening.width / 2:
                blocked = False
                break
        if blocked:
            return False
    return True


def _wall_has_door(wall: Wall) -> bool:
    return any(o.kind.is_door for o in wall.openings)


# ---------------------------------------------------------------------------
# Circulation
# ---------------------------------------------------------------------------

#: Room pairs whose separation materially affects daily life, with a weight.
FUNCTIONAL_PAIRS: tuple[tuple[RoomType, RoomType, float], ...] = (
    (RoomType.KITCHEN, RoomType.DINING, 1.6),
    (RoomType.LIVING, RoomType.DINING, 1.1),
    (RoomType.MASTER_BEDROOM, RoomType.BATHROOM, 1.5),
    (RoomType.BEDROOM, RoomType.BATHROOM, 1.2),
    (RoomType.KITCHEN, RoomType.UTILITY, 1.0),
    (RoomType.FOYER, RoomType.LIVING, 1.2),
    (RoomType.KITCHEN, RoomType.STORE, 0.7),
)


def circulation_analysis(plan: FloorPlan) -> MetricReport:
    """Circulation efficiency: area overhead, connectivity and travel distance."""
    findings: list[Finding] = []
    detail: dict[str, object] = {}
    per_room: dict[str, float] = {}

    total_area = plan.total_built_area
    if total_area <= 0:
        return MetricReport("circulation", 0.0, summary="Plan has no area.")

    circulation_area = sum(r.area for r in plan.all_rooms if r.type.is_circulation)
    ratio = circulation_area / total_area

    # 8-15% is the efficient band for residential work. Below it, rooms are
    # inter-connecting awkwardly; above it, saleable area is being wasted.
    if ratio < 0.04:
        area_score = 0.45
    elif ratio <= 0.15:
        area_score = 1.0
    else:
        area_score = _clamp(1.0 - (ratio - 0.15) * 4.0)

    reachability_score = 1.0
    travel_score = 1.0
    distances: dict[str, float] = {}

    for level in plan.levels:
        connectivity = plan.connectivity(level.index)
        entry = _entry_room(plan, level.index)
        reached = _bfs_depths(connectivity, entry)
        unreachable = [r for r in level.rooms if r.id not in reached and not r.type.is_outdoor]
        if unreachable and level.rooms:
            reachability_score = min(
                reachability_score, _clamp(1.0 - len(unreachable) / len(level.rooms))
            )
            for room in unreachable[:6]:
                findings.append(
                    Finding(
                        code="CIRC.UNREACHABLE",
                        severity=Severity.CRITICAL,
                        message=f"{room.display_name()} cannot be reached from the entrance through any door.",
                        target_id=room.id,
                        target_label=room.display_name(),
                        remedy="Add a door connecting it to the circulation network.",
                        evidence=[
                            Evidence(
                                kind=EvidenceKind.COMPUTED,
                                source="Door connectivity graph traversal",
                                locator=room.id,
                            )
                        ],
                    )
                )

        weights = _shortest_paths(plan, level.index, connectivity)
        pair_scores: list[tuple[float, float]] = []
        for type_a, type_b, weight in FUNCTIONAL_PAIRS:
            rooms_a = [r for r in level.rooms if r.type is type_a]
            rooms_b = [r for r in level.rooms if r.type is type_b]
            if not rooms_a or not rooms_b:
                continue
            best = min(
                (weights.get((a.id, b.id), math.inf) for a in rooms_a for b in rooms_b),
                default=math.inf,
            )
            if math.isinf(best):
                continue
            key = f"{type_a.value}->{type_b.value}"
            distances[key] = round(best, 2)
            # Under 8 m is comfortable in a house; beyond 20 m is a nuisance.
            pair_scores.append((weight, _clamp(1.0 - max(0.0, best - 8.0) / 12.0)))
            if best > 18.0:
                findings.append(
                    Finding(
                        code="CIRC.LONG_PATH",
                        severity=Severity.MINOR,
                        message=f"Walking distance from {type_a.label} to {type_b.label} is {best:.1f} m.",
                        metric=key,
                        actual=round(best, 2),
                        expected=8.0,
                        remedy="Bring these functions closer or add a direct connection.",
                    )
                )
        if pair_scores:
            total_w = sum(w for w, _ in pair_scores)
            travel_score = min(
                travel_score, sum(w * s for w, s in pair_scores) / (total_w or 1.0)
            )

        for room in level.rooms:
            per_room[room.id] = round(
                _clamp(1.0 - (0.0 if room.id in reached else 1.0)) * 0.5 + 0.5 * area_score, 4
            )

    score = _clamp(0.3 * area_score + 0.35 * reachability_score + 0.35 * travel_score)
    detail["circulation_area_ratio"] = round(ratio, 4)
    detail["circulation_area_m2"] = round(circulation_area, 2)
    detail["functional_distances_m"] = distances

    if ratio > 0.20:
        findings.append(
            Finding(
                code="CIRC.EXCESSIVE",
                severity=Severity.MODERATE,
                message=f"Circulation consumes {ratio:.1%} of the built area.",
                metric="circulation_area_ratio",
                actual=round(ratio, 4),
                expected=0.12,
                remedy="Shorten passages or absorb circulation into living space.",
                evidence=[
                    Evidence(
                        kind=EvidenceKind.COMPUTED,
                        source="Area takeoff",
                        detail=f"{circulation_area:.1f} m2 of {total_area:.1f} m2.",
                    )
                ],
            )
        )

    return MetricReport(
        axis="circulation",
        score=round(score, 4),
        per_room=per_room,
        findings=findings,
        detail=detail,
        summary=f"Circulation {ratio:.1%} of area; travel efficiency {travel_score:.2f}.",
    )


def _shortest_paths(
    plan: FloorPlan, level_index: int, connectivity: dict[str, set[str]]
) -> dict[tuple[str, str], float]:
    """All-pairs shortest walking distance through doors (Dijkstra per source)."""
    level = plan.level_at(level_index)
    if level is None:
        return {}
    centres = {r.id: r.centre for r in level.rooms}
    out: dict[tuple[str, str], float] = {}

    for source in centres:
        dist = {source: 0.0}
        queue: list[tuple[float, str]] = [(0.0, source)]
        while queue:
            d, node = heapq.heappop(queue)
            if d > dist.get(node, math.inf):
                continue
            for neighbour in connectivity.get(node, set()):
                if neighbour not in centres:
                    continue
                step = centres[node].distance_to(centres[neighbour])
                nd = d + step
                if nd < dist.get(neighbour, math.inf):
                    dist[neighbour] = nd
                    heapq.heappush(queue, (nd, neighbour))
        for target, value in dist.items():
            out[(source, target)] = value
    return out


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------

WHEELCHAIR_TURNING_DIAMETER = 1.5     # m
MIN_ACCESSIBLE_DOOR_CLEAR = 0.90      # m
MIN_ACCESSIBLE_CORRIDOR = 1.20        # m


def accessibility_analysis(plan: FloorPlan, brief: ClientBrief | None = None) -> MetricReport:
    """Step-free access, door widths, turning circles and reachable sanitation."""
    from aip.domain.brief import AccessibilityLevel

    level_required = brief.accessibility if brief else AccessibilityLevel.BASIC
    strict = level_required in {AccessibilityLevel.WHEELCHAIR, AccessibilityLevel.UNIVERSAL}

    findings: list[Finding] = []
    detail: dict[str, object] = {}
    per_room: dict[str, float] = {}

    door_min = MIN_ACCESSIBLE_DOOR_CLEAR if strict else 0.80
    scores: list[float] = []

    for opening in plan.all_openings:
        if not opening.kind.is_door:
            continue
        if opening.width + 1e-6 < door_min:
            findings.append(
                Finding(
                    code="ACC.DOOR_WIDTH",
                    severity=Severity.MAJOR if strict else Severity.MINOR,
                    message=f"A door is {opening.width:.2f} m wide, below the {door_min:.2f} m clear width.",
                    target_id=opening.id,
                    metric="door_width",
                    actual=opening.width,
                    expected=door_min,
                    remedy=f"Widen to at least {door_min:.2f} m.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.STANDARD,
                            source="Harmonised Guidelines for Accessible India, 2021",
                            locator=opening.id,
                        )
                    ],
                )
            )
            scores.append(0.3 if strict else 0.7)
        else:
            scores.append(1.0)

    for room in plan.all_rooms:
        if room.type.is_outdoor or room.type is RoomType.SHAFT:
            continue
        square = room.usable_square()
        needs_turn = strict and (room.type.is_habitable or room.type.is_wet)
        room_score = 1.0
        if needs_turn and square < WHEELCHAIR_TURNING_DIAMETER:
            room_score = _clamp(square / WHEELCHAIR_TURNING_DIAMETER)
            findings.append(
                Finding(
                    code="ACC.TURNING_CIRCLE",
                    severity=Severity.MAJOR,
                    message=(
                        f"{room.display_name()} cannot accommodate a "
                        f"{WHEELCHAIR_TURNING_DIAMETER:.1f} m turning circle "
                        f"(largest clear square {square:.2f} m)."
                    ),
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="clear_turning_square_m",
                    actual=round(square, 2),
                    expected=WHEELCHAIR_TURNING_DIAMETER,
                    remedy="Enlarge the room or rearrange fittings to free a clear circle.",
                )
            )
        if room.type.is_circulation and room.type is RoomType.CORRIDOR:
            width = min(room.bbox.width, room.bbox.height)
            required = MIN_ACCESSIBLE_CORRIDOR if strict else 0.90
            if width + 1e-6 < required:
                room_score = min(room_score, _clamp(width / required))
                findings.append(
                    Finding(
                        code="ACC.CORRIDOR_WIDTH",
                        severity=Severity.MAJOR if strict else Severity.MODERATE,
                        message=f"{room.display_name()} is {width:.2f} m wide, below {required:.2f} m.",
                        target_id=room.id,
                        target_label=room.display_name(),
                        metric="corridor_width",
                        actual=round(width, 2),
                        expected=required,
                        remedy=f"Widen the passage to at least {required:.2f} m.",
                    )
                )
        per_room[room.id] = round(room_score, 4)
        scores.append(room_score)

    # Is there an accessible WC on the entrance level?
    ground = plan.level_at(0)
    if strict and ground is not None:
        wcs = [r for r in ground.rooms if r.type in {RoomType.BATHROOM, RoomType.TOILET, RoomType.POWDER}]
        accessible = [r for r in wcs if r.usable_square() >= WHEELCHAIR_TURNING_DIAMETER]
        detail["accessible_wc_on_entry_level"] = bool(accessible)
        if not accessible:
            findings.append(
                Finding(
                    code="ACC.NO_ACCESSIBLE_WC",
                    severity=Severity.MAJOR,
                    message="No wheelchair-accessible WC on the entrance level.",
                    remedy="Provide one WC with a 1.5 m clear turning circle at entry level.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.STANDARD,
                            source="Harmonised Guidelines for Accessible India, 2021",
                        )
                    ],
                )
            )
            scores.append(0.2)

    for stair in (s for lv in plan.levels for s in lv.staircases):
        if stair.riser > 0.19:
            findings.append(
                Finding(
                    code="ACC.RISER",
                    severity=Severity.MODERATE,
                    message=f"Stair riser is {stair.riser * 1000:.0f} mm, above the 190 mm maximum.",
                    target_id=stair.id,
                    metric="riser_mm",
                    actual=round(stair.riser * 1000, 1),
                    expected=190.0,
                    remedy="Add steps to reduce the riser, or increase the stair footprint.",
                    evidence=[Evidence(kind=EvidenceKind.STANDARD, source="NBC of India 2016, Part 4")],
                )
            )
            scores.append(0.5)

    score = sum(scores) / len(scores) if scores else 0.7
    detail["standard"] = level_required.value
    return MetricReport(
        axis="accessibility",
        score=round(_clamp(score), 4),
        per_room=per_room,
        findings=findings,
        detail=detail,
        summary=f"Accessibility score {score:.2f} at '{level_required.value}' standard.",
    )


# ---------------------------------------------------------------------------
# Spatial quality
# ---------------------------------------------------------------------------


def spatial_quality_analysis(plan: FloorPlan) -> MetricReport:
    """Proportion, furnishability and geometric sanity.

    Catches the failure mode that purely area-driven generators produce: rooms
    that satisfy their area target but are 1.4 m wide, or L-shaped in a way no
    furniture layout can use.
    """
    per_room: dict[str, float] = {}
    findings: list[Finding] = []
    detail: dict[str, object] = {}

    rooms = [r for r in plan.all_rooms if not r.type.is_outdoor and r.type is not RoomType.SHAFT]
    if not rooms:
        return MetricReport("spatial", 0.0, summary="No rooms.")

    for room in rooms:
        aspect = room.aspect
        compact = room.compactness_score
        square = room.usable_square()

        # 1:1 to 1:1.6 reads as generous; beyond 1:2.2 becomes a corridor.
        aspect_score = 1.0 if aspect <= 1.6 else _clamp(1.0 - (aspect - 1.6) / 1.4)

        required_square = _min_useful_square(room.type)
        furnish_score = _clamp(square / required_square) if required_square else 1.0

        score = _clamp(0.4 * aspect_score + 0.25 * compact + 0.35 * furnish_score)
        per_room[room.id] = round(score, 4)
        detail[room.id] = {
            "name": room.display_name(),
            "aspect_ratio": aspect,
            "compactness": compact,
            "largest_clear_square_m": round(square, 2),
        }

        if aspect > 2.6 and room.type.is_habitable:
            findings.append(
                Finding(
                    code="SPACE.SLENDER",
                    severity=Severity.MODERATE,
                    message=f"{room.display_name()} is {aspect:.1f}:1 - too slender to furnish comfortably.",
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="aspect_ratio",
                    actual=aspect,
                    expected=1.6,
                    remedy="Rebalance the partition positions to widen the room.",
                )
            )
        if required_square and square < required_square * 0.8:
            findings.append(
                Finding(
                    code="SPACE.UNFURNISHABLE",
                    severity=Severity.MAJOR,
                    message=(
                        f"{room.display_name()} has only a {square:.2f} m clear square; "
                        f"{required_square:.2f} m is needed for its function."
                    ),
                    target_id=room.id,
                    target_label=room.display_name(),
                    metric="clear_square_m",
                    actual=round(square, 2),
                    expected=required_square,
                    remedy="Increase the short dimension or simplify the room outline.",
                    evidence=[
                        Evidence(
                            kind=EvidenceKind.COMPUTED,
                            source="Largest inscribed square",
                            detail="Furniture-fit proxy independent of total area.",
                            locator=room.id,
                        )
                    ],
                )
            )

    score = sum(per_room.values()) / len(per_room)
    return MetricReport(
        axis="spatial",
        score=round(score, 4),
        per_room=per_room,
        findings=findings,
        detail=detail,
        summary=f"Mean spatial quality {score:.2f} across {len(per_room)} rooms.",
    )


def _min_useful_square(room_type: RoomType) -> float:
    """Clear square (m) a room needs before its core furniture will fit."""
    return {
        RoomType.MASTER_BEDROOM: 3.0,     # queen bed plus circulation
        RoomType.BEDROOM: 2.7,
        RoomType.GUEST_BEDROOM: 2.7,
        RoomType.CHILDREN_BEDROOM: 2.5,
        RoomType.LIVING: 3.2,
        RoomType.DRAWING: 3.0,
        RoomType.FAMILY: 2.8,
        RoomType.DINING: 2.6,
        RoomType.KITCHEN: 1.8,
        RoomType.STUDY: 2.0,
        RoomType.HOME_OFFICE: 2.0,
        RoomType.BATHROOM: 1.2,
        RoomType.TOILET: 0.9,
        RoomType.PUJA: 0.9,
        RoomType.GYM: 2.5,
        RoomType.HOME_THEATRE: 3.0,
    }.get(room_type, 0.0)


def analyse_all(plan: FloorPlan, brief: ClientBrief | None = None) -> dict[str, MetricReport]:
    """Run every analytical metric. Cheap enough to call inside an optimiser loop."""
    return {
        "daylight": daylight_analysis(plan),
        "ventilation": ventilation_analysis(plan),
        "privacy": privacy_analysis(plan),
        "circulation": circulation_analysis(plan),
        "accessibility": accessibility_analysis(plan, brief),
        "spatial": spatial_quality_analysis(plan),
    }
