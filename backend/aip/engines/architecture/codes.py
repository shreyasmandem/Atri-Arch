"""Statutory compliance checking against the National Building Code of India 2016.

Code compliance is the one axis where the committee is not allowed to trade off:
a scheme that breaches a statutory minimum is inadmissible regardless of how
beautiful the critics find it. That is enforced here by emitting `CRITICAL`
findings, which the consensus layer treats as disqualifying.

The rule set is data, not control flow, so a firm working under a different
development control regulation - a state DCR, a municipal byelaw, or an
international code - can supply its own table without touching the engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from aip.agents.base import Evidence, EvidenceKind, Finding, Severity
from aip.domain.brief import NBC_MIN_AREAS, NBC_MIN_WIDTH, ClientBrief
from aip.domain.plan import FloorPlan, RoomType
from aip.engines.architecture.metrics import MetricReport, _clamp


@dataclass(frozen=True, slots=True)
class CodeRule:
    """One checkable requirement, with its citation."""

    code: str
    clause: str
    description: str
    severity: Severity = Severity.MAJOR
    source: str = "National Building Code of India 2016"


RULES: dict[str, CodeRule] = {
    "AREA_MIN": CodeRule(
        "NBC.3.4.1", "Part 3, Cl. 4.1",
        "Minimum floor area for habitable rooms.", Severity.CRITICAL,
    ),
    "WIDTH_MIN": CodeRule(
        "NBC.3.4.2", "Part 3, Cl. 4.1",
        "Minimum clear width for habitable rooms.", Severity.CRITICAL,
    ),
    "HEIGHT_MIN": CodeRule(
        "NBC.3.4.3", "Part 3, Cl. 4.3",
        "Minimum clear floor-to-ceiling height of 2.75 m for habitable rooms.", Severity.CRITICAL,
    ),
    "LIGHT_MIN": CodeRule(
        "NBC.3.4.4", "Part 3, Cl. 4.2",
        "Openings for light of not less than one-tenth of the floor area.", Severity.MAJOR,
    ),
    "VENT_MIN": CodeRule(
        "NBC.8.4.1", "Part 8, Cl. 4",
        "Openable area for ventilation of not less than one-sixth of the floor area.", Severity.MAJOR,
    ),
    "FAR_MAX": CodeRule(
        "DCR.FAR", "Local development control regulation",
        "Permissible floor area ratio.", Severity.CRITICAL,
        source="Local Development Control Regulation",
    ),
    "COVERAGE_MAX": CodeRule(
        "DCR.COVERAGE", "Local development control regulation",
        "Maximum ground coverage.", Severity.CRITICAL,
        source="Local Development Control Regulation",
    ),
    "HEIGHT_MAX": CodeRule(
        "DCR.HEIGHT", "Local development control regulation",
        "Maximum permitted building height.", Severity.CRITICAL,
        source="Local Development Control Regulation",
    ),
    "SETBACK": CodeRule(
        "DCR.SETBACK", "Local development control regulation",
        "Mandatory open space on all sides.", Severity.CRITICAL,
        source="Local Development Control Regulation",
    ),
    "STAIR_RISER": CodeRule(
        "NBC.4.4.4", "Part 4, Cl. 4.4",
        "Maximum riser 190 mm and minimum tread 250 mm for residential stairs.", Severity.MAJOR,
    ),
    "STAIR_WIDTH": CodeRule(
        "NBC.4.4.5", "Part 4, Cl. 4.4",
        "Minimum stair width of 1.0 m for residential occupancy.", Severity.MAJOR,
    ),
    "STAIR_HEADROOM": CodeRule(
        "NBC.4.4.6", "Part 4, Cl. 4.4",
        "Minimum headroom of 2.1 m over a stair flight.", Severity.MAJOR,
    ),
    "KITCHEN_MIN": CodeRule(
        "NBC.3.4.7", "Part 3, Cl. 4.1",
        "Minimum kitchen area of 5.5 m2 with a minimum width of 1.8 m.", Severity.MAJOR,
    ),
    "BATH_MIN": CodeRule(
        "NBC.3.4.8", "Part 3, Cl. 4.1",
        "Minimum bathroom area of 1.8 m2, WC 1.1 m2.", Severity.MAJOR,
    ),
}

#: Relative tolerance on statutory *ratios* (FAR, ground coverage).
#: An approving authority does not reject a drawing for exceeding coverage by
#: forty-six square millimetres; an exact comparison turns floating-point noise
#: into a critical breach. 0.1% of the permitted value is well inside drafting
#: tolerance and still far tighter than any real plan-check.
RATIO_TOLERANCE = 0.001

MIN_HABITABLE_HEIGHT = 2.75
MIN_STAIR_WIDTH = 1.0
MAX_STAIR_RISER = 0.19
MIN_STAIR_TREAD = 0.25
MIN_STAIR_HEADROOM = 2.1


def _finding(rule_key: str, message: str, **kw) -> Finding:
    rule = RULES[rule_key]
    evidence = kw.pop("evidence", [])
    return Finding(
        code=rule.code,
        severity=kw.pop("severity", rule.severity),
        message=message,
        evidence=[
            Evidence(
                kind=EvidenceKind.STANDARD,
                source=f"{rule.source}, {rule.clause}",
                detail=rule.description,
                locator=kw.get("target_id", ""),
            ),
            *evidence,
        ],
        **kw,
    )


def compliance_analysis(plan: FloorPlan, brief: ClientBrief | None = None) -> MetricReport:
    """Full statutory review of a plan. Returns findings with clause citations."""
    findings: list[Finding] = []
    detail: dict[str, object] = {}
    checks_run = 0
    checks_passed = 0

    site = plan.site

    # ------------------------------------------------------------ envelope --
    checks_run += 1
    if site.plot_area > 0 and plan.achieved_far > site.max_far * (1 + RATIO_TOLERANCE):
        findings.append(
            _finding(
                "FAR_MAX",
                f"Floor area ratio of {plan.achieved_far:.2f} exceeds the permitted {site.max_far:.2f}.",
                metric="far",
                actual=plan.achieved_far,
                expected=site.max_far,
                remedy=(
                    f"Reduce built-up area by about "
                    f"{plan.total_built_area - site.max_built_area:.1f} m2."
                ),
            )
        )
    else:
        checks_passed += 1

    checks_run += 1
    coverage = plan.footprint_area / site.plot_area if site.plot_area else 0.0
    if coverage > site.max_ground_coverage * (1 + RATIO_TOLERANCE):
        findings.append(
            _finding(
                "COVERAGE_MAX",
                f"Ground coverage of {coverage:.1%} exceeds the permitted {site.max_ground_coverage:.1%}.",
                metric="ground_coverage",
                actual=round(coverage, 4),
                expected=site.max_ground_coverage,
                remedy=f"Reduce the footprint by about {plan.footprint_area - site.max_footprint:.1f} m2.",
            )
        )
    else:
        checks_passed += 1

    checks_run += 1
    if plan.building_height > site.max_height * (1 + RATIO_TOLERANCE):
        findings.append(
            _finding(
                "HEIGHT_MAX",
                f"Building height of {plan.building_height:.2f} m exceeds the permitted {site.max_height:.2f} m.",
                metric="height_m",
                actual=plan.building_height,
                expected=site.max_height,
                remedy="Reduce floor-to-floor heights or the number of levels.",
            )
        )
    else:
        checks_passed += 1

    # Setbacks: every room must sit inside the buildable envelope.
    if site.boundary:
        checks_run += 1
        breaches = _setback_breaches(plan)
        if breaches:
            for room_name, encroachment in breaches[:6]:
                findings.append(
                    _finding(
                        "SETBACK",
                        f"{room_name} encroaches {encroachment:.2f} m into the mandatory setback.",
                        metric="setback_encroachment_m",
                        actual=round(encroachment, 3),
                        expected=0.0,
                        remedy="Pull the building line back inside the setback envelope.",
                    )
                )
        else:
            checks_passed += 1
        detail["setback_breaches"] = len(breaches)

    # --------------------------------------------------------------- rooms --
    for room in plan.all_rooms:
        if room.type.is_outdoor or room.type is RoomType.SHAFT:
            continue

        min_area = NBC_MIN_AREAS.get(room.type)
        if min_area:
            checks_run += 1
            if room.area + 1e-6 < min_area:
                findings.append(
                    _finding(
                        "AREA_MIN",
                        f"{room.display_name()} is {room.area:.2f} m2, below the statutory minimum of {min_area:.2f} m2.",
                        target_id=room.id,
                        target_label=room.display_name(),
                        metric="area_m2",
                        actual=room.area,
                        expected=min_area,
                        remedy=f"Enlarge by at least {min_area - room.area:.2f} m2.",
                    )
                )
            else:
                checks_passed += 1

        min_width = NBC_MIN_WIDTH.get(room.type)
        if min_width:
            checks_run += 1
            width = min(room.bbox.width, room.bbox.height)
            if width + 1e-6 < min_width:
                findings.append(
                    _finding(
                        "WIDTH_MIN",
                        f"{room.display_name()} has a clear width of {width:.2f} m, below the {min_width:.2f} m minimum.",
                        target_id=room.id,
                        target_label=room.display_name(),
                        metric="clear_width_m",
                        actual=round(width, 3),
                        expected=min_width,
                        remedy=f"Widen by at least {min_width - width:.2f} m.",
                    )
                )
            else:
                checks_passed += 1

        if room.type.is_habitable:
            checks_run += 1
            if room.ceiling_height + 1e-6 < MIN_HABITABLE_HEIGHT:
                findings.append(
                    _finding(
                        "HEIGHT_MIN",
                        f"{room.display_name()} has a ceiling height of {room.ceiling_height:.2f} m, below {MIN_HABITABLE_HEIGHT} m.",
                        target_id=room.id,
                        target_label=room.display_name(),
                        metric="ceiling_height_m",
                        actual=room.ceiling_height,
                        expected=MIN_HABITABLE_HEIGHT,
                        remedy=f"Raise the ceiling to at least {MIN_HABITABLE_HEIGHT} m.",
                    )
                )
            else:
                checks_passed += 1

    # -------------------------------------------------------------- stairs --
    for level in plan.levels:
        for stair in level.staircases:
            checks_run += 3
            if stair.riser > MAX_STAIR_RISER + 1e-6 or stair.tread + 1e-6 < MIN_STAIR_TREAD:
                findings.append(
                    _finding(
                        "STAIR_RISER",
                        (
                            f"Stair geometry is non-compliant: riser {stair.riser * 1000:.0f} mm "
                            f"(max 190), tread {stair.tread * 1000:.0f} mm (min 250)."
                        ),
                        target_id=stair.id,
                        metric="riser_tread_mm",
                        actual=f"{stair.riser * 1000:.0f}/{stair.tread * 1000:.0f}",
                        expected="<=190/>=250",
                        remedy="Increase the stair run so the riser drops below 190 mm.",
                    )
                )
            else:
                checks_passed += 1

            if stair.width + 1e-6 < MIN_STAIR_WIDTH:
                findings.append(
                    _finding(
                        "STAIR_WIDTH",
                        f"Stair width of {stair.width:.2f} m is below the {MIN_STAIR_WIDTH:.2f} m minimum.",
                        target_id=stair.id,
                        metric="stair_width_m",
                        actual=stair.width,
                        expected=MIN_STAIR_WIDTH,
                        remedy="Widen the stair.",
                    )
                )
            else:
                checks_passed += 1

            if stair.headroom + 1e-6 < MIN_STAIR_HEADROOM:
                findings.append(
                    _finding(
                        "STAIR_HEADROOM",
                        f"Stair headroom of {stair.headroom:.2f} m is below {MIN_STAIR_HEADROOM} m.",
                        target_id=stair.id,
                        metric="headroom_m",
                        actual=stair.headroom,
                        expected=MIN_STAIR_HEADROOM,
                        remedy="Increase the floor-to-floor height or lengthen the flight.",
                    )
                )
            else:
                checks_passed += 1

    # A multi-level building must actually have a stair.
    if len(plan.levels) > 1:
        checks_run += 1
        if not any(level.staircases for level in plan.levels):
            findings.append(
                _finding(
                    "STAIR_WIDTH",
                    "The building has multiple levels but no staircase.",
                    severity=Severity.CRITICAL,
                    metric="staircase_count",
                    actual=0,
                    expected=1,
                    remedy="Add a compliant staircase connecting the levels.",
                )
            )
        else:
            checks_passed += 1

    critical = sum(1 for f in findings if f.severity is Severity.CRITICAL)
    major = sum(1 for f in findings if f.severity is Severity.MAJOR)

    pass_rate = checks_passed / checks_run if checks_run else 1.0
    score = _clamp(pass_rate - 0.22 * critical - 0.07 * major)

    detail.update(
        {
            "checks_run": checks_run,
            "checks_passed": checks_passed,
            "pass_rate": round(pass_rate, 4),
            "critical_breaches": critical,
            "major_breaches": major,
            "achieved_far": plan.achieved_far,
            "permitted_far": site.max_far,
            "ground_coverage": round(coverage, 4),
            "building_height_m": plan.building_height,
        }
    )

    return MetricReport(
        axis="compliance",
        score=round(score, 4),
        findings=findings,
        detail=detail,
        evidence=[
            Evidence(
                kind=EvidenceKind.STANDARD,
                source="National Building Code of India 2016",
                detail=f"{checks_passed} of {checks_run} statutory checks passed.",
                value=round(pass_rate, 3),
            )
        ],
        summary=(
            f"{checks_passed}/{checks_run} code checks passed. "
            f"{critical} critical, {major} major breach(es)."
        ),
    )


def _setback_breaches(plan: FloorPlan) -> list[tuple[str, float]]:
    """Rooms that cross the mandatory open-space line, with encroachment depth."""
    from aip.domain.geometry import point_in_polygon, shrink_polygon

    site = plan.site
    setback = min(site.setback_front, site.setback_rear, site.setback_left, site.setback_right)
    if setback <= 0 or not site.boundary:
        return []

    envelope = shrink_polygon(site.boundary, setback)
    if not envelope:
        return [("entire building", setback)]

    breaches: list[tuple[str, float]] = []
    ground = plan.level_at(0)
    if ground is None:
        return []

    for room in ground.rooms:
        if room.type.is_outdoor:
            continue
        worst = 0.0
        for point in room.polygon:
            if not point_in_polygon(point, envelope):
                worst = max(worst, _distance_outside(point, envelope))
        if worst > 0.02:
            breaches.append((room.display_name(), worst))
    return sorted(breaches, key=lambda b: -b[1])


def _distance_outside(point, polygon) -> float:
    from aip.domain.geometry import distance_point_to_segment

    return min(
        distance_point_to_segment(point, polygon[i], polygon[(i + 1) % len(polygon)])
        for i in range(len(polygon))
    )
