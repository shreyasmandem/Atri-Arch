"""What an audit of generated plans found wanting, held fixed: kitchens that
breathe, west windows shaded, and a toilet over the stove ranked as the fault it is."""

from __future__ import annotations

import pytest

from aip.api.schemas import SimpleBriefRequest
from aip.domain.plan import OpeningKind, RoomType
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator, _severity
from aip.engines.architecture.metrics import OPENABLE_FRACTION, daylight_analysis, ventilation_analysis


@pytest.fixture(scope="module")
def plans():
    out = []
    for road in ("N", "W"):
        req = SimpleBriefRequest(plot_width=12.19, plot_depth=18.29, levels=2, bedrooms=3, bathrooms=3, road_direction=road)
        out.append(LayoutGenerator(req.to_brief(), GeneratorConfig(seed=3)).generate(count=1)[0])
    return out


def test_a_kitchen_gets_a_window_that_meets_the_ventilation_rule(plans):
    for plan in plans:
        for lv in plan.levels:
            for room in lv.rooms:
                if room.type is not RoomType.KITCHEN:
                    continue
                glazed = [o for w in lv.walls if room.id in w.rooms for o in w.openings if o.kind is OpeningKind.WINDOW]
                assert glazed, "a kitchen has a window, not only a vent"
                openable = sum(o.area * OPENABLE_FRACTION.get(o.kind, 0.6) for o in glazed)
                assert openable >= room.area / 6 - 0.05
        assert not [f for f in ventilation_analysis(plan).findings if "Kitchen has" in f.message]


def test_west_windows_get_fins_and_lose_their_overheat_finding(plans):
    finned = [o for plan in plans for lv in plan.levels for w in lv.walls for o in w.openings if o.notes == "fins"]
    assert finned, "a west-facing room gets fins on its west window"
    for plan in plans:
        assert not [f for f in daylight_analysis(plan).findings if f.code == "DAY.OVERHEAT" and "W-facing" in f.message]


def test_a_toilet_over_the_kitchen_weighs_as_a_serious_fault():
    oversize = "level 0: Utility is 6 m², over the 5 m² a room of its kind needs"
    stacked = "level 1: Bathroom over the Kitchen"
    assert _severity([stacked]) > _severity([oversize])
