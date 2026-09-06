"""The three reasoning components: knowledge graph, constraint reasoner,
consensus protocol - plus the CAD export that makes their output editable.

These are the parts of the platform that are claimed to be more than a wrapper
around a language model, so they are tested for the properties that claim rests
on: determinism, referential integrity, agreement with the cited corpus,
generalisation beyond it, and monotonic improvement under negotiation.
"""

from __future__ import annotations

import math

import pytest

from aip.agents.protocol import (
    ConsensusProtocol,
    ProtocolConfig,
    Severity,
    default_constraints,
    default_workers,
    negotiate,
)
from aip.domain.geometry import Direction
from aip.domain.plan import RoomType
from aip.engines.architecture.dxf import LAYERS, export_dxf, export_dxf_all_levels
from aip.engines.vastu.graph import (
    QUARTER_OF_DIRECTION,
    ROOM_ACTIVITIES,
    EdgeKind,
    NodeKind,
    build_graph,
)
from aip.engines.vastu.reasoner import VastuReasoner, get_reasoner

# ---------------------------------------------------------------------------
# The knowledge graph
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def graph():
    return build_graph()


@pytest.fixture(scope="module")
def reasoner():
    return get_reasoner()


def test_graph_is_referentially_intact(graph):
    """Every edge must land on a node that exists.

    A dangling edge is the failure mode that turns graph reasoning back into
    guesswork: the search silently loses a branch and the score shifts with no
    visible cause.
    """
    for node_id in list(graph._nodes):  # noqa: SLF001 - structural invariant
        for edge in graph.out_edges(node_id):
            assert graph.has(edge.source), edge
            assert graph.has(edge.target), edge


def test_graph_weights_are_normalised(graph):
    for node_id in list(graph._nodes):  # noqa: SLF001
        for edge in graph.out_edges(node_id):
            assert 0.0 < edge.weight <= 1.0, edge


def test_graph_is_deterministic():
    """Two independent builds must be identical, edge for edge."""
    build_graph.cache_clear()
    a = build_graph()
    build_graph.cache_clear()
    b = build_graph()
    build_graph.cache_clear()

    def signature(g):
        return sorted(
            (e.source, e.target, e.kind.value, round(e.weight, 6))
            for n in g._nodes  # noqa: SLF001
            for e in g.out_edges(n)
        )

    assert a.node_count == b.node_count
    assert signature(a) == signature(b)


def test_every_direction_belongs_to_a_quarter(graph):
    for direction in Direction:
        assert direction in QUARTER_OF_DIRECTION
        assert graph.has(QUARTER_OF_DIRECTION[direction])


def test_every_mapped_room_and_activity_exists(graph):
    for room_type, hosted in ROOM_ACTIVITIES.items():
        assert graph.has(f"room_{room_type.value}"), room_type
        for activity, _weight in hosted:
            assert graph.has(activity), (room_type, activity)


def test_graph_layers_are_populated(graph):
    for kind in NodeKind:
        assert graph.nodes_of(kind), f"no nodes of kind {kind.value}"


def test_paths_are_well_formed_chains(graph):
    paths = graph.paths("room_kitchen", "q_agneya", max_depth=5, max_paths=5)
    assert paths
    for path in paths:
        assert len(path.nodes) == len(path.edges) + 1
        for i, edge in enumerate(path.edges):
            assert edge.source == path.nodes[i]
            assert edge.target == path.nodes[i + 1]
        assert path.polarity in (-1, 1)
        rendered = path.render(graph)
        assert "-[" in rendered and "]->" in rendered


def test_polarity_flips_on_negative_edges(graph):
    """A chain crossing an OPPOSES or DEFILES edge must come out negative.

    This is the mechanism that lets the graph contradict an otherwise clean
    elemental derivation - a WC in the north-east - so it is worth pinning.
    """
    negative = {EdgeKind.OPPOSES, EdgeKind.DEFILES}
    for source, target in [("room_toilet", "q_ishanya"), ("room_home_theatre", "q_ishanya")]:
        paths = graph.paths(source, target, max_depth=5, max_paths=8)
        for path in paths:
            crossings = sum(1 for e in path.edges if e.kind in negative)
            assert path.polarity == (-1 if crossings % 2 else 1), path.render(graph)


# ---------------------------------------------------------------------------
# The constraint reasoner
# ---------------------------------------------------------------------------


#: Placements every classical text agrees on. If the reasoner cannot reproduce
#: these it does not matter how elegant the derivation machinery is.
CANONICAL = [
    (RoomType.KITCHEN, Direction.SE, "ideal"),
    (RoomType.KITCHEN, Direction.NE, "prohibited"),
    (RoomType.PUJA, Direction.NE, "ideal"),
    (RoomType.PUJA, Direction.SW, "prohibited"),
    (RoomType.MASTER_BEDROOM, Direction.SW, "ideal"),
    (RoomType.MASTER_BEDROOM, Direction.NE, "prohibited"),
    (RoomType.TOILET, Direction.NE, "prohibited"),
    (RoomType.LIVING, Direction.N, "ideal"),
    (RoomType.STORE, Direction.SW, "ideal"),
]


@pytest.mark.parametrize(("room", "direction", "expected"), CANONICAL)
def test_canonical_placements(reasoner, room, direction, expected):
    verdict = reasoner.evaluate(room, direction)
    assert verdict.verdict == expected, verdict.explanation


def test_reasoner_is_deterministic(reasoner):
    first = reasoner.evaluate(RoomType.KITCHEN, Direction.SE).to_dict()
    second = VastuReasoner().evaluate(RoomType.KITCHEN, Direction.SE).to_dict()
    assert first == second


def test_agreement_with_the_cited_corpus(reasoner):
    """Where a text speaks, the derivation should usually reach the same answer.

    Perfect agreement would be suspicious - it would mean the graph is only
    reading the assertions back. A single principled disagreement, reported
    rather than hidden, is the honest outcome.
    """
    agree = disagree = 0
    for room in RoomType:
        if not reasoner.graph.has(f"room_{room.value}"):
            continue
        for direction in Direction:
            verdict = reasoner.evaluate(room, direction)
            if verdict.agrees_with_text is True:
                agree += 1
            elif verdict.agrees_with_text is False:
                disagree += 1

    assert agree + disagree > 100, "the corpus should assert a substantial number of placements"
    assert agree / (agree + disagree) >= 0.95


def test_disagreements_are_disclosed_not_hidden(reasoner):
    """When derivation and text conflict, the text governs and the note appears."""
    conflicted = [
        reasoner.evaluate(room, d)
        for room in RoomType
        if reasoner.graph.has(f"room_{room.value}")
        for d in Direction
        if reasoner.evaluate(room, d).agrees_with_text is False
    ]
    for verdict in conflicted:
        assert "disagree" in verdict.explanation.lower()
        assert verdict.asserted in {"favour", "prohibit"}


def test_generalises_past_the_corpus(reasoner):
    """The point of the graph: verdicts for rooms no rule enumerates.

    A gym belongs in the airy north-west and a home theatre in a dark, heavy
    quarter. Neither is written down anywhere in the rule corpus; both are
    reached through activity and element.
    """
    expectations = {
        RoomType.GYM: {"NW", "WNW", "NNW"},
        RoomType.HOME_THEATRE: {"S", "SW", "W", "SSW", "WSW"},
        RoomType.HOME_OFFICE: {"NE", "E", "N"},
        RoomType.LAUNDRY: {"NW", "WNW", "NNW", "W"},
    }
    for room, acceptable in expectations.items():
        best = reasoner.best_directions(room, top=1)[0]
        assert best.derived, f"{room.value} should be derived, not asserted"
        assert best.direction in acceptable, f"{room.value} -> {best.direction}"
        assert best.derivations, "a derived verdict must carry its proof"


def test_derived_verdicts_carry_proof(reasoner):
    """The majority of derived verdicts must show their working."""
    total = with_proof = 0
    for room in RoomType:
        if not reasoner.graph.has(f"room_{room.value}"):
            continue
        for direction in Direction:
            verdict = reasoner.evaluate(room, direction)
            if verdict.derived:
                total += 1
                with_proof += bool(verdict.derivations)
    assert total > 300
    assert with_proof / total >= 0.75


def test_scores_and_confidence_stay_in_range(reasoner):
    for room in list(RoomType)[:12]:
        for direction in Direction:
            v = reasoner.evaluate(room, direction)
            assert 0.0 <= v.score <= 1.0
            assert 0.0 <= v.confidence <= 1.0
            assert 0.0 <= v.support <= 1.0
            assert 0.0 <= v.conflict <= 1.0
            assert v.explanation


def test_unmodelled_room_is_declared_not_guessed():
    """A room outside the graph must say so rather than invent a score."""
    graph = build_graph()
    missing = next(
        (r for r in RoomType if not graph.has(f"room_{r.value}")),
        None,
    )
    if missing is None:
        pytest.skip("every room type is modelled")
    verdict = VastuReasoner(graph).evaluate(missing, Direction.NE)
    assert verdict.verdict == "not modelled"
    assert verdict.confidence == 0.0
    assert "not represented" in verdict.explanation


def test_coverage_gain_is_real(reasoner):
    stats = reasoner.coverage()
    assert stats["placements_derivable_by_graph"] > stats["placements_asserted_by_text"]
    assert stats["coverage_gain"] > 2.0


# ---------------------------------------------------------------------------
# The consensus protocol
# ---------------------------------------------------------------------------


def test_constraint_set_is_coherent():
    constraints = default_constraints()
    ids = [c.id for c in constraints]
    assert len(ids) == len(set(ids)), "duplicate constraint id"
    assert any(c.severity is Severity.HARD for c in constraints)
    assert any(c.severity is Severity.SOFT for c in constraints)
    for c in constraints:
        assert c.owner, f"{c.id} has no owning agent"


def test_every_constraint_has_a_real_owner():
    """An owner that is not a worker orphans the constraint.

    The manager routes each open constraint to the worker whose name matches its
    owner. Name one that does not exist and the failure is never offered to
    anyone: the protocol reports it unresolved having never asked a single agent
    to try, which looks identical to a genuine deadlock.
    """
    workers = {w.name for w in default_workers()}
    for constraint in default_constraints():
        assert constraint.owner in workers, (
            f"{constraint.id} is owned by '{constraint.owner}', which is not a worker"
        )


def test_workers_are_distinct():
    workers = default_workers()
    names = [w.name for w in workers]
    assert len(names) == len(set(names))
    assert len(workers) >= 4


def test_measurement_is_total(plan, brief):
    protocol = ConsensusProtocol()
    results = protocol.measure(plan, brief)
    assert len(results) == len(protocol.constraints)
    for result in results:
        assert result.detail, f"{result.id} reported no detail"
        assert 0.0 <= result.value <= 1.0


def test_hard_constraints_dominate_the_aggregate():
    """A blocking failure must cost more than a soft one, or the manager will
    trade away a statutory breach to buy a cosmetic improvement."""
    protocol = ConsensusProtocol()
    from aip.agents.protocol import ConstraintResult

    hard_fail = [
        ConstraintResult(id="a", severity=Severity.HARD, satisfied=False, value=0.0,
                         detail="x", owner="w"),
        ConstraintResult(id="b", severity=Severity.SOFT, satisfied=True, value=1.0,
                         detail="x", owner="w"),
    ]
    soft_fail = [
        ConstraintResult(id="a", severity=Severity.HARD, satisfied=True, value=1.0,
                         detail="x", owner="w"),
        ConstraintResult(id="b", severity=Severity.SOFT, satisfied=False, value=0.0,
                         detail="x", owner="w"),
    ]
    assert protocol.aggregate(hard_fail) < protocol.aggregate(soft_fail)


def test_negotiation_terminates_and_never_regresses(plan, brief):
    """The core safety property of the loop.

    A negotiation that can leave the design worse than it started is not an
    optimiser, it is a random walk. Every accepted mutation must improve the
    aggregate, and hard failures must never increase.
    """
    protocol = ConsensusProtocol(config=ProtocolConfig(max_rounds=3, time_budget_seconds=45.0))
    before = protocol.aggregate(protocol.measure(plan, brief))

    result, transcript = protocol.run(plan, brief)

    assert transcript.outcome in {
        "satisfied", "converged", "converged_with_open_constraints", "exhausted",
    }
    assert transcript.final_score >= before - 1e-9, "the negotiation made the design worse"
    assert len(transcript.rounds) <= 3

    for rnd in transcript.rounds:
        assert rnd.hard_open_after <= rnd.hard_open_before
        for mutation in rnd.mutations:
            if mutation.accepted:
                assert mutation.delta > 0, f"accepted a non-improving mutation: {mutation}"

    assert result.id is not None


def test_every_round_reports_a_real_score(plan, brief):
    """No round may publish a placeholder score.

    A round that terminates early still has to close its own record. Leaving
    `score_after` at its zero default puts a transcript in front of the client
    showing the design collapsing to nought in the round where nothing was
    wrong with it.
    """
    protocol = ConsensusProtocol(config=ProtocolConfig(max_rounds=3, time_budget_seconds=45.0))
    _result, transcript = protocol.run(plan, brief)

    for rnd in transcript.rounds:
        assert rnd.score_after > 0.0, f"round {rnd.index} published a zero score"
        assert rnd.seconds >= 0.0
        assert rnd.phase_sequence, f"round {rnd.index} recorded no phases"
        if not rnd.mutations:
            # Nothing was applied, so the score cannot have moved.
            assert rnd.score_after == pytest.approx(rnd.score_before)


def test_negotiation_can_satisfy_a_dimension_breach(plan, brief):
    """A room below its statutory minimum width must actually get fixed.

    This is the class of failure local repair cannot touch: widening a room by
    nudging a wall steals the width from its neighbour, so the repair engine
    correctly refuses. Without a re-packing proposal the loop reports the breach
    open having exhausted its options, which satisfies the letter of "iterate
    until constraints are satisfied" only by never satisfying them.
    """
    protocol = ConsensusProtocol(config=ProtocolConfig(max_rounds=3, time_budget_seconds=60.0))
    result, transcript = protocol.run(plan, brief)

    after = protocol.measure(result, brief)
    assert not [c for c in after if c.blocking], (
        "hard constraints remain open: "
        + "; ".join(c.detail for c in after if c.blocking)
    )
    # `satisfied` additionally requires every *soft* constraint to hold, which is
    # not what this test is about: a Vastu or budget preference left open on a
    # tight brief is a legitimate reported trade-off, not a failure to negotiate.
    assert transcript.outcome in {"satisfied", "converged"}
    assert transcript.hard_open == 0
    assert transcript.final_score > transcript.rounds[0].score_before


def test_repack_is_reproducible(plan, brief):
    """Two negotiations of the same plan must reach the same design.

    An architect comparing the negotiated alternative against the original needs
    the alternative to still be there when they re-run it.
    """
    a, ta = ConsensusProtocol(config=ProtocolConfig(max_rounds=2)).run(plan, brief)
    b, tb = ConsensusProtocol(config=ProtocolConfig(max_rounds=2)).run(plan, brief)

    assert ta.outcome == tb.outcome
    assert ta.final_score == pytest.approx(tb.final_score)
    assert a.total_built_area == pytest.approx(b.total_built_area)
    assert [r.type for r in a.level_at(0).rooms] == [r.type for r in b.level_at(0).rooms]


def test_transcript_serialises_for_the_api(plan, brief):
    _result, transcript = negotiate(
        plan, brief, ProtocolConfig(max_rounds=2, time_budget_seconds=30.0)
    )
    payload = transcript.to_dict()

    assert payload["outcome"] == transcript.outcome
    assert payload["rounds"] == len(transcript.rounds)
    assert isinstance(payload["log"], list)
    for entry in payload["log"]:
        assert {"round", "phases", "hard_open", "score", "improved"} <= set(entry)
        for mutation in entry["mutations"]:
            assert {"worker", "for", "change", "accepted", "delta"} <= set(mutation)

    import json

    json.dumps(payload)  # must be transport-safe


def test_protocol_emits_phase_events(plan, brief):
    """The UI streams these; an unnamed phase would render as a blank step."""
    seen: list[str] = []
    ConsensusProtocol(config=ProtocolConfig(max_rounds=2, time_budget_seconds=30.0)).run(
        plan, brief, on_event=lambda phase, _detail: seen.append(phase)
    )
    assert "intake" in seen
    assert all(isinstance(p, str) and p for p in seen)


def test_time_budget_is_honoured(plan, brief):
    protocol = ConsensusProtocol(
        config=ProtocolConfig(max_rounds=50, time_budget_seconds=0.0)
    )
    _result, transcript = protocol.run(plan, brief)
    assert transcript.outcome in {"satisfied", "exhausted"}
    assert transcript.seconds < 30.0


# ---------------------------------------------------------------------------
# DXF export
# ---------------------------------------------------------------------------


def _pairs(text: str) -> list[tuple[str, str]]:
    lines = text.split("\n")
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def test_dxf_is_structurally_valid(plan):
    text = export_dxf(plan, 0)
    pairs = _pairs(text)

    assert pairs[0] == ("0", "SECTION")
    assert text.rstrip().endswith("EOF")

    for code, _value in pairs:
        if code.strip():
            assert code.strip().lstrip("-").isdigit(), f"non-numeric group code {code!r}"

    counts: dict[str, int] = {}
    for code, value in pairs:
        if code == "0":
            counts[value] = counts.get(value, 0) + 1

    assert counts["SECTION"] == counts["ENDSEC"] == 3
    assert counts["POLYLINE"] == counts["SEQEND"], "every polyline needs its terminator"
    assert counts.get("LINE", 0) > 0 and counts.get("TEXT", 0) > 0


def test_dxf_uses_the_conventional_layers(plan):
    text = export_dxf(plan, 0)
    used = {value for code, value in _pairs(text) if code == "8"}
    assert used <= set(LAYERS), f"unknown layer(s): {used - set(LAYERS)}"
    for required in ("A-WALL", "A-AREA", "A-ANNO"):
        assert required in used


def test_dxf_covers_every_level(plan):
    files = export_dxf_all_levels(plan)
    assert len(files) == len(plan.levels)
    for content in files.values():
        assert content.rstrip().endswith("EOF")


def test_dxf_handles_a_missing_level(plan):
    """An out-of-range level must produce a valid file, not a traceback."""
    text = export_dxf(plan, 99)
    assert text.rstrip().endswith("EOF")
    assert "NO LEVEL" in text


def test_dxf_reopens_in_a_cad_library(plan):
    """Read the file back with ezdxf and check the geometry survived.

    Validating our own writer with our own parser proves nothing. This asserts
    the file is what a third-party CAD reader thinks it is.
    """
    ezdxf = pytest.importorskip("ezdxf")

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plan.dxf"
        path.write_text(export_dxf(plan, 0), encoding="utf-8")
        doc = ezdxf.readfile(str(path))

    assert doc.dxfversion == "AC1009"  # R12
    assert doc.header["$INSUNITS"] == 6  # metres

    names = {layer.dxf.name for layer in doc.layers}
    assert set(LAYERS) <= names

    modelspace = doc.modelspace()
    level = plan.level_at(0)
    wall_polylines = [
        e for e in modelspace if e.dxftype() == "POLYLINE" and e.dxf.layer == "A-WALL"
    ]
    assert len(wall_polylines) == len(level.walls)

    for wall, polyline in zip(level.walls, wall_polylines, strict=True):
        points = [(v.dxf.location.x, v.dxf.location.y) for v in polyline.vertices]
        assert len(points) == 4 and polyline.is_closed
        sides = [math.dist(points[i], points[(i + 1) % 4]) for i in range(4)]
        assert abs(max(sides) - wall.length) < 1e-3
        assert abs(min(sides) - wall.thickness) < 1e-6

    labels = {e.dxf.text for e in modelspace if e.dxftype() == "TEXT"}
    for room in level.rooms:
        if min(room.bbox.width, room.bbox.height) >= 1.0:
            assert room.display_name().upper() in labels

    if plan.column_grid:
        columns = [e for e in modelspace if e.dxf.layer == "S-COLS"]
        assert len(columns) == plan.column_grid.column_count
