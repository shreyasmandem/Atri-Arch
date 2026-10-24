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


def test_pool_options_say_what_fits_where(pool_plan):
    """Customise offers only the pools that fit: each kind with the places it fits."""
    from aip.engines.experience.landscape import POOL_PLACES, POOLS, pool_options

    opts = pool_options(pool_plan)
    assert set(opts) == set(POOLS)
    assert all(set(v) <= set(POOL_PLACES) for v in opts.values())
    assert opts["family"]                                # the brief made room for it
    # What the options promise, a placement keeps.
    from aip.engines.architecture.editor import apply_edits
    for place in opts["family"]:
        new, applied, refused = apply_edits(pool_plan, [{"op": "pool", "kind": "family", "place": place}])
        assert applied and not refused, (place, refused)


def test_a_tight_plot_fits_no_pool_and_the_edit_says_so():
    from aip.engines.architecture.editor import apply_edits
    from aip.engines.experience.landscape import pool_options

    brief = SimpleBriefRequest(plot_width=12.2, plot_depth=18.3, levels=2, bedrooms=3).to_brief()
    plan = LayoutGenerator(brief, GeneratorConfig(population=16, generations=8, seed=3)).generate(count=1)[0]
    if not any(pool_options(plan).values()):
        _new, applied, refused = apply_edits(plan, [{"op": "pool", "kind": "plunge"}])
        assert not applied and "does not fit" in refused[0]


def test_a_smaller_pool_is_offered_not_swapped_in(pool_plan):
    """Asking for a lap pool where only a smaller one fits is refused with the
    one that would, rather than quietly building the smaller one."""
    from aip.engines.architecture.editor import apply_edits
    from aip.engines.experience.landscape import pool_options

    opts = pool_options(pool_plan)
    if not opts["lap"] and opts["family"]:
        _new, applied, refused = apply_edits(pool_plan, [{"op": "pool", "kind": "lap"}])
        assert not applied and "family pool would" in refused[0]


def test_the_pool_deck_keeps_off_the_drive(pool_plan):
    from aip.engines.experience.landscape import DRIVE_HALF, POOL_DECK, _footprint, _gate, drive_line
    from shapely.geometry import Polygon

    rect, _kind = pool_rect(pool_plan)
    plot = Polygon([(p.x, p.y) for p in pool_plan.site.boundary])
    drive = drive_line(_footprint(pool_plan), _gate(pool_plan, plot)).buffer(DRIVE_HALF)
    assert not rect.buffer(POOL_DECK).intersects(drive)


def test_the_pool_is_sunk_below_its_coping(pool_plan):
    """The water sits below the coping round it, so it reads as a pool, not a sheet on the lawn."""
    from aip.engines.experience.arch3d import build_scene

    from shapely.geometry import Point

    scene = build_scene(pool_plan, include_furniture=False)
    rect, _kind = pool_rect(pool_plan)
    # Meshes are merged per node and material; take the site's vertices over the pool itself.
    def top(part: str, area) -> float:
        ys = [float(y) for k, g in scene.geometry.items() if k.startswith("site__") and part in k
              for x, y, z in g.vertices if area.contains(Point(x, -z))]
        return max(ys)
    assert top("pool_water", rect.buffer(0.01)) < top("__sill", rect.buffer(0.31)) - 0.1   # a hand's width below the coping


def test_glass_and_corten_homes_build_in_their_own_materials(pool_plan):
    """The new signature homes build, glass walls in glass with a mullion frame, corten in weathering steel."""
    from aip.engines.experience.arch3d import build_scene
    from aip.engines.experience.looks import LOOKS, look_designs

    designs = {d["look"]: d for d in look_designs(pool_plan, variations=1)}
    for look in ("glass_box_villa", "floating_glass_house", "black_glass_modern", "corten_courtyard",
                 "corten_glass_cube", "mediterranean_villa", "industrial_loft"):
        assert look in LOOKS and look in designs
        names = {g.visual.material.name for g in build_scene(pool_plan, include_furniture=False,
                                                             design_id=designs[look]["id"]).geometry.values()}
        if "glass" in look:
            assert "curtain_glass" in names
        if "corten" in look:
            assert "corten_steel" in names


def test_a_lawn_gets_lamps_and_a_path(pool_plan):
    """A garden is dressed: lamps light the drive and stones lead to its feature; a bare site is not."""
    from aip.engines.experience.arch3d import build_scene
    from aip.engines.experience.exteriors import Exterior

    lit = build_scene(pool_plan, include_furniture=False, design_id=Exterior(yard="fountain", garden="standard").id)
    bare = build_scene(pool_plan, include_furniture=False, design_id=Exterior(yard="fountain", garden="none").id)
    lamps = lambda sc: sum(len(g.faces) for k, g in sc.geometry.items() if k.startswith("site__") and k.endswith("__light"))  # noqa: E731
    assert lamps(lit) > 0 and lamps(bare) == 0


def test_a_large_plot_is_not_left_mostly_lawn():
    """A house on a 55 x 85 ft plot that asked to keep a quarter as lawn used
    to cover under a third of it; it now grows toward what the byelaw allows.
    A town plot the programme already fills is left as it was."""
    from shapely.geometry import Polygon

    from aip.engines.experience.landscape import _footprint

    def share(w: float, d: float, lawn: float) -> float:
        req = SimpleBriefRequest(plot_width=w, plot_depth=d, levels=2, bedrooms=3, bathrooms=3,
                                 road_direction="N", **({"lawn_share": lawn} if lawn else {}))
        gen = LayoutGenerator(req.to_brief(), GeneratorConfig(seed=3))
        plan = gen.generate(count=1)[0]
        plot = Polygon([(p.x, p.y) for p in plan.site.boundary])
        return _footprint(plan).area / plot.area

    big = share(16.76, 25.91, 0.25)
    assert big >= 0.40, f"the house covers only {big:.0%} of a plot meant to keep 25% as lawn"
    assert big <= 0.62                                  # and never past the byelaw's coverage
    town = share(12.19, 18.29, 0.0)
    assert 0.40 <= town <= 0.60
