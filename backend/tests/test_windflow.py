"""The whole-floor wind solve: mass is conserved and walls stop the air."""

from __future__ import annotations

from aip.domain.geometry import Direction, Vec2
from aip.domain.plan import FloorPlan, Level, Opening, OpeningKind, Room, RoomType, Site, Wall, WallKind
from aip.engines.architecture.windflow import solve_level


def _box_room(windows: list[tuple[str, float]]) -> FloorPlan:
    """A 5 x 4 m room with windows on the named faces."""
    room = Room(id="r1", name="Living", type=RoomType.LIVING,
                polygon=[Vec2(0, 0), Vec2(5, 0), Vec2(5, 4), Vec2(0, 4)])
    faces = {"S": ((0, 0), (5, 0)), "E": ((5, 0), (5, 4)), "N": ((5, 4), (0, 4)), "W": ((0, 4), (0, 0))}
    walls = []
    for face, (a, b) in faces.items():
        ops = [Opening(kind=OpeningKind.WINDOW, position=pos, width=1.2) for f, pos in windows if f == face]
        walls.append(Wall(start=Vec2(a[0], a[1]), end=Vec2(b[0], b[1]), kind=WallKind.EXTERIOR,
                          rooms=["r1"], openings=ops))
    site = Site(boundary=[Vec2(-5, -5), Vec2(10, -5), Vec2(10, 9), Vec2(-5, 9)])
    return FloorPlan(site=site, levels=[Level(index=0, rooms=[room], walls=walls)])


def test_cross_beats_single_sided_and_sealed_is_still():
    cross = solve_level(_box_room([("S", 0.5), ("N", 0.5)]), 0, wind=Direction.S)["rooms"][0]
    single = solve_level(_box_room([("S", 0.5)]), 0, wind=Direction.S)["rooms"][0]
    sealed = solve_level(_box_room([]), 0, wind=Direction.S)["rooms"][0]
    assert cross["ach"] > 3 * max(single["ach"], 0.1)
    assert cross["mode"] == "cross"
    assert sealed["ach"] == 0 and sealed["mode"] == "sealed"


def test_wind_parallel_to_the_openings_moves_less_air():
    head_on = solve_level(_box_room([("S", 0.5), ("N", 0.5)]), 0, wind=Direction.S)["rooms"][0]
    across = solve_level(_box_room([("S", 0.5), ("N", 0.5)]), 0, wind=Direction.E)["rooms"][0]
    assert head_on["ach"] > across["ach"]
