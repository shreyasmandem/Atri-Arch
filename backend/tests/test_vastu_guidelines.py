"""The guideline review's Vastu rules: present, measured, and live after an edit."""

from __future__ import annotations

from aip.domain.plan import RoomType
from aip.engines.vastu.engine import analyse_vastu, quick_vastu_score, vastu_changes
from aip.engines.vastu.knowledge import RULES, RULES_BY_ID, RuleCategory


def test_the_corpus_carries_the_reviewed_rules():
    assert len(RULES) >= 44
    for rid in ("VS.STACK.KITCHEN_TOILET", "VS.PUJA.AWAY_FROM_TOILET", "VS.ENTRANCE.STAIR_NOT_FACING",
                "VS.ENTRANCE.TOILET_NOT_FACING", "VS.MASTER.LARGEST", "VS.ENTRANCE.PADA", "VS.POOL.NORTH_EAST",
                "VS.BALCONY.NORTH_EAST", "VS.VERANDAH.NORTH_EAST", "VS.SITE.SEPTIC_NORTHWEST"):
        assert rid in RULES_BY_ID
    # Every rule cites where it comes from.
    assert all(r.citation for r in RULES)


def test_new_rules_are_measured_on_a_plan(plan):
    report = analyse_vastu(plan, 0.5)
    by_id = {v.rule_id: v for v in report.verdicts}
    for rid in ("VS.STACK.KITCHEN_TOILET", "VS.ENTRANCE.STAIR_NOT_FACING", "VS.ENTRANCE.TOILET_NOT_FACING",
                "VS.ENTRANCE.PADA", "VS.MASTER.LARGEST"):
        assert by_id[rid].assessable, rid
        assert 0.0 <= by_id[rid].compliance <= 1.0
    assert by_id["VS.ENTRANCE.PADA"].compliance in (1.0, 0.65, 0.2)
    # On-site items are listed for the builder, never scored.
    site = [v for v in report.verdicts if v.category == RuleCategory.SITE.value]
    assert site and all(not v.assessable and "site checklist" in v.reason_not_assessable for v in site)


def test_a_kitchen_under_a_toilet_is_caught(plans):
    multi = next((p for p in plans if len(p.levels) > 1), None)
    if multi is None:
        return
    kitchen = multi.first_room_of(RoomType.KITCHEN)
    upper = multi.levels[1]
    wet = next((r for r in upper.rooms if r.type in (RoomType.TOILET, RoomType.BATHROOM)), None)
    if kitchen is None or wet is None:
        return
    staged = multi.model_copy(deep=True)
    up = next(r for r in staged.levels[1].rooms if r.id == wet.id)
    up.polygon = [p for p in staged.first_room_of(RoomType.KITCHEN).polygon]      # put it right over the kitchen
    v = {x.rule_id: x for x in analyse_vastu(staged).verdicts}["VS.STACK.KITCHEN_TOILET"]
    assert v.assessable and v.compliance == 0.0


def test_an_edit_reports_what_it_changed_for_vastu(plan):
    from aip.engines.architecture.editor import apply_edits

    same = vastu_changes(analyse_vastu(plan), analyse_vastu(plan))
    assert same["delta"] == 0 and same["changes"] == []
    rooms = [r for r in plan.levels[0].rooms if r.type in (RoomType.KITCHEN, RoomType.BEDROOM, RoomType.MASTER_BEDROOM,
                                                          RoomType.PUJA, RoomType.DINING, RoomType.LIVING)]
    for a in rooms:
        for b in rooms:
            if a.id >= b.id:
                continue
            new, applied, _ = apply_edits(plan, [{"op": "swap", "a": a.id, "b": b.id}])
            if not applied:
                continue
            diff = vastu_changes(analyse_vastu(plan), analyse_vastu(new))
            if diff["changes"]:
                assert diff["delta"] == round(diff["score_after"] - diff["score_before"], 1)
                assert all("title" in c and "better" in c for c in diff["changes"])
                return


def test_the_optimiser_weighs_the_relations(plan):
    assert 0.0 <= quick_vastu_score(plan) <= 1.0
