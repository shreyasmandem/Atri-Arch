"""Shared fixtures.

Every test runs with no model provider configured. That is deliberate: it proves
the analytical half of the platform - geometry, building physics, code
compliance, Vastu reasoning and quantity takeoff - is genuinely independent of
any API, which is the whole basis of the zero-cost claim.
"""

from __future__ import annotations

import pytest

# The suite must run as if no model provider exists. That is not a convenience
# - it is the evidence for the platform's central claim, that every analytical
# capability works with no API at all. Achieving it by leaving environment
# variables unset is a trap: the moment a developer creates a `.env`, the suite
# starts calling live providers and silently becomes slow, flaky and
# quota-consuming while still passing. So isolation is stated explicitly.
from aip.core.config import hermetic_settings, override_settings  # noqa: E402

override_settings(hermetic_settings())

from aip.domain.brief import (  # noqa: E402
    Budget,
    ClientBrief,
    Occupant,
    RoomRequirement,
    StylePreference,
    VastuStance,
    default_residence_brief,
)
from aip.domain.geometry import Direction, Vec2  # noqa: E402
from aip.domain.plan import RoomType, Site  # noqa: E402
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator  # noqa: E402


@pytest.fixture(scope="session")
def brief() -> ClientBrief:
    return default_residence_brief()


@pytest.fixture(scope="session")
def plan(brief: ClientBrief):
    """One deterministic scheme, shared across the suite.

    Seeded so a failure is reproducible: a test that fails on a random plan
    tells you nothing you can act on.
    """
    generator = LayoutGenerator(brief, GeneratorConfig(population=36, generations=32, seed=17))
    plans = generator.generate(count=1)
    assert plans, "the generator produced no scheme"
    return plans[0]


@pytest.fixture(scope="session")
def plans(brief: ClientBrief):
    generator = LayoutGenerator(brief, GeneratorConfig(population=36, generations=32, seed=23))
    return generator.generate(count=3)


@pytest.fixture
def tight_brief() -> ClientBrief:
    """A brief that cannot be satisfied comfortably, to exercise failure paths."""
    return ClientBrief(
        project_name="Constrained site",
        site=Site(
            boundary=[Vec2(0, 0), Vec2(6, 0), Vec2(6, 9), Vec2(0, 9)],
            road_directions=[Direction.S],
            max_far=1.2,
            setback_front=1.0, setback_rear=0.6, setback_left=0.5, setback_right=0.5,
        ),
        requirements=[
            RoomRequirement(type=RoomType.LIVING, preferred_area=14.0),
            RoomRequirement(type=RoomType.KITCHEN, preferred_area=7.0),
            RoomRequirement(type=RoomType.MASTER_BEDROOM, preferred_area=12.0),
            RoomRequirement(type=RoomType.BATHROOM, preferred_area=4.0, needs_daylight=False),
        ],
        occupants=[Occupant(role="adult", count=2)],
        style=StylePreference(),
        budget=Budget(amount=2_200_000),
        vastu=VastuStance.BALANCED,
    )
