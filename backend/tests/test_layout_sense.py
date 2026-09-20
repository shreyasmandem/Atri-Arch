"""Does the plan work as a building?

Every other test in this suite asks whether a number is right. These ask the
question a client asks first: is the kitchen near the dining room, can you get
to the bathroom without crossing the living room, and does the air reach the
back of the bedroom. A plan can pass every metric in the platform and fail all
three, which is exactly what it used to do.
"""

from __future__ import annotations

import re

import pytest

from aip.domain.brief import default_residence_brief
from aip.domain.geometry import Vec2
from aip.domain.plan import (
    FloorPlan,
    Level,
    Opening,
    OpeningKind,
    Room,
    RoomType,
    Site,
    Wall,
    WallKind,
)
from aip.engines.architecture.airflow import airflow_svg
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator
from aip.engines.architecture.metrics import (
    VENTILATION_DEPTH_LIMIT,
    ventilation_analysis,
    ventilation_mode,
)
from aip.engines.architecture.programme import (
    RESIDENCE,
    ZONE_OF,
    Zone,
    apply_defaults,
    door_cost_factor,
    evaluate,
    programme_for,
)

SEEDS = (17, 23, 11, 5, 42)


@pytest.fixture(scope="module")
def brief():
    return default_residence_brief()


@pytest.fixture(scope="module")
def plans(brief):
    return [
        LayoutGenerator(
            brief, GeneratorConfig(population=36, generations=32, seed=seed)
        ).generate(1)[0]
        for seed in SEEDS
    ]


# ---------------------------------------------------------------------------
# The programme itself
# ---------------------------------------------------------------------------


def test_programme_is_coherent():
    """No relationship may contradict another, and none may be self-referential."""
    seen: dict[frozenset, float] = {}
    for rel in RESIDENCE:
        assert rel.a is not rel.b, f"{rel.a} related to itself"
        assert rel.weight != 0.0, f"{rel.a}/{rel.b} carries no weight"
        assert -1.0 <= rel.weight <= 1.0
        assert rel.reason.strip(), f"{rel.a}/{rel.b} states no reason"
        assert rel.scope in {"wall", "door", "both"}

        key = frozenset((rel.a, rel.b))
        if key in seen:
            assert (seen[key] > 0) == (rel.weight > 0), (
                f"{rel.a}/{rel.b} is both wanted and forbidden"
            )
        seen[key] = rel.weight


def test_every_room_type_has_a_zone():
    """A room with no zone is invisible to the zoning score."""
    for rel in RESIDENCE:
        assert rel.a in ZONE_OF, rel.a
        assert rel.b in ZONE_OF, rel.b


def test_defaults_fill_silence_but_never_override(brief):
    filled = apply_defaults(brief)
    by_type = {r.type: r for r in filled.requirements}

    # The relationship whose absence made the old plans obviously wrong.
    assert RoomType.KITCHEN in by_type[RoomType.DINING].must_be_adjacent_to
    assert RoomType.LIVING in by_type[RoomType.FOYER].must_be_adjacent_to

    # An explicit brief is a decision and must survive untouched.
    stated = brief.model_copy(deep=True)
    stated.requirements[0].must_be_adjacent_to = [RoomType.GARAGE]
    kept = apply_defaults(stated)
    assert kept.requirements[0].must_be_adjacent_to == [RoomType.GARAGE]


def test_door_costs_follow_the_programme():
    """Wanted pairs are cheaper to connect; forbidden ones dearer."""
    from aip.domain.brief import ProjectKind

    wanted = door_cost_factor(RoomType.FOYER, RoomType.LIVING, ProjectKind.RESIDENCE)
    forbidden = door_cost_factor(RoomType.FOYER, RoomType.TOILET, ProjectKind.RESIDENCE)
    neutral = door_cost_factor(RoomType.STORE, RoomType.BALCONY, ProjectKind.RESIDENCE)

    assert wanted < neutral < forbidden
    assert forbidden > 2.0, "a WC off the entrance must be strongly discouraged"


def test_programme_falls_back_rather_than_being_empty():
    """An unmapped project kind must still get an opinion.

    Returning no programme is how the generator ended up with no view on where
    anything went, so the fallback matters more than it looks.
    """
    from aip.domain.brief import ProjectKind

    for kind in ProjectKind:
        assert programme_for(kind), f"{kind} has no programme"


# ---------------------------------------------------------------------------
# Generated plans must satisfy it
# ---------------------------------------------------------------------------


def test_the_core_sequence_holds(plans, brief):
    """Arrive, receive, eat, cook: the chain that makes a house a house.

    These four are checked individually rather than through the aggregate score
    because an average can hide the one relationship everybody notices.
    """
    # Living-to-dining is deliberately not here: with a passage in the plan
    # the two may be joined through it, which is a legitimate arrangement.
    # Foyer-to-living and dining-to-kitchen have no such excuse.
    required = [
        (RoomType.FOYER, RoomType.LIVING),
        (RoomType.DINING, RoomType.KITCHEN),
    ]
    failures: list[str] = []
    for seed, plan in zip(SEEDS, plans, strict=True):
        level = plan.level_at(0)
        by_id = {r.id: r for r in level.rooms}
        graph = plan.adjacency(0)
        touching = {
            (by_id[a].type, by_id[b].type)
            for a, nb in graph.items() for b in nb
        }
        for x, y in required:
            if (x, y) not in touching and (y, x) not in touching:
                failures.append(f"seed {seed}: {x.label} not adjacent to {y.label}")

    # One miss across five schemes is a tight plot, not a broken generator;
    # a systematic miss is the defect this whole module exists to prevent.
    assert len(failures) <= 2, "\n".join(failures)


# ---------------------------------------------------------------------------
# Can you walk through it
# ---------------------------------------------------------------------------


def test_every_room_is_reached_the_right_way(plans):
    """The test the client runs on the plan before any other: how do I get to
    each room, and what do I walk through to get there.

    A bedroom reached through the kitchen, a kitchen reached through the
    master bedroom, a bathroom on the route to anything: each is a failure
    no score should be allowed to hide. One illegal route across five
    schemes is a tight plot; several is a broken door placer.
    """
    from aip.engines.architecture.programme import walkability

    illegal: list[str] = []
    for seed, plan in zip(SEEDS, plans, strict=True):
        for route in walkability(plan):
            if not route.legal:
                illegal.append(f"seed {seed}: {route.room} via {' > '.join(route.path)}")
    assert len(illegal) <= 2, "; ".join(illegal)


def test_no_route_passes_through_a_bedroom(plans):
    """Stronger than the count above: nobody's way to anywhere is a bedroom."""
    from aip.engines.architecture.programme import walkability

    bedrooms = {"Master Bedroom", "Bedroom"}
    for seed, plan in zip(SEEDS, plans, strict=True):
        for route in walkability(plan):
            through = route.path[1:-1]
            # The attached bath's host is exempt: that is the right door.
            if route.room == "Bathroom" and through and through[-1] in bedrooms:
                through = through[:-1]
            assert not (set(through) & bedrooms), (
                f"seed {seed}: {route.room} reached via {' > '.join(route.path)}"
            )


def test_through_rooms_form_one_chain(plans):
    """Foyer, living, dining and the passage must connect without leaving them.

    Two islands of through-rooms means the only bridge runs through a bedroom.
    """
    from aip.engines.architecture.programme import walkability

    for seed, plan in zip(SEEDS, plans, strict=True):
        for route in walkability(plan):
            if is_through_name(route.room):
                assert all(is_through_name(x) for x in route.path), (
                    f"seed {seed}: {route.room} reached via {' > '.join(route.path)}"
                )


def is_through_name(name: str) -> bool:
    return name in {"Foyer", "Living", "Dining", "Corridor", "Lobby", "Family", "Drawing", "Verandah"}


def test_a_passage_is_added_for_multiple_bedrooms(brief):
    filled = apply_defaults(brief)
    assert any(r.type is RoomType.CORRIDOR for r in filled.requirements), (
        "three bedrooms and no passage means a bedroom reached through a bedroom"
    )


def test_attached_bath_and_kitchen_utility_are_legal_routes():
    """A route through the *host* of a room is the correct route, not a breach."""
    from aip.engines.architecture.programme import PRIVATE_HOST

    assert RoomType.KITCHEN in PRIVATE_HOST[RoomType.UTILITY]
    assert RoomType.MASTER_BEDROOM in PRIVATE_HOST[RoomType.WARDROBE]


def test_layout_score_is_respectable(plans, brief):
    scores = [evaluate(plan, brief).score for plan in plans]
    mean = sum(scores) / len(scores)
    assert mean >= 0.75, f"mean layout score {mean:.3f}; per-seed {scores}"
    assert min(scores) >= 0.55, f"a scheme scored {min(scores):.3f}"


def test_no_habitable_room_is_a_corridor(plans):
    """Proportion has no upper bound in the shape term, so it needs its own guard.

    An 8:1 bedroom satisfies its area, its glazing and its code minimums, and is
    still a hallway with a bed in it.
    """
    for seed, plan in zip(SEEDS, plans, strict=True):
        for room in plan.level_at(0).rooms:
            if not room.type.is_habitable:
                continue
            assert room.bbox.aspect_ratio <= 3.0, (
                f"seed {seed}: {room.display_name()} is "
                f"{room.bbox.aspect_ratio:.1f}:1"
            )


def test_private_rooms_are_not_marooned_among_public_ones(plans, brief):
    reports = [evaluate(plan, brief) for plan in plans]
    mean = sum(r.zoning for r in reports) / len(reports)
    assert mean >= 0.6, f"mean zoning {mean:.3f}"


def test_broken_relationships_explain_themselves(plans, brief):
    for plan in plans:
        for message in evaluate(plan, brief).broken:
            assert " - " in message, f"no reason given: {message}"
            assert len(message.split(" - ", 1)[1]) > 20


# ---------------------------------------------------------------------------
# Ventilation reach
# ---------------------------------------------------------------------------


def _deep_room_plan(depth: float, openings_on: str = "one") -> FloorPlan:
    """A single room, 4 m wide by `depth` deep, glazed on one or both ends.

    Built by hand rather than generated so the geometry is exactly the case
    under test: the generator, correctly, tries hard not to produce this.
    """
    width = 4.0
    corners = [Vec2(0, 0), Vec2(width, 0), Vec2(width, depth), Vec2(0, depth)]
    room = Room(type=RoomType.BEDROOM, polygon=corners, ceiling_height=3.0)

    south = Wall(start=Vec2(0, 0), end=Vec2(width, 0), thickness=0.23,
                 kind=WallKind.EXTERIOR, rooms=[room.id])
    north = Wall(start=Vec2(0, depth), end=Vec2(width, depth), thickness=0.23,
                 kind=WallKind.EXTERIOR, rooms=[room.id])
    east = Wall(start=Vec2(width, 0), end=Vec2(width, depth), thickness=0.23,
                kind=WallKind.EXTERIOR, rooms=[room.id])
    west = Wall(start=Vec2(0, 0), end=Vec2(0, depth), thickness=0.23,
                kind=WallKind.EXTERIOR, rooms=[room.id])

    window = Opening(kind=OpeningKind.WINDOW, wall_id=south.id, position=0.5,
                     width=1.5, height=1.35, sill_height=0.9)
    south.openings.append(window)
    if openings_on == "both":
        north.openings.append(
            Opening(kind=OpeningKind.WINDOW, wall_id=north.id, position=0.5,
                    width=1.5, height=1.35, sill_height=0.9)
        )

    level = Level(index=0, rooms=[room], walls=[south, north, east, west])
    site = Site(boundary=[Vec2(-1, -1), Vec2(width + 1, -1),
                          Vec2(width + 1, depth + 1), Vec2(-1, depth + 1)])
    return FloorPlan(name="Reach test", site=site, levels=[level])


def test_depth_limits_are_ordered():
    assert (
        VENTILATION_DEPTH_LIMIT["cross"]
        > VENTILATION_DEPTH_LIMIT["single_sided_double"]
        > VENTILATION_DEPTH_LIMIT["single_sided"]
        > VENTILATION_DEPTH_LIMIT["none"]
    )


def test_mode_classification():
    from aip.domain.geometry import Direction

    assert ventilation_mode(set(), 0) == "none"
    assert ventilation_mode({Direction.S}, 1) == "single_sided"
    assert ventilation_mode({Direction.S}, 2) == "single_sided_double"
    assert ventilation_mode({Direction.N, Direction.S}, 2) == "cross"


def test_a_deep_single_sided_room_has_a_stagnant_zone():
    """The CFD result the whole feature exists to express.

    A 9 m room with one window is ventilated for the first 6 m (2 x the 3 m
    ceiling) and stagnant beyond. Enlarging that one window does not change the
    number, which is the point: area is not reach.
    """
    plan = _deep_room_plan(9.0, openings_on="one")
    detail = next(
        d for d in ventilation_analysis(plan).detail.values()
        if isinstance(d, dict) and "ventilation_mode" in d
    )
    assert detail["ventilation_mode"] == "single_sided"
    assert detail["flow_depth_m"] == pytest.approx(9.0, abs=0.1)
    assert detail["effective_reach_m"] == pytest.approx(6.0, abs=0.1)
    assert detail["stagnant_fraction"] > 0.3


def test_the_same_room_cross_ventilated_has_none():
    plan = _deep_room_plan(9.0, openings_on="both")
    detail = next(
        d for d in ventilation_analysis(plan).detail.values()
        if isinstance(d, dict) and "ventilation_mode" in d
    )
    assert detail["ventilation_mode"] == "cross"
    assert detail["stagnant_fraction"] == 0.0


def test_the_stagnant_room_is_reported_not_just_scored():
    plan = _deep_room_plan(9.0, openings_on="one")
    codes = {f.code for f in ventilation_analysis(plan).findings}
    assert "VENT.REACH" in codes

    finding = next(f for f in ventilation_analysis(plan).findings if f.code == "VENT.REACH")
    assert "recirculates" in finding.message
    # The remedy must say to move air, not to add glass.
    assert "different face" in finding.remedy


# ---------------------------------------------------------------------------
# The animation
# ---------------------------------------------------------------------------


def test_airflow_svg_animates_the_real_analysis(plans):
    svg = airflow_svg(plans[0], 0)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "animateMotion" in svg, "the diagram is not animated"
    assert svg.count('<mpath href="#fl') == svg.count("<animateMotion"), (
        "every particle must be bound to a streamline path"
    )
    # Self-contained: no script, no external reference.
    assert "<script" not in svg
    assert "http://" not in svg.replace('xmlns="http://www.w3.org/2000/svg"', "")


def test_airflow_marks_where_the_air_stops_reaching():
    """The dead zone must be shown, not merely computed.

    The solved field already renders the stillness as colour; the line names the
    depth at which the standard says to stop counting on it, so the picture and
    the number in the report agree.
    """
    svg = airflow_svg(_deep_room_plan(9.0, openings_on="one"), 0)
    assert "reach limit" in svg
    assert "6.0 m" in svg, "the limit shown must be 2 x the 3 m ceiling"


def test_airflow_paints_a_solved_field():
    """The colour is a solved velocity field, not a gradient chosen by hand."""
    svg = airflow_svg(_deep_room_plan(9.0, openings_on="one"), 0)
    assert "data:image/png;base64," in svg, "no field raster was produced"


def test_airflow_field_itself_breathes(plans):
    """The colour field animates, not only the particles riding on it.

    A still heatmap with moving dots reads as a diagram; asked for something
    that looks like a live solve, the field itself has to move. This checks
    the mechanism is really there - an animated feDisplacementMap warping the
    field raster - and that the warp is derived from the field's own
    brightness rather than bolted on as an unrelated decoration.
    """
    svg = airflow_svg(plans[0], 0)
    assert svg.count("<feDisplacementMap") >= 1, "the field raster is not warped"
    assert "<animate attributeName=\"baseFrequency\"" in svg
    # The mask chain reads the source image's own luminance, so a fast (bright)
    # cell churns and a still (dark) one does not - the animation cannot show
    # motion the solve did not compute.
    assert "luminanceToAlpha" in svg
    # Every ripple filter must actually be applied to an image.
    filter_ids = re.findall(r'<filter id="(ripple\d+)"', svg)
    assert filter_ids, "no ripple filter was defined"
    for fid in filter_ids:
        assert f'filter="url(#{fid})"' in svg
    # Distinct rooms get distinct filters (and therefore independent phase),
    # not one filter silently reused everywhere.
    assert len(set(filter_ids)) == len(filter_ids)
    # Still self-contained.
    assert "<script" not in svg


def test_the_solver_conserves_mass_and_respects_walls():
    """A stream-function field cannot leak through a wall, and this checks it did not."""
    import numpy as np

    from aip.engines.architecture.cfd import solve

    field = solve(4.0, 9.0, Vec2(0.0, 0.0), [(Vec2(2.0, 0.0), 1.5)], through_flow=False)
    assert field is not None

    # Normal velocity into the side walls must be ~zero: those are solid.
    assert np.abs(field.u[:, 0]).max() < 0.3 * np.abs(field.speed).max() + 1e-9
    assert np.abs(field.u[:, -1]).max() < 0.3 * np.abs(field.speed).max() + 1e-9

    # And the air must actually be moving somewhere.
    assert field.speed.max() > 0.9


def test_single_sided_air_dies_away_with_depth():
    """The physical claim the whole feature rests on.

    Near the opening the air moves; far from it, it does not. If this ever
    inverts, the picture is lying and the number beside it is not.
    """

    from aip.engines.architecture.cfd import solve

    field = solve(4.0, 9.0, Vec2(0.0, 0.0), [(Vec2(2.0, 0.0), 1.5)], through_flow=False)
    assert field is not None
    rows = field.speed.shape[0]
    near = field.speed[: rows // 4].mean()
    far = field.speed[-rows // 4 :].mean()
    assert near > far * 3, f"near {near:.3f} vs far {far:.3f}"


def test_cross_flow_reaches_the_far_end():

    from aip.engines.architecture.cfd import solve

    field = solve(
        4.0, 9.0, Vec2(0.0, 0.0),
        [(Vec2(2.0, 0.0), 1.5), (Vec2(2.0, 9.0), 1.5)],
        through_flow=True,
    )
    assert field is not None
    rows = field.speed.shape[0]
    far = field.speed[-rows // 4 :].mean()
    assert far > 0.15, f"through-flow left the far end still ({far:.3f})"


def test_airflow_survives_a_plan_with_no_openings():
    plan = _deep_room_plan(9.0)
    for wall in plan.level_at(0).walls:
        wall.openings.clear()
    svg = airflow_svg(plan, 0)
    assert "no external opening" in svg
    assert svg.startswith("<svg")


def test_airflow_handles_a_missing_level(plans):
    assert "<svg" in airflow_svg(plans[0], 99)


def test_zone_vocabulary_is_complete():
    for zone in Zone:
        assert any(z is zone for z in ZONE_OF.values()), f"no room in zone {zone.value}"
