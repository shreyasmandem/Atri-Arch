"""Outdoors: a lawn share and a pool hold the house back and find their place."""

from __future__ import annotations

import pytest

from aip.api.schemas import SimpleBriefRequest
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator
from aip.engines.experience.landscape import pool_area, pool_rect


def test_lawn_and_pool_hold_the_footprint_down():
    plain = SimpleBriefRequest(plot_width=15, plot_depth=25).to_brief().site
    green = SimpleBriefRequest(plot_width=15, plot_depth=25, lawn_share=0.3, pool="family").to_brief().site
    assert green.max_ground_coverage < plain.max_ground_coverage
    assert green.max_ground_coverage <= 1 - 0.3 - pool_area("family") / (15 * 25) - 0.08 + 1e-6
    assert green.garden_share == 0.3 and green.pool == "family"
    by_area = SimpleBriefRequest(plot_width=15, plot_depth=25, lawn_area=75).to_brief().site
    assert by_area.garden_share == pytest.approx(0.2)
    # Never so tight a house cannot stand.
    tight = SimpleBriefRequest(plot_width=9, plot_depth=12, lawn_share=0.7, pool="lap").to_brief().site
    assert tight.max_ground_coverage >= 0.25


@pytest.fixture(scope="module")
def pool_plan():
    brief = SimpleBriefRequest(plot_width=16, plot_depth=26, levels=2, bedrooms=3, lawn_share=0.25, pool="family").to_brief()
    plans = LayoutGenerator(brief, GeneratorConfig(population=24, generations=16, seed=5)).generate(count=1)
    assert plans
    return plans[0]


def test_the_pool_sits_in_the_garden_clear_of_the_house(pool_plan):
    from shapely.geometry import Polygon

    placed = pool_rect(pool_plan)
    assert placed is not None
    rect, kind = placed
    plot = Polygon([(p.x, p.y) for p in pool_plan.site.boundary])
    assert plot.contains(rect)
    ground = pool_plan.level_at(0)
    for room in ground.rooms:
        assert not Polygon([(p.x, p.y) for p in room.polygon]).buffer(0).intersects(rect)
    assert pool_plan.footprint_area <= pool_plan.site.max_footprint * 1.05


def test_the_pool_is_built_and_drawn(pool_plan):
    from aip.engines.architecture.drawings import site_plan_svg
    from aip.engines.experience.arch3d import build_scene

    names = {g.visual.material.name for g in build_scene(pool_plan, include_furniture=False).geometry.values()}
    assert "pool_water" in names
    svg = site_plan_svg(pool_plan)
    assert "POOL" in svg and "Open ground" in svg


def test_a_pool_that_cannot_fit_is_said_so():
    from aip.engines.architecture.drawings import site_plan_svg

    brief = SimpleBriefRequest(plot_width=9, plot_depth=12, levels=2, bedrooms=2, pool="lap").to_brief()
    plans = LayoutGenerator(brief, GeneratorConfig(population=16, generations=8, seed=3)).generate(count=1)
    if plans and pool_rect(plans[0]) is None:
        assert "does not fit" in site_plan_svg(plans[0])


def test_a_garden_pool_is_not_also_a_room():
    from aip.api.schemas import RoomRequest
    from aip.domain.plan import RoomType

    extra = [RoomRequest(type=RoomType.LIVING, label="Swimming Pool")]
    with_pool = SimpleBriefRequest(plot_width=16, plot_depth=26, pool="family", extra_rooms=extra).to_brief()
    without = SimpleBriefRequest(plot_width=16, plot_depth=26, extra_rooms=extra).to_brief()
    assert not any((r.label or "").lower().endswith("pool") for r in with_pool.requirements)
    assert any((r.label or "").lower().endswith("pool") for r in without.requirements)


def test_garden_features_find_their_quarter_and_build(pool_plan):
    import math

    from aip.engines.experience.arch3d import build_scene
    from aip.engines.experience.exteriors import YARDS, Exterior
    from aip.engines.experience.landscape import YARD_FEATURES, yard_spot

    placed = 0
    for kind in YARDS[1:]:
        spot = yard_spot(pool_plan, kind)
        if spot is not None:
            placed += 1
            c, r = spot
            centre = pool_plan.site.centre
            assert math.hypot(c.x - centre.x, c.y - centre.y) > 0.5
        build_scene(pool_plan, include_furniture=False, design_id=Exterior(yard=kind).id)
    assert placed >= 4
    assert set(YARD_FEATURES) == set(YARDS[1:])


def test_words_ask_for_garden_features():
    from aip.engines.experience.exteriors import prefer_from_text

    assert prefer_from_text("a tulsi in front and a jhoola")["yard"][:2] == ("tulsi", "jhoola")


def test_the_pool_goes_where_it_is_asked(pool_plan):
    """Behind the house and centred on it by default, not wedged in a corner;
    beside it, in the north-east or in the far corner when asked."""
    from aip.engines.architecture.editor import apply_edits
    from aip.engines.experience.landscape import _footprint, road_vector

    foot = _footprint(pool_plan)
    road = road_vector(pool_plan)
    back = (-road.x, -road.y)
    across = (-back[1], back[0])

    def where(plan):
        rect, _kind = pool_rect(plan)
        c = rect.centroid
        v = (c.x - foot.centroid.x, c.y - foot.centroid.y)
        return v[0] * back[0] + v[1] * back[1], v[0] * across[0] + v[1] * across[1], rect

    along, side, rect = where(pool_plan)
    assert along > 0                                    # behind the house
    assert abs(side) < 1.5                              # centred on it
    corner, applied, _ = apply_edits(pool_plan, [{"op": "pool", "place": "corner"}])
    assert applied and corner.site.pool_place == "corner"
    assert where(corner)[2].centroid.distance(rect.centroid) > 0.5
    beside, applied, refused = apply_edits(pool_plan, [{"op": "pool", "place": "side"}])
    if applied:
        # Level with the house, in a side yard.
        a2, s2, _r = where(beside)
        assert abs(s2) > abs(side) and abs(a2) < abs(along)
    else:
        assert "no room beside the house" in refused[0]
    gone, applied, _ = apply_edits(pool_plan, [{"op": "pool", "kind": "none"}])
    assert applied == ["Pool removed"] and pool_rect(gone) is None
    _same, applied, refused = apply_edits(pool_plan, [{"op": "pool", "place": "roof"}])
    assert not applied and refused
