"""Direct edits to a finished plan: walls slide, rooms swap, names and ceilings change."""

from __future__ import annotations

import pytest

from aip.api.schemas import SimpleBriefRequest
from aip.domain.plan import RoomType
from aip.engines.architecture.editor import apply_edits, describe_rooms
from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator


@pytest.fixture(scope="module")
def plan():
    req = SimpleBriefRequest(plot_width=12, plot_depth=18, levels=2, bedrooms=3, bathrooms=3, road_direction="N")
    return LayoutGenerator(req.to_brief(), GeneratorConfig(seed=3)).generate(1)[0]


def _by(plan, name: str, level: int = 0):
    rooms = [r for r in describe_rooms(plan) if r["name"] == name and r["level"] == level]
    assert rooms, f"no {name} on level {level}"
    return rooms[0]


def test_resize_slides_one_wall_and_leaves_the_rest(plan):
    before = {r["id"]: r for r in describe_rooms(plan)}
    living = _by(plan, "Living")
    new, applied, refused = apply_edits(plan, [{"op": "resize", "room": living["id"], "depth": -0.3}])
    assert applied and not refused
    assert new.id != plan.id and new.metadata["edited_from"] == plan.id
    after = {r["id"]: r for r in describe_rooms(new)}
    changed = [i for i in before if (before[i]["width"], before[i]["depth"]) != (after[i]["width"], after[i]["depth"])]
    assert living["id"] in changed and 1 <= len(changed) <= 3          # the room and the room it gave to
    assert after[living["id"]]["depth"] == pytest.approx(living["depth"] - 0.3, abs=0.02)
    # The original is untouched, so an edit can be undone.
    assert _by(plan, "Living")["depth"] == living["depth"]


def test_the_total_floor_area_is_conserved_by_a_shared_wall_slide(plan):
    living = _by(plan, "Living")
    new, applied, _ = apply_edits(plan, [{"op": "resize", "room": living["id"], "depth": -0.3}])
    if applied and "setback" not in applied[0]:
        total = lambda p: sum(r["area"] for r in describe_rooms(p) if r["level"] == 0)  # noqa: E731
        assert total(new) == pytest.approx(total(plan), abs=0.3)


def test_a_room_cannot_be_squeezed_below_what_it_is(plan):
    bath = next(r for r in describe_rooms(plan) if r["type"] == "bathroom" and r["level"] == 0)
    new, applied, refused = apply_edits(plan, [{"op": "resize", "room": bath["id"], "width": -3.0, "depth": -3.0}])
    assert not applied and refused
    assert new is plan


def test_the_stair_is_not_movable(plan):
    stair = next(r for r in describe_rooms(plan) if r["type"] == "staircase")
    assert stair["fixed"]
    _, applied, refused = apply_edits(plan, [{"op": "resize", "room": stair["id"], "width": 0.3}])
    assert not applied and refused


def test_swap_exchanges_two_rooms_on_one_floor(plan):
    beds = [r for r in describe_rooms(plan) if r["level"] == 1 and r["type"] in ("bedroom", "master_bedroom")]
    a, b = beds[0], beds[1]
    new, applied, refused = apply_edits(plan, [{"op": "swap", "a": a["id"], "b": b["id"]}])
    assert applied and not refused
    after = {r["id"]: r for r in describe_rooms(new)}
    assert (after[a["id"]]["width"], after[a["id"]]["depth"]) == (b["width"], b["depth"])
    # Walls, stairs and openings are rebuilt: the plan is still a whole one.
    assert all(lv.walls for lv in new.levels)
    assert any(o.kind.is_door for lv in new.levels for w in lv.walls for o in w.openings)


def test_swap_across_floors_is_refused(plan):
    ground = next(r for r in describe_rooms(plan) if r["level"] == 0 and not r["fixed"])
    upper = next(r for r in describe_rooms(plan) if r["level"] == 1 and not r["fixed"])
    _, applied, refused = apply_edits(plan, [{"op": "swap", "a": ground["id"], "b": upper["id"]}])
    assert not applied and "same floor" in refused[0]


def test_rename_retype_and_ceiling(plan):
    top_room = next(r for r in describe_rooms(plan) if r["level"] == 1 and r["type"] == "bedroom")
    new, applied, refused = apply_edits(plan, [
        {"op": "rename", "room": top_room["id"], "name": "Kids Den"},
        {"op": "ceiling", "room": top_room["id"], "height": 3.6},
    ])
    assert len(applied) == 2 and not refused
    got = next(r for r in describe_rooms(new) if r["id"] == top_room["id"])
    assert got["name"] == "Kids Den" and got["ceiling"] == 3.6
    study, applied, _ = apply_edits(plan, [{"op": "retype", "room": top_room["id"], "type": "study", "name": "Study"}])
    assert applied
    assert next(r for r in study.all_rooms if r.id == top_room["id"]).type is RoomType.STUDY


def test_a_ceiling_under_another_floor_is_limited(plan):
    ground = _by(plan, "Living")
    _, applied, refused = apply_edits(plan, [{"op": "ceiling", "room": ground["id"], "height": 3.6}])
    assert not applied and "at most" in refused[0]


def test_unknown_edits_and_ids_are_refused_not_raised(plan):
    _, applied, refused = apply_edits(plan, [{"op": "explode", "room": "x"}, {"op": "resize", "room": "nope", "width": 1}])
    assert not applied and len(refused) == 2


def test_the_editor_is_told_each_rooms_ceiling_limit(plan):
    """Heights the edit would refuse are known up front, so the editor can grey them out."""
    ground = _by(plan, "Living")
    top = next(r for r in describe_rooms(plan) if r["level"] == 1)
    assert ground["ceiling_max"] < 3.3 and top["ceiling_max"] >= 4.2
    _, applied, refused = apply_edits(plan, [{"op": "ceiling", "room": ground["id"], "height": ground["ceiling_max"]}])
    assert applied and not refused


def test_stepping_into_the_setback_keeps_every_other_rooms_windows(plan):
    """An outside wall stepped out leaves the house no longer a rectangle; the
    rooms beside it keep their outside walls and windows."""
    from aip.domain.plan import OpeningKind, WallKind

    def windows(p):
        out = {}
        for lv in p.levels:
            for w in lv.walls:
                for o in w.openings:
                    if o.kind is OpeningKind.WINDOW:
                        for rid in w.rooms:
                            out[rid] = out.get(rid, 0) + 1
        return out

    before = windows(plan)
    for r in describe_rooms(plan):
        if r["fixed"] or r["level"] != 0:
            continue
        new, applied, refused = apply_edits(plan, [{"op": "resize", "room": r["id"], "width": 0.3}])
        if applied and "into the setback" in applied[0]:
            after = windows(new)
            lost = [rid for rid, n in before.items() if n and not after.get(rid) and rid != r["id"]]
            assert not lost, f"widening the {r['name']} cost {lost} their windows"
            ext = [w for w in new.level_at(0).walls if w.kind is WallKind.EXTERIOR]
            assert len(ext) >= len([w for w in plan.level_at(0).walls if w.kind is WallKind.EXTERIOR])
            return
    pytest.skip("no room on this plan steps into its setback")
