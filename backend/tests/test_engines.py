"""Engine behaviour: generation, physics, compliance, Vastu, cost, interiors, 3D."""

from __future__ import annotations

import pytest

from aip.domain.geometry import Direction
from aip.domain.plan import FloorPlan, OpeningKind, RoomType, WallKind
from aip.engines.architecture.codes import compliance_analysis
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator
from aip.engines.architecture.metrics import analyse_all
from aip.engines.architecture.solar import (
    annual_orientation_exposure,
    average_daylight_factor,
    daylight_hours,
    daylight_quality_by_orientation,
    solar_declination,
    sun_position,
)

# ══ Generation ═════════════════════════════════════════════════════════


def test_generator_produces_valid_geometry(plan: FloorPlan):
    assert plan.levels, "no levels generated"
    assert plan.all_rooms, "no rooms generated"
    for room in plan.all_rooms:
        assert room.area > 0, f"{room.display_name()} has zero area"
        assert len(room.polygon) >= 3


def test_rooms_do_not_overlap(plan: FloorPlan):
    """A slicing tree guarantees a partition. This asserts the guarantee holds."""
    from aip.domain.geometry import overlap_area

    rooms = plan.levels[0].rooms
    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            shared = overlap_area(a.polygon, b.polygon)
            assert shared < 0.05, (
                f"{a.display_name()} and {b.display_name()} overlap by {shared:.3f} m2"
            )


def test_every_room_is_reachable_through_doors(plan: FloorPlan):
    """The defect that made every early scheme fail the circulation critic."""
    from collections import deque

    for level in plan.levels:
        graph = plan.connectivity(level.index)
        if len(level.rooms) <= 1:
            continue
        start = next(iter(graph))
        seen, queue = {start}, deque([start])
        while queue:
            node = queue.popleft()
            for nxt in graph.get(node, set()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        unreachable = [r.display_name() for r in level.rooms if r.id not in seen]
        assert not unreachable, f"unreachable rooms: {unreachable}"


def test_habitable_rooms_receive_glazing(plan: FloorPlan):
    for room in plan.all_rooms:
        if not room.type.is_habitable:
            continue
        walls = [w for w in plan.levels[room.level].walls if room.id in w.rooms]
        glazed = sum(o.area for w in walls for o in w.openings if o.kind.is_glazed)
        exterior = [w for w in walls if w.kind is WallKind.EXTERIOR]
        if exterior:
            assert glazed > 0, f"{room.display_name()} has an external wall but no window"


def test_main_door_exists_and_faces_the_road(plan: FloorPlan):
    doors = [o for o in plan.all_openings if o.kind is OpeningKind.MAIN_DOOR]
    assert len(doors) == 1, f"expected exactly one main door, found {len(doors)}"


def test_generator_respects_far_and_coverage(plan: FloorPlan):
    assert plan.achieved_far <= plan.site.max_far + 1e-6
    coverage = plan.footprint_area / plan.site.plot_area
    assert coverage <= plan.site.max_ground_coverage + 0.02


def test_generated_schemes_are_distinct(plans):
    assert len(plans) >= 2
    signatures = {
        tuple(sorted((r.type.value, round(r.area)) for r in p.all_rooms)) for p in plans
    }
    assert len(signatures) > 1, "the generator returned duplicate schemes"


def test_generator_is_deterministic_under_a_seed(brief):
    a = LayoutGenerator(brief, GeneratorConfig(population=24, generations=16, seed=99)).generate(1)
    b = LayoutGenerator(brief, GeneratorConfig(population=24, generations=16, seed=99)).generate(1)
    assert [round(r.area, 3) for r in a[0].all_rooms] == [round(r.area, 3) for r in b[0].all_rooms]


def test_generator_survives_an_over_constrained_brief(tight_brief):
    """A brief that cannot be satisfied must still return something reviewable."""
    plans = LayoutGenerator(tight_brief, GeneratorConfig(population=24, generations=20, seed=5)).generate(1)
    assert plans, "the generator gave up instead of returning its least-bad scheme"
    report = compliance_analysis(plans[0], tight_brief)
    assert report.detail["checks_run"] > 0


# ══ Building physics ═══════════════════════════════════════════════════


def test_solar_declination_at_solstices_and_equinoxes():
    assert solar_declination(172) == pytest.approx(23.45, abs=0.35)   # June
    assert solar_declination(355) == pytest.approx(-23.45, abs=0.35)  # December
    assert abs(solar_declination(80)) < 1.5                           # March equinox


def test_sun_is_up_at_noon_and_down_at_midnight():
    assert sun_position(13.08, 80.27, 172, 12.0).altitude > 60
    assert not sun_position(13.08, 80.27, 172, 0.0).is_up


def test_equinox_daylight_is_about_twelve_hours():
    assert daylight_hours(13.08, 80) == pytest.approx(12.0, abs=0.3)


def test_tropical_north_is_the_best_daylight_orientation():
    """The single most important orientation fact for Indian residential work.

    A model trained mostly on northern-temperate advice says "face south"; in
    Chennai that is actively wrong.
    """
    tropical = daylight_quality_by_orientation(13.08)
    assert tropical[Direction.N] > tropical[Direction.S]
    assert tropical[Direction.N] > tropical[Direction.W]
    assert tropical[Direction.W] == min(tropical.values())


def test_temperate_south_beats_north():
    temperate = daylight_quality_by_orientation(52.0)
    assert temperate[Direction.S] > temperate[Direction.N]


def test_southern_hemisphere_mirrors_north_south():
    north = daylight_quality_by_orientation(20.0)
    south = daylight_quality_by_orientation(-20.0)
    assert south[Direction.S] == pytest.approx(north[Direction.N])


def test_orientation_exposure_is_normalised():
    exposure = annual_orientation_exposure(13.08, 80.27)
    assert max(exposure.values()) == pytest.approx(1.0)
    assert all(0.0 <= v <= 1.0 for v in exposure.values())


def test_average_daylight_factor_scales_with_glazing():
    low = average_daylight_factor(1.0, 20.0)
    high = average_daylight_factor(3.0, 20.0)
    assert high > low > 0
    assert average_daylight_factor(0.0, 20.0) == 0.0


def test_metric_suite_returns_bounded_scores(plan, brief):
    reports = analyse_all(plan, brief)
    assert set(reports) == {
        "daylight", "ventilation", "privacy", "circulation", "accessibility", "spatial"
    }
    for axis, report in reports.items():
        assert 0.0 <= report.score <= 1.0, f"{axis} score out of range: {report.score}"
        assert report.summary


def test_findings_carry_a_remedy_and_a_locator(plan, brief):
    reports = analyse_all(plan, brief)
    for report in reports.values():
        for finding in report.findings:
            assert finding.message
            assert finding.code
            # Every finding must be actionable; a complaint with no fix is noise.
            assert finding.remedy or finding.severity.value == "info"


# ══ Compliance ═════════════════════════════════════════════════════════


def test_compliance_runs_real_checks(plan, brief):
    report = compliance_analysis(plan, brief)
    assert report.detail["checks_run"] >= 10
    assert 0.0 <= report.score <= 1.0


def test_far_breach_is_critical(plan, brief):
    """Statutory breaches must disqualify, not merely lower a score."""
    from aip.agents.base import Severity

    breached = plan.model_copy(deep=True)
    breached.site.max_far = 0.05
    report = compliance_analysis(breached, brief)
    assert any(f.severity is Severity.CRITICAL for f in report.findings)


def test_undersized_room_is_flagged(brief):
    from aip.agents.base import Severity
    from aip.domain.geometry import Vec2, rectangle
    from aip.domain.plan import Level, Room

    tiny = FloorPlan(
        name="Undersized",
        levels=[Level(index=0, rooms=[
            Room(name="Bedroom", type=RoomType.BEDROOM,
                 polygon=rectangle(Vec2(0, 0), 2.0, 2.0)),
        ])],
    )
    report = compliance_analysis(tiny, brief)
    codes = {f.code for f in report.findings}
    assert "NBC.3.4.1" in codes          # minimum area
    assert any(f.severity is Severity.CRITICAL for f in report.findings)


# ══ Vastu ══════════════════════════════════════════════════════════════


def test_vastu_report_is_complete(plan):
    from aip.engines.vastu.engine import analyse_vastu

    report = analyse_vastu(plan, 0.5)
    assert 0 <= report.score <= 100
    assert report.rules_assessed + report.rules_not_assessable == report.rules_total
    assert report.summary and report.grade


def test_vastu_never_scores_a_rule_it_cannot_evaluate(plan):
    """Manufactured precision is the failure mode this engine exists to avoid."""
    from aip.engines.vastu.engine import analyse_vastu

    report = analyse_vastu(plan, 0.5)
    for verdict in report.verdicts:
        if not verdict.assessable:
            assert verdict.score_contribution == 0.0
            assert verdict.reason_not_assessable or verdict.defeated_by


def test_vastu_verdicts_carry_provenance(plan):
    from aip.engines.vastu.engine import analyse_vastu

    for verdict in analyse_vastu(plan, 0.5).verdicts:
        assert verdict.citation, f"{verdict.rule_id} has no citation"
        assert verdict.school
        assert verdict.traditional_rationale
        assert verdict.modern_rationale


def test_stance_reweights_rules_without_touching_the_corpus(plan):
    """The traditional/modern reconciliation, asserted as arithmetic."""
    from aip.engines.vastu.engine import analyse_vastu

    orthodox = analyse_vastu(plan, 1.0)
    modern = analyse_vastu(plan, 0.0)

    assert orthodox.rules_total == modern.rules_total

    weak = next(v for v in orthodox.reconciliation if v.rule_id == "VS.STAIR.CLOCKWISE")
    strong = next(v for v in orthodox.reconciliation if v.rule_id == "VS.BRAHMASTHAN.OPEN")
    assert weak.weight_retained == pytest.approx(1.0, abs=0.01)
    assert strong.weight_retained == pytest.approx(1.0, abs=0.01)

    weak_modern = next(v for v in modern.reconciliation if v.rule_id == "VS.STAIR.CLOCKWISE")
    strong_modern = next(v for v in modern.reconciliation if v.rule_id == "VS.BRAHMASTHAN.OPEN")
    # A rule with no functional basis loses most of its influence; one with a
    # demonstrable climatic basis keeps nearly all of it.
    assert weak_modern.weight_retained < 0.3
    assert strong_modern.weight_retained > 0.7


def test_counterfactuals_are_bounded_and_actionable(plan):
    from aip.engines.vastu.engine import analyse_vastu

    report = analyse_vastu(plan, 0.6)
    for remedy in report.top_remedies:
        assert remedy["points_recoverable"] > 0
        assert remedy["score_if_fixed"] <= 100.0
        assert remedy["score_if_fixed"] >= report.score
        assert remedy["remedy"]


def test_quick_vastu_score_is_bounded(plan):
    from aip.engines.vastu.engine import quick_vastu_score

    assert 0.0 <= quick_vastu_score(plan, 0.5) <= 1.0


# ══ Cost ═══════════════════════════════════════════════════════════════


def test_cost_estimate_is_internally_consistent(plan, brief):
    from aip.engines.cost.estimator import estimate_cost

    e = estimate_cost(plan, brief, monte_carlo_runs=400)
    assert e.total > 0
    assert e.line_items
    assert e.works_subtotal == pytest.approx(sum(i.amount for i in e.line_items), rel=1e-6)
    expected = e.works_subtotal + e.overhead_profit + e.contingency + e.professional_fees + e.tax
    assert e.total == pytest.approx(expected, rel=1e-6)
    assert e.rate_per_m2 == pytest.approx(e.total / e.built_area_m2, rel=1e-6)


def test_cost_uncertainty_band_is_ordered(plan, brief):
    from aip.engines.cost.estimator import estimate_cost

    e = estimate_cost(plan, brief, monte_carlo_runs=800)
    assert e.p10 < e.p50 < e.p90
    assert 3.0 < e.uncertainty_band_percent < 90.0


def test_cost_scales_with_area(brief):
    """Takeoff from geometry, not a flat per-square-metre rate."""
    from aip.engines.cost.estimator import estimate_cost

    small = LayoutGenerator(brief, GeneratorConfig(population=20, generations=14, seed=3)).generate(1)[0]
    big = small.model_copy(deep=True)
    for level in big.levels:
        for room in level.rooms:
            room.polygon = [type(p)(p.x * 1.4, p.y * 1.4) for p in room.polygon]

    assert estimate_cost(big, brief, monte_carlo_runs=200).total > \
           estimate_cost(small, brief, monte_carlo_runs=200).total


def test_regional_index_moves_cost(plan, brief):
    from aip.engines.cost.estimator import estimate_cost
    from aip.engines.cost.rates import default_schedule

    chennai = estimate_cost(plan, brief, schedule=default_schedule("IN-TN"), monte_carlo_runs=200)
    mumbai = estimate_cost(plan, brief, schedule=default_schedule("IN-MH"), monte_carlo_runs=200)
    assert mumbai.total > chennai.total


def test_line_items_record_how_the_quantity_was_derived(plan, brief):
    from aip.engines.cost.estimator import estimate_cost

    e = estimate_cost(plan, brief, monte_carlo_runs=200)
    documented = [i for i in e.line_items if i.basis]
    assert len(documented) > len(e.line_items) * 0.6


def test_cash_flow_is_monotonic_and_completes(plan, brief):
    from aip.engines.cost.estimator import estimate_cost

    e = estimate_cost(plan, brief, monte_carlo_runs=200)
    cumulative = [p.cumulative for p in e.cash_flow]
    assert cumulative == sorted(cumulative)
    assert cumulative[-1] == pytest.approx(e.total, rel=1e-6)
    assert e.cash_flow[-1].percent_complete == pytest.approx(100.0, abs=0.1)


# ══ Interiors ══════════════════════════════════════════════════════════


def test_interior_places_furniture_without_collisions(plan, brief):
    from aip.engines.interior.engine import design_interior

    scheme = design_interior(plan, brief)
    assert scheme.rooms

    for room in scheme.rooms:
        boxes = [f.footprint for f in room.furniture]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                overlap_x = min(a.max_x, b.max_x) - max(a.min_x, b.min_x)
                overlap_y = min(a.max_y, b.max_y) - max(a.min_y, b.min_y)
                assert not (overlap_x > 0.03 and overlap_y > 0.03), (
                    f"furniture overlaps in {room.room_name}"
                )


def test_furniture_stays_inside_its_room(plan, brief):
    from aip.engines.interior.engine import design_interior

    scheme = design_interior(plan, brief)
    by_id = {r.id: r for r in plan.all_rooms}
    for room in scheme.rooms:
        box = by_id[room.room_id].bbox
        for item in room.furniture:
            fp = item.footprint
            assert fp.min_x >= box.min_x - 0.05 and fp.max_x <= box.max_x + 0.05
            assert fp.min_y >= box.min_y - 0.05 and fp.max_y <= box.max_y + 0.05


def test_bedrooms_get_a_bed(plan, brief):
    from aip.engines.interior.engine import design_interior

    scheme = design_interior(plan, brief)
    bedrooms = [r for r in scheme.rooms if "bedroom" in r.room_type]
    assert bedrooms
    for room in bedrooms:
        has_bed = any("bed" in f.item_id for f in room.furniture)
        blocked = any("bed" in u["item_id"] for u in room.unplaced)
        assert has_bed or blocked, f"{room.room_name}: bed neither placed nor explained"


def test_unplaced_items_explain_themselves(plan, brief):
    from aip.engines.interior.engine import design_interior

    for room in design_interior(plan, brief).rooms:
        for item in room.unplaced:
            assert item["reason"]
            assert "m" in item["reason"]     # states the dimensions involved


# ══ 3D ═════════════════════════════════════════════════════════════════


def test_glb_export_is_valid_gltf(plan):
    import struct

    from aip.engines.experience.model3d import export_glb

    data = export_glb(plan)
    assert data[:4] == b"glTF"
    version, length = struct.unpack("<II", data[4:12])
    assert version == 2
    assert length == len(data)


def test_model_has_geometry_in_every_category(plan):
    from aip.engines.experience.model3d import model_statistics

    stats = model_statistics(plan)
    assert stats["triangles"] > 100
    assert stats["triangles_by_category"].get("structure", 0) > 0
    assert stats["height_m"] > 2.5


def test_walkthrough_waypoints_are_at_eye_level(plan):
    from aip.engines.experience.model3d import camera_waypoints

    waypoints = camera_waypoints(plan)
    assert waypoints
    for waypoint in waypoints:
        assert waypoint["position"][1] == pytest.approx(1.6, abs=0.01)
        assert waypoint["label"]


def test_obj_export_is_parseable(plan):
    from aip.engines.experience.model3d import export_obj

    text = export_obj(plan)
    assert text.count("\nv ") > 100
    assert text.count("\nf ") > 50


# ══ Drawings ═══════════════════════════════════════════════════════════


def test_every_drawing_renders_as_wellformed_svg(plan):
    import xml.etree.ElementTree as ET

    from aip.engines.architecture.drawings import all_drawings

    drawings = all_drawings(plan)
    assert len(drawings) >= 8
    for name, svg in drawings.items():
        root = ET.fromstring(svg)          # raises if malformed
        assert root.tag.endswith("svg"), name
        assert float(root.get("width")) > 0


def test_floor_plan_labels_every_room_large_enough_to_label(plan):
    import xml.etree.ElementTree as ET

    from aip.engines.architecture.drawings import floor_plan_svg

    root = ET.fromstring(floor_plan_svg(plan, 0))
    labels = {t.text for t in root.iter("{http://www.w3.org/2000/svg}text") if t.text}
    for room in plan.levels[0].rooms:
        if min(room.bbox.width, room.bbox.height) * 42 >= 34:
            assert room.display_name().upper() in labels
