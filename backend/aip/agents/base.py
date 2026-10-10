"""Agent primitives.

The platform's central claim is that a *committee* of narrow, independently
grounded agents produces better and more defensible architecture than a single
large model asked to "design a house". This module defines the vocabulary that
makes such a committee auditable.

Two kinds of agent coexist and are treated identically by the consensus layer:

* **Analytical agents** compute their verdict from geometry, physics or codified
  rules. They are exact, instantaneous, free, and fully explainable. Daylight,
  ventilation, circulation, accessibility, Vastu and quantity takeoff all live
  here.
* **Generative agents** call a language or vision model for judgement that
  resists formalisation - aesthetic coherence, brief interpretation, narrative
  explanation.

Mixing them is the point. Analytical agents anchor the committee to physical
truth so that generative agents cannot hallucinate a design into acceptance, and
generative agents supply the judgement that rules alone cannot express.
"""

from __future__ import annotations

import abc
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from aip.core.llm import LLMRouter, get_router
from aip.core.logging import get_logger, log_event
from aip.domain.brief import ClientBrief

logger = get_logger("aip.agents")

TIn = TypeVar("TIn")
TOut = TypeVar("TOut")


class AgentRole(str, Enum):
    RETRIEVER = "retriever"      # gathers evidence from the corpus
    GENERATOR = "generator"      # proposes candidate artefacts
    CRITIC = "critic"            # scores a candidate on one axis
    REFINER = "refiner"          # repairs a candidate against critique
    ARBITER = "arbiter"          # selects among candidates
    EXPLAINER = "explainer"      # renders decisions into client language


class Severity(str, Enum):
    INFO = "info"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    CRITICAL = "critical"        # statutory or physical impossibility

    @property
    def weight(self) -> float:
        return {
            Severity.INFO: 0.0, Severity.MINOR: 0.15, Severity.MODERATE: 0.4,
            Severity.MAJOR: 0.75, Severity.CRITICAL: 1.0,
        }[self]

    @property
    def blocks_delivery(self) -> bool:
        return self is Severity.CRITICAL


class EvidenceKind(str, Enum):
    COMPUTED = "computed"        # derived from the geometry itself
    STANDARD = "standard"        # a building code / statutory clause
    SHASTRA = "shastra"          # a classical Vastu text
    CORPUS = "corpus"            # retrieved precedent or reference project
    MODEL = "model"              # a model's own assertion
    HISTORICAL = "historical"    # this firm's own past outcomes


class Evidence(BaseModel):
    """A citation. Every score in the platform must be traceable to one of these."""

    kind: EvidenceKind
    source: str
    detail: str = ""
    value: float | str | None = None
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    locator: str = ""            # room id, wall id, clause number, page

    def render(self) -> str:
        bits = [self.source]
        if self.locator:
            bits.append(f"({self.locator})")
        if self.detail:
            bits.append(f"- {self.detail}")
        return " ".join(bits)


class Finding(BaseModel):
    """A specific, located, actionable problem with a candidate design."""

    code: str                    # stable identifier, e.g. "NBC.3.2.1" or "VS.KITCHEN.SE"
    severity: Severity
    message: str
    target_id: str = ""          # room / wall / opening the finding attaches to
    target_label: str = ""
    metric: str = ""
    actual: float | str | None = None
    expected: float | str | None = None
    remedy: str = ""
    evidence: list[Evidence] = Field(default_factory=list)

    def render(self) -> str:
        where = f" [{self.target_label or self.target_id}]" if (self.target_label or self.target_id) else ""
        return f"{self.severity.value.upper()}{where}: {self.message}"


class Critique(BaseModel):
    """One critic's verdict on one candidate, along one axis."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    critic_id: str
    axis: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    rationale: str = ""
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    analytical: bool = True
    model_used: str = ""
    degraded: bool = False
    duration_ms: float = 0.0

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity.blocks_delivery]

    @property
    def is_blocking(self) -> bool:
        return bool(self.blocking_findings)

    @property
    def worst_severity(self) -> Severity:
        if not self.findings:
            return Severity.INFO
        return max(self.findings, key=lambda f: f.severity.weight).severity


@dataclass(slots=True)
class AgentContext:
    """Everything an agent is allowed to see.

    Passing one context object rather than loose arguments keeps the trace
    honest: if it is not in here, the agent could not have used it.
    """

    brief: ClientBrief
    trace_id: str = ""
    router: LLMRouter | None = None
    retrieved: list[Evidence] = field(default_factory=list)
    shared: dict[str, Any] = field(default_factory=dict)
    budget_seconds: float = 120.0
    allow_generative: bool = True

    def llm(self) -> LLMRouter:
        if self.router is None:
            self.router = get_router()
        return self.router

    def child(self, **overrides: Any) -> AgentContext:
        data = {
            "brief": self.brief,
            "trace_id": self.trace_id,
            "router": self.router,
            "retrieved": list(self.retrieved),
            "shared": dict(self.shared),
            "budget_seconds": self.budget_seconds,
            "allow_generative": self.allow_generative,
        }
        data.update(overrides)
        return AgentContext(**data)


@dataclass(slots=True)
class AgentResult(Generic[TOut]):
    agent_id: str
    role: AgentRole
    output: TOut | None
    ok: bool = True
    error: str = ""
    duration_ms: float = 0.0
    model_used: str = ""
    degraded: bool = False
    notes: list[str] = field(default_factory=list)


class Agent(abc.ABC, Generic[TIn, TOut]):
    """Base class for every agent in the platform."""

    #: Stable identifier used in traces, weights and the UI.
    id: str = "agent"
    #: Human-readable name shown to architects.
    name: str = "Agent"
    role: AgentRole = AgentRole.CRITIC
    #: True when the agent needs no model call - free, exact, always available.
    analytical: bool = True
    #: Short statement of what this agent is responsible for. Shown in the UI.
    charter: str = ""

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.instance_id = f"{self.id}#{uuid.uuid4().hex[:6]}"

    @abc.abstractmethod
    async def run(self, payload: TIn, ctx: AgentContext) -> TOut:
        """Do the work. Raise on failure; the executor records it."""

    async def execute(self, payload: TIn, ctx: AgentContext) -> AgentResult[TOut]:
        """Run with timing, error capture and structured logging."""
        started = time.perf_counter()
        try:
            output = await asyncio.wait_for(self.run(payload, ctx), timeout=ctx.budget_seconds)
        except TimeoutError:
            elapsed = (time.perf_counter() - started) * 1000
            log_event(logger, "agent.timeout", level=30, agent=self.id, ms=round(elapsed, 1))
            return AgentResult(self.id, self.role, None, ok=False, error="timeout", duration_ms=elapsed)
        except Exception as exc:  # noqa: BLE001 - a failing agent must not fail the run
            elapsed = (time.perf_counter() - started) * 1000
            log_event(
                logger, "agent.failed", level=40,
                agent=self.id, error=f"{type(exc).__name__}: {exc}", ms=round(elapsed, 1),
            )
            return AgentResult(
                self.id, self.role, None, ok=False,
                error=f"{type(exc).__name__}: {exc}", duration_ms=elapsed,
            )

        elapsed = (time.perf_counter() - started) * 1000
        log_event(logger, "agent.ok", agent=self.id, ms=round(elapsed, 1))
        return AgentResult(self.id, self.role, output, duration_ms=elapsed)


class CriticAgent(Agent[Any, Critique]):
    """An agent that scores a candidate along one named axis."""

    role = AgentRole.CRITIC
    axis: str = "general"
    #: Baseline trust. Adjusted at runtime by the calibration ledger.
    prior_reliability: float = 0.8

    def make_critique(
        self,
        score: float,
        *,
        rationale: str = "",
        findings: list[Finding] | None = None,
        evidence: list[Evidence] | None = None,
        suggestions: list[str] | None = None,
        confidence: float = 0.85,
        model_used: str = "",
        degraded: bool = False,
    ) -> Critique:
        return Critique(
            critic_id=self.id,
            axis=self.axis,
            score=max(0.0, min(1.0, score)),
            confidence=max(0.0, min(1.0, confidence)),
            rationale=rationale,
            findings=findings or [],
            evidence=evidence or [],
            suggestions=suggestions or [],
            analytical=self.analytical,
            model_used=model_used,
            degraded=degraded,
        )


async def run_agents(
    agents: list[Agent[Any, Any]],
    payload: Any,
    ctx: AgentContext,
    *,
    max_parallel: int = 8,
) -> list[AgentResult[Any]]:
    """Execute agents concurrently with a bounded fan-out.

    The bound matters: free tiers are rate-limited per minute, so an unbounded
    committee would spend its allowance on 429s. Analytical agents are exempt in
    practice because they never leave the process.
    """
    semaphore = asyncio.Semaphore(max_parallel)

    async def guarded(agent: Agent[Any, Any]) -> AgentResult[Any]:
        async with semaphore:
            return await agent.execute(payload, ctx)

    return list(await asyncio.gather(*(guarded(a) for a in agents)))


def collect_critiques(results: list[AgentResult[Any]]) -> list[Critique]:
    """Filter agent results down to the critiques that actually succeeded."""
    out: list[Critique] = []
    for res in results:
        if res.ok and isinstance(res.output, Critique):
            critique = res.output
            critique.duration_ms = res.duration_ms
            out.append(critique)
    return out
