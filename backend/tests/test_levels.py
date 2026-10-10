"""A house with an upper floor is still a house you can walk through.

Every layout test before this one generated a single-storey plan. The studio's
default brief is a duplex, and the duplex path had never been looked at: it
carried thirteen staircases on one floor, an upper floor entered through the
master bedroom, and bathrooms doored from each other. These tests generate
the briefs the studio actually sends and hold every floor to the same rules.
"""

from __future__ import annotations

from collections import Counter

import pytest

from aip.api.schemas import SimpleBriefRequest
from aip.domain.plan import OpeningKind, RoomType
from aip.engines.architecture.layout import (
    MIN_CLEAR_WIDTH,
    GeneratorConfig,
    LayoutGenerator,
    _overlap_fraction,
)
from aip.engines.architecture.programme import walkability

_COMMON = {
    "budget": 6500000, "vastu": "balanced", "occupant_adults": 2, "occupant_children": 1, "occupant_elders": 1,
    "setback_front": 2.5, "setback_rear": 1.5, "setback_left": 1.2, "setback_right": 1.2,
    "finish_tier": "premium", "kitchen_type": "open_modular",
}


def _brief(**kw):
    amenities = kw.pop("amenities", ["pooja", "dining", "utility"])
    return SimpleBriefRequest(amenities=amenities, must_haves=amenities, **_COMMON, **kw).to_brief()


def _generate(brief, seed, count=3):
    return LayoutGenerator(brief, GeneratorConfig(seed=seed)).generate(count)


@pytest.fixture(scope="module")
def duplex_plans():
    """The studio's default brief: 12 x 18 m, north road, 3 BHK on two floors."""
    brief = _brief(plot_width=12, plot_depth=18, levels=2, bedrooms=3, bathrooms=3,
                   road_direction="N")
    return [p for seed in (1, 2) for p in _generate(brief, seed)]


def _illegal(plan):
    return [
        f"level {level.index}: {r.room} {r.reason}"
        for level in plan.levels for r in walkability(plan, level.index) if not r.legal
    ]


# ---------------------------------------------------------------------------
# The studio's default duplex
# ---------------------------------------------------------------------------


def test_duplex_has_two_floors_of_the_right_rooms(duplex_plans):
    for plan in duplex_plans:
        assert len(plan.levels) == 2
        ground = Counter(r.type for r in plan.level_at(0).rooms)
        upper = Counter(r.type for r in plan.level_at(1).rooms)
        assert ground[RoomType.LIVING] == 1 and ground[RoomType.KITCHEN] == 1
        assert ground[RoomType.FOYER] == 1 and ground[RoomType.BATHROOM] == 1
        assert upper[RoomType.MASTER_BEDROOM] == 1 and upper[RoomType.BEDROOM] == 2
        assert upper[RoomType.BATHROOM] == 2


def test_one_staircase_per_floor_and_one_passage(duplex_plans):
    """Thirteen staircases on one floor was the bug that started this file."""
    for plan in duplex_plans:
        for level in plan.levels:
            kinds = Counter(r.type for r in level.rooms)
            assert kinds[RoomType.STAIRCASE] == 1, plan.name
            assert kinds[RoomType.CORRIDOR] + kinds[RoomType.LOBBY] == 1, plan.name


def test_every_room_on_every_floor_is_reached_the_right_way(duplex_plans):
    for plan in duplex_plans:
        assert not _illegal(plan), (plan.name, _illegal(plan))


def test_the_upper_floor_is_entered_from_the_stair(duplex_plans):
    for plan in duplex_plans:
        for route in walkability(plan, 1):
            assert route.path[0] == "Staircase", route
        # And nothing upstairs has a front door.
        upper = plan.level_at(1)
        assert not any(
            o.kind is OpeningKind.MAIN_DOOR for w in upper.walls for o in w.openings
        )


def test_the_stairs_stack(duplex_plans):
    for plan in duplex_plans:
        ground = next(r for r in plan.level_at(0).rooms if r.type is RoomType.STAIRCASE)
        upper = next(r for r in plan.level_at(1).rooms if r.type is RoomType.STAIRCASE)
        assert _overlap_fraction(upper.bbox, ground.bbox) >= 0.5, plan.name


def test_the_master_bedroom_has_its_own_bathroom(duplex_plans):
    for plan in duplex_plans:
        upper = plan.level_at(1)
        rooms = {r.id: r for r in upper.rooms}
        master = next(r for r in upper.rooms if r.type is RoomType.MASTER_BEDROOM)
        en_suite = [
            o for w in upper.walls for o in w.openings
            if o.kind.is_door and o.connects and master.id in o.connects
            and any(rooms[x].type is RoomType.BATHROOM for x in o.connects if x in rooms)
        ]
        assert en_suite, plan.name


def test_no_room_is_narrower_than_its_kind_allows(duplex_plans):
    for plan in duplex_plans:
        for level in plan.levels:
            for room in level.rooms:
                short = min(room.bbox.width, room.bbox.height)
                floor = MIN_CLEAR_WIDTH.get(room.type, 1.5)
                assert short >= floor - 0.05, (plan.name, room.name, short)


def test_the_guardrail_finds_nothing_to_say(duplex_plans):
    """The plans offered for the default brief pass every hard rule."""
    for plan in duplex_plans:
        assert plan.metadata["guardrail"] == [], (plan.name, plan.metadata["guardrail"])


def test_the_ground_floor_is_a_full_footprint(duplex_plans):
    """No holes: the rooms of each floor tile the same envelope."""
    for plan in duplex_plans:
        areas = [sum(r.area for r in level.rooms) for level in plan.levels]
        assert max(areas) - min(areas) < 0.5, areas


# ---------------------------------------------------------------------------
# The programme is fixed once
# ---------------------------------------------------------------------------


def test_requirements_do_not_grow_with_use():
    brief = _brief(plot_width=12, plot_depth=18, levels=2, bedrooms=3, bathrooms=3)
    gen = LayoutGenerator(brief, GeneratorConfig(population=16, generations=8, seed=3))
    before = [r.type for r in gen.requirements]
    buckets = [list(b) for b in gen.level_buckets]
    gen.generate(2)
    gen.generate(2)
    assert [r.type for r in gen.requirements] == before
    assert [list(b) for b in gen.level_buckets] == buckets
    assert sum(1 for t in before if t is RoomType.STAIRCASE) == 2


# ---------------------------------------------------------------------------
# Other briefs the studio can send
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kw", [
    {"plot_width": 12, "plot_depth": 18, "levels": 2, "bedrooms": 3, "bathrooms": 3, "road_direction": "E"},
    {"plot_width": 12, "plot_depth": 18, "levels": 3, "bedrooms": 5, "bathrooms": 4, "road_direction": "W"},
    {"plot_width": 10, "plot_depth": 14, "levels": 2, "bedrooms": 2, "bathrooms": 2, "road_direction": "N",
         "amenities": ["utility"]},
    {"plot_width": 15, "plot_depth": 20, "levels": 2, "bedrooms": 4, "bathrooms": 4, "road_direction": "S",
         "amenities": ["pooja", "dining", "utility", "study", "balcony", "parking"]},
])
def test_other_briefs_walk_through(kw):
    plans = _generate(_brief(**kw), seed=1)
    clean = [p for p in plans if not p.metadata["guardrail"]]
    assert len(clean) >= 2, [p.metadata["guardrail"] for p in plans]
    for plan in clean:
        assert not _illegal(plan)
        for level in plan.levels:
            assert sum(1 for r in level.rooms if r.type is RoomType.STAIRCASE) == 1


def test_a_narrow_plot_runs_its_passage_down_one_side():
    """6.5 m of frontage cannot hold two rooms and a passage: single-loaded."""
    plans = _generate(_brief(plot_width=9, plot_depth=15, levels=2, bedrooms=3, bathrooms=2,
                             road_direction="N"), seed=3)
    clean = [p for p in plans if not p.metadata["guardrail"]]
    assert clean
    upper = clean[0].level_at(1)
    corridor = next(r for r in upper.rooms if r.type is RoomType.CORRIDOR)
    assert min(corridor.bbox.width, corridor.bbox.height) >= 1.0
    assert not _illegal(clean[0])


# ---------------------------------------------------------------------------
# The guardrail itself
# ---------------------------------------------------------------------------


def test_the_guardrail_catches_a_bedroom_reached_through_the_kitchen(duplex_plans):
    plan = duplex_plans[0].clone()
    gen = LayoutGenerator(_brief(plot_width=12, plot_depth=18, levels=2, bedrooms=3, bathrooms=3))
    assert gen._sanity(plan) == []
    # Relabel the ground-floor hall as a kitchen: every room off it is now
    # reached through the kitchen, and the plan must say so.
    hall = next(r for r in plan.level_at(0).rooms if r.type is RoomType.CORRIDOR)
    hall.type = RoomType.KITCHEN
    problems = gen._sanity(plan)
    assert any("passes through" in p or "entered from" in p for p in problems), problems
    assert any("passages" not in p for p in problems)


def test_the_guardrail_counts_stairs_and_passages(duplex_plans):
    plan = duplex_plans[0].clone()
    gen = LayoutGenerator(_brief(plot_width=12, plot_depth=18, levels=2, bedrooms=3, bathrooms=3))
    upper = plan.level_at(1)
    bath = next(r for r in upper.rooms if r.type is RoomType.BATHROOM)
    bath.type = RoomType.STAIRCASE
    problems = gen._sanity(plan)
    assert any("2 staircases" in p for p in problems), problems
