"""The multi-agent layer: consensus arithmetic, the router, and zero cost."""

from __future__ import annotations

import pytest

from aip.agents.base import Critique, Finding, Severity
from aip.agents.consensus import (
    CalibrationLedger,
    Candidate,
    CriticCalibration,
    borda_scores,
    dominates,
    pareto_front,
    reach_consensus,
    weighted_axis_scores,
)


def _critique(critic: str, axis: str, score: float, *, analytical=True,
              confidence=0.9, findings=None) -> Critique:
    return Critique(
        critic_id=critic, axis=axis, score=score, confidence=confidence,
        analytical=analytical, findings=findings or [],
    )


def _candidate(cid: str, scores: dict[str, float], findings=None) -> Candidate:
    return Candidate(
        id=cid, artifact=object(), origin=cid,
        critiques=[_critique(f"critic.{a}", a, s) for a, s in scores.items()]
                  + ([_critique("critic.blocker", "compliance", 0.1, findings=findings)]
                     if findings else []),
    )


# ══ Pareto ═════════════════════════════════════════════════════════════


def test_dominance_requires_no_worse_and_one_better():
    axes = ["a", "b"]
    assert dominates({"a": 0.8, "b": 0.7}, {"a": 0.7, "b": 0.7}, axes)
    assert not dominates({"a": 0.8, "b": 0.6}, {"a": 0.7, "b": 0.7}, axes)   # trade-off
    assert not dominates({"a": 0.7, "b": 0.7}, {"a": 0.7, "b": 0.7}, axes)   # equal


def test_pareto_front_keeps_genuine_tradeoffs():
    """The step a weighted sum would destroy.

    B is better on daylight, C on cost. Neither dominates, so both must survive
    to the ranking; A is worse on both and must be removed.
    """
    a = _candidate("A", {"daylight": 0.4, "cost": 0.4})
    b = _candidate("B", {"daylight": 0.9, "cost": 0.5})
    c = _candidate("C", {"daylight": 0.5, "cost": 0.9})

    front, dominated = pareto_front([a, b, c], ["daylight", "cost"])
    assert {x.id for x in front} == {"B", "C"}
    assert [x.id for x in dominated] == ["A"]


# ══ Admissibility ══════════════════════════════════════════════════════


def test_critical_finding_disqualifies_regardless_of_score():
    """No amount of aesthetic merit buys a way past a building code."""
    breach = Finding(code="NBC.X", severity=Severity.CRITICAL, message="setback breach")
    excellent_but_illegal = _candidate("illegal", {"daylight": 0.99, "cost": 0.99}, findings=[breach])
    mediocre_but_legal = _candidate("legal", {"daylight": 0.55, "cost": 0.55})

    result = reach_consensus([excellent_but_illegal, mediocre_but_legal])
    assert result.winner_id == "legal"
    assert len(result.disqualified) == 1
    assert not result.relaxed_admissibility


def test_all_inadmissible_relaxes_and_says_so():
    """Returning nothing helps nobody - but the warning must be unmissable."""
    breach = Finding(code="NBC.X", severity=Severity.CRITICAL, message="breach")
    a = _candidate("A", {"daylight": 0.6}, findings=[breach])
    b = _candidate("B", {"daylight": 0.4}, findings=[breach, breach])

    result = reach_consensus([a, b])
    assert result.relaxed_admissibility
    assert result.winner_id == "A"          # the least non-compliant
    assert "WARNING" in result.explanation
    assert not result.is_confident


# ══ Borda and utility ══════════════════════════════════════════════════


def test_borda_is_ordinal_and_normalised():
    a = _candidate("A", {"x": 0.9, "y": 0.9})
    b = _candidate("B", {"x": 0.5, "y": 0.5})
    scores = borda_scores([a, b], CalibrationLedger(), {"x": 0.5, "y": 0.5})
    assert scores["A"] > scores["B"]
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_borda_shares_points_across_ties():
    """Ties must not be broken by insertion order."""
    a = _candidate("A", {"x": 0.7})
    b = _candidate("B", {"x": 0.7})
    scores = borda_scores([a, b], CalibrationLedger(), {"x": 1.0})
    assert scores["A"] == pytest.approx(scores["B"])


def test_borda_is_robust_to_a_miscalibrated_critic():
    """A critic well-ordered but badly scaled must not distort the ranking.

    This is why the consensus blends an ordinal view with the cardinal one:
    LLM critics are routinely miscalibrated in absolute terms while still
    ranking correctly.
    """
    good = Candidate(id="good", artifact=object(), critiques=[
        _critique("c1", "x", 0.62), _critique("c2", "y", 0.90),
    ])
    poor = Candidate(id="poor", artifact=object(), critiques=[
        _critique("c1", "x", 0.60), _critique("c2", "y", 0.20),
    ])
    result = reach_consensus([good, poor], priorities={"x": 0.5, "y": 0.5})
    assert result.winner_id == "good"


# ══ Reliability weighting ══════════════════════════════════════════════


def test_calibration_moves_toward_accuracy():
    cal = CriticCalibration("c", reliability=0.8)
    for _ in range(25):
        cal.observe(predicted=0.9, actual=0.9)
    accurate = cal.reliability

    cal2 = CriticCalibration("c", reliability=0.8)
    for _ in range(25):
        cal2.observe(predicted=0.9, actual=0.1)
    inaccurate = cal2.reliability

    assert accurate > 0.8 > inaccurate
    assert 0.15 <= inaccurate <= 0.99        # never fully silenced


def test_unreliable_critic_loses_influence():
    ledger = CalibrationLedger()
    for _ in range(30):
        ledger.observe("critic.noisy", predicted=0.95, actual=0.05)

    candidate = Candidate(id="X", artifact=object(), critiques=[
        _critique("critic.noisy", "x", 1.0),
        _critique("critic.solid", "x", 0.2),
    ])
    weighted = weighted_axis_scores(candidate, ledger, {"x": 1.0})
    # The trusted critic must pull the mean well below the midpoint.
    assert weighted["x"] < 0.5


def test_degraded_critique_is_heavily_discounted():
    candidate = Candidate(id="X", artifact=object(), critiques=[
        Critique(critic_id="a", axis="x", score=1.0, analytical=False, degraded=True),
        Critique(critic_id="b", axis="x", score=0.2, analytical=True),
    ])
    weighted = weighted_axis_scores(candidate, CalibrationLedger(), {"x": 1.0})
    assert weighted["x"] < 0.45


# ══ Agreement ══════════════════════════════════════════════════════════


def test_disagreement_is_surfaced_not_averaged():
    split = Candidate(id="split", artifact=object(), critiques=[
        _critique("c1", "aesthetics", 0.95, analytical=False),
        _critique("c2", "aesthetics", 0.15, analytical=False),
        _critique("c3", "daylight", 0.7),
    ])
    result = reach_consensus([split], priorities={"aesthetics": 0.5, "daylight": 0.5})
    assert "aesthetics" in result.contested_axes
    assert result.debate_triggered
    assert result.overall_agreement < 0.7


def test_agreement_is_high_when_critics_concur():
    agreed = Candidate(id="agreed", artifact=object(), critiques=[
        _critique("c1", "daylight", 0.72), _critique("c2", "daylight", 0.75),
        _critique("c3", "daylight", 0.70),
    ])
    result = reach_consensus([agreed], priorities={"daylight": 1.0})
    assert result.overall_agreement > 0.9
    assert not result.contested_axes


def test_consensus_explanation_is_written_for_a_human():
    result = reach_consensus([
        _candidate("A", {"daylight": 0.8, "cost": 0.6}),
        _candidate("B", {"daylight": 0.5, "cost": 0.9}),
    ])
    assert len(result.explanation) > 120
    assert "candidate" in result.explanation.lower()
    assert result.winner_id in {"A", "B"}


def test_consensus_requires_candidates():
    with pytest.raises(ValueError):
        reach_consensus([])


# ══ The router and the zero-cost invariant ═════════════════════════════


def test_json_extraction_survives_real_model_output():
    from aip.core.llm import extract_json

    cases = [
        '{"a": 1}',
        'Sure! ```json\n{"a": 1}\n```',
        '<think>let me reason</think>\n{"a": 1}',
        'Here you go: {"a": 1, "b": [2, 3,],}',
        "{'a': 1}",
        '{"a": 1',                        # truncated
        '{a: 1}',                         # bare key
    ]
    for raw in cases:
        assert extract_json(raw)["a"] == 1, raw


def test_suite_is_hermetic():
    """The suite must not reach a live provider, whatever is in `.env`.

    Without this the isolation is incidental rather than real: creating a `.env`
    silently turns every router test into a live API call. It still passes, so
    nothing alerts you - it just becomes slow, flaky, and starts consuming the
    developer's free-tier quota. This asserts the premise the whole suite rests
    on, which is that the analytical engines need no API at all.
    """
    from aip.core.config import get_settings

    settings = get_settings()
    assert settings.configured_providers() == [], (
        "the test suite is reaching live providers; "
        "conftest must call override_settings(hermetic_settings())"
    )
    assert settings.ollama_enabled is False


def test_disabled_ollama_is_not_probed():
    """`AuthStyle.NONE` must not short-circuit past the enabled switch."""
    from aip.core.config import hermetic_settings
    from aip.core.providers import PROVIDERS_BY_NAME

    ollama = PROVIDERS_BY_NAME["ollama"]
    assert ollama.is_available(hermetic_settings(ollama_enabled=False)) is False
    assert ollama.is_available(hermetic_settings(ollama_enabled=True)) is True


def test_truncated_json_is_recovered():
    """Every one of these shapes was produced by a live free-tier model.

    A model that hits its token ceiling severs the object wherever it happens to
    be: inside a string, after a key, after a colon, or inside an array. Losing
    the whole critique because the last field was cut is a needless failure -
    the score, which is what consensus actually consumes, already arrived.
    """
    from aip.core.llm import extract_json

    cases = [
        ('{\n  "score": 0.3,\n  "reasoning": "This scheme presents', 0.3),
        ('{"score": 0.7, "confidence": 0.8, "rationale"', 0.7),
        ('{"score": 0.9, "confidence": 0.5, "rationale":', 0.9),
        ('{"score": 0.4, "concerns": ["too narrow", "no cross vent', 0.4),
    ]
    for raw, expected in cases:
        assert extract_json(raw)["score"] == expected, raw


def test_renamed_keys_are_coerced_onto_the_schema():
    """`score_brief_fidelity` for `score` is a real observed model output."""
    from aip.core.llm import _coerce_keys

    fixed = _coerce_keys(
        {"score_brief_fidelity": 0.42, "reasoning": "the brief was not met"},
        ["score", "confidence", "rationale"],
    )
    assert fixed["score"] == 0.42
    assert fixed["rationale"] == "the brief was not met"


def test_coercion_leaves_correct_payloads_untouched():
    from aip.core.llm import _coerce_keys

    good = {"score": 0.5, "confidence": 0.9, "rationale": "fine"}
    assert _coerce_keys(dict(good), ["score", "confidence", "rationale"]) == good


def test_reasoning_traces_are_split_out():
    from aip.core.llm import split_reasoning

    text, trace = split_reasoning("<think>step one</think>The answer is 4.")
    assert text == "The answer is 4."
    assert "step one" in trace


def test_unterminated_reasoning_is_recovered():
    from aip.core.llm import split_reasoning

    text, trace = split_reasoning("Answer: 4 <think>ran out of budget")
    assert text.startswith("Answer: 4")
    assert "ran out" in trace


async def test_router_degrades_instead_of_raising():
    """With no provider reachable, the pipeline must continue - clearly labelled."""
    from aip.core.llm import LLMRouter, user

    response = await LLMRouter().complete([user("Describe this scheme.")])
    assert response.degraded
    assert response.provider == "offline"
    assert response.text
    assert response.cost_usd == 0.0


async def test_structured_output_falls_back_to_a_valid_shape():
    from pydantic import BaseModel, Field

    from aip.core.llm import LLMRouter, user

    class Verdict(BaseModel):
        score: float = Field(ge=0.0, le=1.0)
        rationale: str

    verdict, response = await LLMRouter().complete_model([user("Score it.")], Verdict)
    assert 0.0 <= verdict.score <= 1.0
    assert response.degraded


async def test_total_model_cost_is_exactly_zero():
    """The platform's headline economic claim, asserted rather than asserted-to."""
    from aip.core.llm import LLMRouter, user

    router = LLMRouter()
    for _ in range(5):
        await router.complete([user("anything")])
    assert router.ledger.total_cost_usd == 0.0
    assert router.ledger.summary()["total_cost_usd"] == 0.0


async def test_rate_limiter_enforces_the_free_tier_ceiling():
    from aip.core.llm import RateLimiter
    from aip.core.providers import Capability, ModelSpec

    model = ModelSpec("m", "p", frozenset({Capability.FAST}), 8192, 0.5, rpm=3, rpd=100)
    limiter = RateLimiter()
    assert [await limiter.try_acquire(model) for _ in range(5)] == [True, True, True, False, False]


def test_circuit_breaker_opens_and_recovers():
    from aip.core.llm import CircuitBreaker

    breaker = CircuitBreaker(threshold=2, base_cooldown=30.0)
    assert not breaker.is_open("groq")
    breaker.record_failure("groq")
    breaker.record_failure("groq")
    assert breaker.is_open("groq")
    breaker.record_success("groq")
    assert not breaker.is_open("groq")


def test_provider_registry_is_diverse_and_free():
    from aip.core.providers import PROVIDERS, all_models

    assert len(PROVIDERS) >= 8
    assert len(all_models()) >= 30
    for provider in PROVIDERS:
        assert provider.signup_url, f"{provider.name} has no signup URL"
        assert provider.free_tier_note, f"{provider.name} does not state its free tier"


def test_ensemble_selection_maximises_provider_diversity():
    """Critics drawn from one model family make correlated mistakes."""
    from aip.core.config import Settings
    from aip.core.providers import Capability, candidates_for, diversified

    settings = Settings(
        groq_api_key="x", google_api_key="y", cerebras_api_key="z", ollama_enabled=False
    )
    picked = diversified(candidates_for(Capability.REASONING, settings), 3)
    assert len({m.provider for m in picked}) == 3


def test_committee_covers_every_promised_axis():
    from aip.agents.critics import ALL_CRITICS, committee_charter

    axes = {c.axis for c in ALL_CRITICS}
    for required in ("daylight", "ventilation", "privacy", "circulation",
                     "accessibility", "compliance", "vastu", "cost", "structure"):
        assert required in axes, f"no critic owns '{required}'"

    charter = committee_charter()
    assert len(charter) == len(ALL_CRITICS)
    for entry in charter:
        assert entry["charter"], f"{entry['id']} has no charter"

    analytical = sum(1 for c in ALL_CRITICS if c.analytical)
    # The analytical majority is what anchors the committee to physical truth.
    assert analytical > len(ALL_CRITICS) / 2


def test_dead_model_does_not_disable_its_provider():
    """A withdrawn model id is not a provider outage.

    Free-tier catalogues churn: this project watched seven Groq ids and every
    OpenRouter ':free' variant disappear within a fortnight. Treating the
    resulting 404 as a provider failure tripped the circuit breaker and took the
    whole account offline over one stale entry, which then degraded every
    generative critic in the run.
    """
    from aip.core.llm import CircuitBreaker, DeadModels
    from aip.core.providers import Capability, ModelSpec

    gone = ModelSpec("withdrawn-model", "groq", frozenset({Capability.REASONING}), 8192, 0.9, 30, 100)
    alive = ModelSpec("still-here", "groq", frozenset({Capability.REASONING}), 8192, 0.8, 30, 100)

    dead = DeadModels()
    breaker = CircuitBreaker(threshold=2)

    dead.mark(gone, "http 404: model does not exist")
    dead.mark(gone, "http 404: model does not exist")     # idempotent

    assert dead.is_dead(gone)
    assert not dead.is_dead(alive)
    assert dead.names == ["groq/withdrawn-model"]
    # The provider must remain usable.
    assert not breaker.is_open("groq")


def test_model_unavailable_is_distinguishable():
    from aip.core.llm import LLMError, ModelUnavailable

    assert issubclass(ModelUnavailable, LLMError)
