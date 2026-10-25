"""The committee's pick yields to a clean scheme when its own pick fails the guardrail."""

from types import SimpleNamespace

from aip.agents.consensus import ConsensusResult
from aip.agents.orchestrator import DesignPipeline


def _cand(cid: str, guardrail: list[str]):
    return SimpleNamespace(id=cid, artifact=SimpleNamespace(metadata={"guardrail": guardrail}))


def _consensus(winner: str, ids: list[str]) -> ConsensusResult:
    return ConsensusResult(
        winner_id=winner, winner_score=0.9,
        ranking=[{"candidate_id": i, "score": 0.9 - n * 0.1} for n, i in enumerate(ids)],
    )


def test_flawed_winner_gives_way_to_best_ranked_clean_scheme():
    cands = [_cand("a", ["level 0: Corridor is 0.5 m wide"]), _cand("b", []), _cand("c", [])]
    out = DesignPipeline._prefer_valid(cands, _consensus("a", ["a", "b", "c"]))
    assert out.winner_id == "b"
    assert out.ranking[0]["candidate_id"] == "b"


def test_clean_winner_is_kept():
    cands = [_cand("a", []), _cand("b", [])]
    c = _consensus("a", ["a", "b"])
    assert DesignPipeline._prefer_valid(cands, c).winner_id == "a"


def test_all_flawed_keeps_committee_pick():
    cands = [_cand("a", ["x"]), _cand("b", ["y"])]
    assert DesignPipeline._prefer_valid(cands, _consensus("a", ["a", "b"])).winner_id == "a"


def test_clean_candidate_outside_the_front_is_still_reachable():
    cands = [_cand("a", ["x"]), _cand("b", [])]
    assert DesignPipeline._prefer_valid(cands, _consensus("a", ["a"])).winner_id == "b"
