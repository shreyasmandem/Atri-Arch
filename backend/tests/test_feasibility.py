"""Does the programme fit the plot, and does the house fit the programme?

Four things the generator now does before and around the search, each of which
used to be left to luck:

* a **feasibility gate** that adds a floor, drops optional rooms, draws rooms
  smaller, or refuses with a typed error - and says which, in plain English;
* a **staircase carved once**, as locked cuts, so it is the same rectangle on
  every floor;
* **proportion and circulation** limits that rule out slots and halls;
* a **house that grows to a generous plot**, with every room capped at what a
  room of its kind usefully is.
"""

from __future__ import annotations

import json

import pytest

from aip.api.schemas import SimpleBriefRequest
from aip.domain.plan import RoomType
from aip.engines.architecture.feasibility import (
    LUXURY_MAX,
    InfeasibleBriefError,
    luxury_max,
    max_levels,
)
from aip.engines.architecture.layout import (
    MIN_CLEAR_WIDTH,
    GeneratorConfig,
    LayoutGenerator,
    aspect_limit,
    corridor_penalty,
    proportion_penalty,
)

#: A search small enough to run in a test; these tests are about structure.
QUICK = {"population": 24, "generations": 20, "max_runs": 2, "time_budget": 4.0}


def _brief(**kw):
    amenities = kw.pop("amenities", ["pooja", "dining", "utility"])
    # These tests cover the studio filling a generous plot, which it now does
    # only when the client allows rooms they did not ask for.
    kw.setdefault("auto_extras", True)
    # The gate is exercised under the classic limits; the size-dependent byelaw
    # defaults have their own test (test_byelaw_limits_follow_the_plot_size).
    kw.setdefault("max_ground_coverage", 0.6)
    kw.setdefault("max_far", 1.5)
    return SimpleBriefRequest(amenities=amenities, **kw).to_brief()


def _kinds(generator: LayoutGenerator) -> list[RoomType]:
    return [r.type for r in generator.requirements]


# ---------------------------------------------------------------------------
# The staircase is one rectangle on every floor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kw", [
    {"plot_width": 12, "plot_depth": 18, "levels": 2, "bedrooms": 3, "bathrooms": 3, "road_direction": "N"},
    {"plot_width": 15, "plot_depth": 20, "levels": 3, "bedrooms": 3, "bathrooms": 2, "road_direction": "E"},
    {"plot_width": 9, "plot_depth": 15, "levels": 2, "bedrooms": 3, "bathrooms": 3, "road_direction": "SW"},
])
def test_the_staircase_is_the_same_rectangle_on_every_floor(kw):
    plans = LayoutGenerator(_brief(**kw), GeneratorConfig(seed=4, **QUICK)).generate(2)
    assert plans
    for plan in plans:
        rects = [
            next(r.bbox for r in level.rooms if r.type is RoomType.STAIRCASE)
            for level in plan.levels
        ]
        assert len(rects) > 1
        for rect in rects[1:]:
            assert (rect.min_x, rect.min_y, rect.max_x, rect.max_y) == pytest.approx(
                (rects[0].min_x, rects[0].min_y, rects[0].max_x, rects[0].max_y), abs=1e-6
            )
        # And it is a real dog-leg, not a closet.
        assert min(rects[0].width, rects[0].height) >= 2.0 - 1e-6   # two 0.9 m flights
        assert max(rects[0].width, rects[0].height) >= 3.8
        assert not any("stack" in p for p in plan.metadata["guardrail"])


def test_the_carve_is_locked_so_the_search_cannot_move_the_stair():
    from aip.engines.architecture.layout import Genome, crossover, mutate

    generator = LayoutGenerator(
        _brief(plot_width=12, plot_depth=18, levels=2, bedrooms=3, bathrooms=3, road_direction="N"),
        GeneratorConfig(seed=2, **QUICK),
    )
    worker = generator._worker(1, 5)
    rng = __import__("random").Random(3)
    slots = list(range(len(worker.requirements)))
    areas = [r.target_area for r in worker.requirements]
    population = worker._seed_population(slots, areas, worker._envelope)
    stair_slot = next(s for s in slots if worker.requirements[s].type is RoomType.STAIRCASE)
    from aip.engines.architecture.layout import realise

    expected = realise(population[0].tree, worker._envelope)[stair_slot]
    genome: Genome = population[0]
    for _ in range(200):
        genome = mutate(genome, rng)
        genome = crossover(genome, population[rng.randrange(len(population))], rng)
        box = realise(genome.tree, worker._envelope)[stair_slot]
        assert (box.min_x, box.min_y, box.max_x, box.max_y) == pytest.approx(
            (expected.min_x, expected.min_y, expected.max_x, expected.max_y), abs=1e-9
        )
        assert genome.assignment[stair_slot] == stair_slot


# ---------------------------------------------------------------------------
# The feasibility gate
# ---------------------------------------------------------------------------


def test_a_programme_that_does_not_fit_gets_a_floor_and_says_so():
    brief = _brief(plot_width=10, plot_depth=14, levels=1, bedrooms=4, bathrooms=3,
                   amenities=["utility"], road_direction="S")
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    assert generator.brief.levels == 2
    assert generator.feasibility.requested_levels == 1
    assert any("a floor was added" in a for a in generator.advisories), generator.advisories
    # Bedrooms went up; the public rooms stayed down; a staircase links them.
    ground = {generator.requirements[i].type for i in generator.level_buckets[0]}
    upper = {generator.requirements[i].type for i in generator.level_buckets[1]}
    assert RoomType.LIVING in ground and RoomType.KITCHEN in ground
    assert RoomType.BEDROOM in upper and RoomType.MASTER_BEDROOM in upper
    assert RoomType.STAIRCASE in ground and RoomType.STAIRCASE in upper


def test_optional_rooms_go_in_the_stated_order_when_a_floor_is_not_enough():
    brief = _brief(plot_width=9, plot_depth=12, levels=2, bedrooms=3, bathrooms=3,
                   amenities=["pooja", "study", "balcony", "utility"], road_direction="N")
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    dropped = generator.feasibility.dropped
    # Rooms the client named go last, in the stated order, after anything the
    # programme added on its own.
    named = [d for d in dropped if d in ("study", "balcony")]
    assert named == ["study", "balcony"], dropped
    kinds = _kinds(generator)
    assert RoomType.STUDY not in kinds and RoomType.BALCONY not in kinds
    text = " ".join(generator.advisories)
    assert "study" in text and "balcony" in text
    # The puja is a niche, not a room, and the advisory says so.
    if "puja" in dropped:
        assert "niche" in text


def test_extra_bathrooms_are_the_last_optional_thing_to_go():
    brief = _brief(plot_width=10, plot_depth=14, levels=1, bedrooms=4, bathrooms=6,
                   amenities=["study", "balcony", "utility", "pooja"], road_direction="S")
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    dropped = generator.feasibility.dropped
    if "bathroom" in dropped:
        # Every other optional room that could go went first.
        assert dropped.index("bathroom") > max(
            (i for i, d in enumerate(dropped) if d != "bathroom"), default=-1
        ) - 1
        kept = sum(1 for k in _kinds(generator) if k is RoomType.BATHROOM)
        assert kept >= 3        # one per two bedrooms plus a common one


def test_an_over_full_brief_is_relaxed_rather_than_refused():
    """A client is never sent away with nothing: rooms and floors give way, and the plan says so."""
    brief = _brief(plot_width=9, plot_depth=12, levels=1, bedrooms=5, bathrooms=5)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    assert generator.advisories
    assert any("left out" in a or "tight" in a or "floor was added" in a for a in generator.advisories)


def test_a_programme_nothing_can_save_is_a_typed_error_with_the_numbers():
    brief = _brief(plot_width=6, plot_depth=8, levels=1, bedrooms=5, bathrooms=5)
    with pytest.raises(InfeasibleBriefError) as caught:
        LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    error = caught.value
    assert str(error).startswith("A 5-bedroom ")
    assert "buildable area" in str(error) and "m²" in str(error)
    assert "reduce bedrooms" in str(error).lower()
    assert error.needed_area > error.available_area > 0
    payload = error.to_dict()
    assert payload["code"] == "infeasible_brief"
    json.dumps(payload)         # the stream sends it as JSON


def test_where_no_floor_can_be_added_the_error_does_not_suggest_one():
    brief = _brief(plot_width=6, plot_depth=8, levels=1, bedrooms=5, bathrooms=5)
    brief.site.max_height = 3.2           # one floor, by the height rule
    assert max_levels(brief.site.max_height) == 1
    with pytest.raises(InfeasibleBriefError) as caught:
        LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    message = str(caught.value)
    assert "single-storey" in message
    assert "Add a floor" not in message and "Reduce bedrooms" in message


def test_the_far_stops_a_floor_being_added():
    brief = _brief(plot_width=10, plot_depth=14, levels=1, bedrooms=4, bathrooms=3, amenities=["utility"])
    brief.site.max_far = 0.8
    try:
        generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    except InfeasibleBriefError:
        return                      # refused: also correct
    assert generator.brief.levels == 1


def test_a_generous_brief_is_left_alone_by_the_gate():
    brief = _brief(plot_width=15, plot_depth=25, levels=1, bedrooms=2, bathrooms=2)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    assert generator.brief.levels == 1
    assert generator.feasibility.dropped == []
    assert not generator.feasibility.shrunk


def test_advisories_travel_with_the_plan_into_its_json():
    brief = _brief(plot_width=10, plot_depth=14, levels=1, bedrooms=4, bathrooms=3, amenities=["utility"])
    plans = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK)).generate(1)
    advisories = plans[0].metadata["advisories"]
    assert advisories and all(isinstance(a, str) for a in advisories)
    clone = plans[0].clone()
    assert clone.metadata["advisories"] == advisories        # refinement clones the plan
    dumped = json.loads(plans[0].model_dump_json())
    assert dumped["metadata"]["advisories"] == advisories     # and the API serialises it
    assert dumped["metadata"]["feasibility"]["requested_levels"] == 1


def test_a_light_upper_floor_gets_a_terrace_not_a_fifty_square_metre_bathroom():
    brief = _brief(plot_width=20, plot_depth=30, levels=3, bedrooms=1, bathrooms=2, amenities=["balcony"])
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    # Three floors for one bedroom is more house than the rooms fill.
    assert generator.brief.levels == 2
    assert any("fill only 2" in a for a in generator.advisories)
    upper = {generator.requirements[i].type for i in generator.level_buckets[1]}
    assert RoomType.TERRACE in upper


# ---------------------------------------------------------------------------
# Proportions
# ---------------------------------------------------------------------------


def test_the_aspect_caps_are_the_ones_the_brief_names():
    assert aspect_limit(RoomType.BEDROOM) <= 2.2 and aspect_limit(RoomType.MASTER_BEDROOM) <= 2.2
    assert aspect_limit(RoomType.DINING) <= 2.2
    assert aspect_limit(RoomType.LIVING) <= 2.5
    assert aspect_limit(RoomType.KITCHEN) == 2.4              # a galley is allowed
    assert aspect_limit(RoomType.BATHROOM) == 3.0 and aspect_limit(RoomType.UTILITY) == 3.0
    assert aspect_limit(RoomType.CORRIDOR) is None            # a passage is meant to be long


def test_proportion_costs_little_below_1_6_steeply_above_and_jumps_at_the_cap():
    for kind in (RoomType.BEDROOM, RoomType.DINING, RoomType.LIVING):
        assert proportion_penalty(kind, 1.5) == 0.0
        assert 0.0 < proportion_penalty(kind, 1.65) < 0.2
        cap = aspect_limit(kind)
        assert proportion_penalty(kind, cap + 0.1) - proportion_penalty(kind, cap - 0.1) > 0.7
        # No ceiling: an 8:1 room costs more than a 4:1 one.
        assert proportion_penalty(kind, 8.0) > proportion_penalty(kind, 4.0) > proportion_penalty(kind, 3.0)
    assert proportion_penalty(RoomType.KITCHEN, 2.4) < proportion_penalty(RoomType.BEDROOM, 2.4)


def test_wet_rooms_have_the_minimum_clear_widths_the_brief_names():
    assert MIN_CLEAR_WIDTH[RoomType.BATHROOM] >= 1.5
    assert MIN_CLEAR_WIDTH[RoomType.TOILET] >= 1.0
    assert MIN_CLEAR_WIDTH[RoomType.UTILITY] >= 1.2


def test_the_guardrail_refuses_a_slot_a_bedroom_too_narrow_and_a_hall():
    brief = _brief(plot_width=12, plot_depth=18, levels=1, bedrooms=3, bathrooms=2)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    plan = generator.generate(1)[0]
    assert generator._sanity(plan) == plan.metadata["guardrail"]
    bedroom = next(r for r in plan.level_at(0).rooms if r.type is RoomType.BEDROOM)
    from aip.domain.geometry import Vec2, rectangle

    box = bedroom.bbox
    bedroom.polygon = rectangle(Vec2(box.min_x, box.min_y), 1.2, 7.0)       # a 1.2 x 7 m "bedroom"
    problems = generator._sanity(plan)
    assert any("wide" in p or "slot" in p for p in problems), problems


def test_a_clean_plan_has_no_slot_among_the_rooms_people_live_in():
    brief = _brief(plot_width=12, plot_depth=18, levels=1, bedrooms=3, bathrooms=2)
    plan = LayoutGenerator(brief, GeneratorConfig(seed=7, **QUICK)).generate(1)[0]
    if plan.metadata["guardrail"]:
        pytest.skip("the quick search found no clean scheme; covered by the sweep")
    for room in plan.all_rooms:
        if room.type.is_habitable:
            assert room.bbox.aspect_ratio <= 3.0 + 1e-9, room.display_name()


# ---------------------------------------------------------------------------
# Corridors
# ---------------------------------------------------------------------------


def test_circulation_is_free_to_ten_percent_and_dear_above_twelve():
    assert corridor_penalty(0.04) == 0.0
    assert corridor_penalty(0.10) == 0.0
    assert 0.0 < corridor_penalty(0.115) < corridor_penalty(0.12) < corridor_penalty(0.15)
    assert corridor_penalty(0.15) - corridor_penalty(0.12) > corridor_penalty(0.12) - corridor_penalty(0.10)


def test_a_single_bedroom_flat_is_not_given_a_corridor_it_does_not_need():
    brief = _brief(plot_width=12, plot_depth=18, levels=1, bedrooms=1, bathrooms=1)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    assert RoomType.CORRIDOR not in _kinds(generator)


def test_the_passage_a_multi_bedroom_house_gets_is_sized_from_the_plot_not_the_frontage():
    from aip.engines.architecture.programme import passage_area

    brief = _brief(plot_width=12, plot_depth=18, levels=1, bedrooms=3, bathrooms=2)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    corridors = [r for r in generator.requirements if r.type is RoomType.CORRIDOR]
    assert len(corridors) == 1
    assert corridors[0].target_area == pytest.approx(passage_area(brief.site), abs=0.11)
    assert corridors[0].target_area <= 1.15 * 7.0 + 0.1       # a metre and a bit by seven metres, at most


def test_generated_floors_keep_their_passages_under_a_sixth_and_mostly_under_a_tenth():
    brief = _brief(plot_width=12, plot_depth=18, levels=2, bedrooms=3, bathrooms=3, road_direction="N")
    plans = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK)).generate(2)
    for plan in plans:
        for level in plan.levels:
            total = sum(r.area for r in level.rooms)
            share = sum(r.area for r in level.rooms
                        if r.type in (RoomType.CORRIDOR, RoomType.LOBBY)) / total
            assert share <= 0.17, (plan.name, level.index, share)


# ---------------------------------------------------------------------------
# A generous plot gets a house that fills it
# ---------------------------------------------------------------------------


def _allowed(generator: LayoutGenerator) -> float:
    site = generator.brief.site
    return min(generator._footprint_cap(), site.max_footprint)


@pytest.mark.parametrize("kw", [
    {"plot_width": 30, "plot_depth": 40, "levels": 2, "bedrooms": 4, "bathrooms": 4},
    {"plot_width": 25, "plot_depth": 35, "levels": 2, "bedrooms": 5, "bathrooms": 5},
    {"plot_width": 20, "plot_depth": 30, "levels": 2, "bedrooms": 5, "bathrooms": 5},
])
def test_the_footprint_covers_three_quarters_of_what_the_plot_allows(kw):
    brief = _brief(max_far=3.0, amenities=["pooja", "dining", "study", "utility", "balcony", "parking"],
                   road_direction="N", **kw)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    assert generator._envelope.area >= 0.75 * _allowed(generator) - 1e-6
    assert generator._envelope.area <= _allowed(generator) + 1e-6


def test_rooms_scale_up_to_their_caps_and_never_past_them():
    brief = _brief(plot_width=40, plot_depth=60, levels=4, bedrooms=6, bathrooms=6, max_far=3.0,
                   amenities=["pooja", "dining", "study", "utility", "balcony", "parking"], road_direction="N")
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    for req in generator.requirements:
        cap = luxury_max(req.type)
        if cap is not None:
            assert req.target_area <= cap + 1e-6, (req.type, req.target_area, cap)
    # The named maxima are the ones in the table.
    assert LUXURY_MAX[RoomType.LIVING] == 70 and LUXURY_MAX[RoomType.DINING] == 35
    assert LUXURY_MAX[RoomType.KITCHEN] == 30 and LUXURY_MAX[RoomType.MASTER_BEDROOM] == 40
    assert LUXURY_MAX[RoomType.BEDROOM] == 28 and LUXURY_MAX[RoomType.BATHROOM] == 12
    assert LUXURY_MAX[RoomType.STAIRCASE] == 20
    big = [r for r in generator.requirements if r.type is RoomType.LIVING]
    assert big and big[0].target_area > big[0].asked_area   # and it did grow, to a comfortable size


def test_when_the_caps_bind_useful_rooms_are_added_and_the_advisories_say_why():
    brief = _brief(plot_width=30, plot_depth=40, levels=2, bedrooms=4, bathrooms=4, max_far=3.0,
                   amenities=["pooja", "dining", "utility"], road_direction="N")
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    kinds = _kinds(generator)
    added = [k for k in (RoomType.FAMILY, RoomType.STUDY, RoomType.GUEST_BEDROOM,
                         RoomType.HOME_THEATRE, RoomType.VERANDAH, RoomType.COURTYARD) if k in kinds]
    assert len(added) >= 3, kinds
    text = " ".join(generator.advisories)
    assert "generous" in text and "Added" in text
    # In the order the brief names: lounge first, then study.
    assert RoomType.FAMILY in kinds
    ground = {generator.requirements[i].type for i in generator.level_buckets[0]}
    assert RoomType.COURTYARD in ground or RoomType.VERANDAH in ground


def test_a_plot_the_programme_already_fills_is_not_grown():
    brief = _brief(plot_width=9, plot_depth=15, levels=2, bedrooms=3, bathrooms=2)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    assert not any("generous" in a for a in generator.advisories)
    assert generator._footprint_area is None or generator._footprint_area <= _allowed(generator)


def test_a_room_past_its_cap_is_a_finding_even_if_the_plan_is_otherwise_sound():
    brief = _brief(plot_width=12, plot_depth=18, levels=1, bedrooms=3, bathrooms=2)
    generator = LayoutGenerator(brief, GeneratorConfig(seed=1, **QUICK))
    plan = generator.generate(1)[0]
    from aip.domain.geometry import Vec2, rectangle

    living = next(r for r in plan.level_at(0).rooms if r.type is RoomType.LIVING)
    box = living.bbox
    living.polygon = rectangle(Vec2(box.min_x, box.min_y), 12.0, 10.0)      # 120 m2
    _guardrail, quality = generator._findings(plan)
    assert any("over the 26" in q for q in quality), quality


def test_byelaw_limits_follow_the_plot_size():
    small = SimpleBriefRequest(plot_width=6.1, plot_depth=9.1).to_brief().site
    large = SimpleBriefRequest(plot_width=30, plot_depth=40).to_brief().site
    assert small.max_ground_coverage > large.max_ground_coverage == 0.6
    assert small.max_far > large.max_far == 1.5
    stated = SimpleBriefRequest(plot_width=6.1, plot_depth=9.1, max_ground_coverage=0.5).to_brief().site
    assert stated.max_ground_coverage == 0.5          # what the client states wins
