"""Multi-Agent Consensus Protocol: a manager-worker orchestration state machine.

The pipeline in `orchestrator.py` runs each stage once. That is a chain, not a
protocol: if the selected scheme still breaches a hard constraint after its one
repair pass, the run ends anyway and the breach is reported rather than fixed.

This module implements the negotiation the reviewer asked for. A **Manager**
node holds the design state and routes it to specialist **Workers** -- Floorplan
Architect, Vastu Compliance, Cost Estimator, Interior Renderer -- which each
return proposed *mutations* to the design vector rather than opinions about it.
The manager applies them, re-measures, and loops. Iteration stops on one of
three conditions, all explicit:

1. **Satisfied** -- every hard constraint holds. The design is admissible.
2. **Converged** -- a round produced no measurable improvement, so further
   rounds would only burn budget.
3. **Exhausted** -- the round or wall-clock budget ran out with constraints
   still open, which is reported as a partial result and never as success.

Two properties make this a protocol rather than a loop:

* **Hard and soft constraints are separated.** A statutory breach or an
  unreachable room is *hard*: no amount of Vastu or aesthetic gain offsets it,
  and the machine will not terminate as "satisfied" while one stands. Vastu
  preference, cost target and daylight quality are *soft*: they are optimised,
  traded against each other, and reported with their residual.

* **Every transition is recorded.** The `Transcript` is the debate log: which
  worker proposed which mutation in which round, whether the manager accepted
  it, and what it did to each constraint. That record is what makes the
  negotiation auditable instead of asking the reader to trust that agents
  "collaborated".

Mutations are rejected when they make the aggregate worse, so the loop is
monotonic by construction and cannot talk itself into a poorer design.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aip.core.logging import get_logger, log_event
from aip.domain.brief import ClientBrief
from aip.domain.plan import FloorPlan, RoomType

logger = get_logger("aip.protocol")


class Phase(str, Enum):
    """States of the machine. The transition table is closed and total."""

    INTAKE = "intake"          # normalise the brief into a design vector
    PROPOSE = "propose"        # the architect worker emits candidate geometry
    MEASURE = "measure"        # every constraint is evaluated against the state
    NEGOTIATE = "negotiate"    # workers propose mutations for open constraints
    APPLY = "apply"            # the manager accepts or rejects each mutation
    DECIDE = "decide"          # satisfied / converged / exhausted, or loop again
    SETTLED = "settled"        # terminal


class Severity(str, Enum):
    HARD = "hard"    # must hold for the design to be admissible at all
    SOFT = "soft"    # optimised and traded off, reported with a residual


@dataclass(slots=True)
class Constraint:
    """One checkable requirement on the design state."""

    id: str
    severity: Severity
    description: str
    #: Returns (satisfied, measured_value, human_detail).
    check: Callable[[FloorPlan, ClientBrief], tuple[bool, float, str]]
    #: Which worker is competent to repair it.
    owner: str
    target: float = 1.0

    def evaluate(self, plan: FloorPlan, brief: ClientBrief) -> ConstraintResult:
        try:
            ok, value, detail = self.check(plan, brief)
        except Exception as exc:  # noqa: BLE001 - a broken check must not kill the run
            log_event(logger, "constraint.error", level=30, constraint=self.id, error=str(exc))
            return ConstraintResult(self.id, self.severity, False, 0.0,
                                    f"check failed: {type(exc).__name__}", self.owner)
        return ConstraintResult(self.id, self.severity, ok, value, detail, self.owner)


@dataclass(slots=True)
class ConstraintResult:
    id: str
    severity: Severity
    satisfied: bool
    value: float
    detail: str
    owner: str

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.HARD and not self.satisfied


@dataclass(slots=True)
class Mutation:
    """A concrete change one worker proposes to the design."""

    worker: str
    constraint_id: str
    description: str
    apply: Callable[[FloorPlan], FloorPlan]
    #: Set by the manager after evaluation.
    accepted: bool | None = None
    delta: float = 0.0


@dataclass(slots=True)
class Round:
    """One full pass of the machine, kept for the audit trail."""

    index: int
    phase_sequence: list[str] = field(default_factory=list)
    results: list[ConstraintResult] = field(default_factory=list)
    mutations: list[Mutation] = field(default_factory=list)
    #: Why an agent that owns an open constraint proposed nothing. Silence from
    #: the responsible agent is indistinguishable from the agent not running, so
    #: an agent that cannot help is required to say why.
    notes: list[str] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0
    hard_open_before: int = 0
    hard_open_after: int = 0
    seconds: float = 0.0

    @property
    def improved(self) -> bool:
        return (
            self.hard_open_after < self.hard_open_before
            or self.score_after > self.score_before + 1e-4
        )


@dataclass(slots=True)
class Transcript:
    """The negotiation record. This is the deliverable, not a side effect."""

    rounds: list[Round] = field(default_factory=list)
    outcome: str = ""
    final_score: float = 0.0
    hard_open: int = 0
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "rounds": len(self.rounds),
            "final_score": round(self.final_score, 4),
            "hard_constraints_open": self.hard_open,
            "seconds": round(self.seconds, 2),
            "log": [
                {
                    "round": r.index,
                    "phases": r.phase_sequence,
                    "hard_open": f"{r.hard_open_before} -> {r.hard_open_after}",
                    "score": f"{r.score_before:.4f} -> {r.score_after:.4f}",
                    "improved": r.improved,
                    "seconds": round(r.seconds, 2),
                    "unsatisfied": [
                        {"id": c.id, "severity": c.severity.value,
                         "owner": c.owner, "detail": c.detail}
                        for c in r.results if not c.satisfied
                    ],
                    "mutations": [
                        {"worker": m.worker, "for": m.constraint_id,
                         "change": m.description, "accepted": m.accepted,
                         "delta": round(m.delta, 4)}
                        for m in r.mutations
                    ],
                    "notes": list(r.notes),
                }
                for r in self.rounds
            ],
        }


# ---------------------------------------------------------------------------
# The constraint set
# ---------------------------------------------------------------------------


def _c_no_critical_breach(plan: FloorPlan, brief: ClientBrief):
    from aip.agents.base import Severity as FindingSeverity
    from aip.engines.architecture.codes import compliance_analysis

    report = compliance_analysis(plan, brief)
    critical = [f for f in report.findings if f.severity is FindingSeverity.CRITICAL]
    return (
        not critical,
        report.score,
        f"{len(critical)} critical statutory breach(es)" if critical
        else "no statutory breach",
    )


def _c_all_rooms_reachable(plan: FloorPlan, brief: ClientBrief):
    from collections import deque

    unreachable: list[str] = []
    for level in plan.levels:
        graph = plan.connectivity(level.index)
        if len(level.rooms) <= 1:
            continue
        start = next(iter(graph), None)
        if start is None:
            continue
        seen, queue = {start}, deque([start])
        while queue:
            node = queue.popleft()
            for nxt in graph.get(node, set()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        unreachable += [r.display_name() for r in level.rooms if r.id not in seen]
    ratio = 1.0 - len(unreachable) / max(1, len(plan.all_rooms))
    return (not unreachable, ratio,
            f"unreachable: {', '.join(unreachable[:4])}" if unreachable else "all rooms reachable")


def _c_habitable_daylight(plan: FloorPlan, brief: ClientBrief):
    from aip.engines.architecture.metrics import daylight_analysis

    report = daylight_analysis(plan)
    dark = [f for f in report.findings if f.code in {"DAY.NO_GLAZING", "DAY.UNDER_GLAZED"}]
    return (not dark, report.score,
            f"{len(dark)} room(s) below the statutory glazing ratio" if dark
            else "every habitable room is adequately glazed")


def _c_ventilation(plan: FloorPlan, brief: ClientBrief):
    from aip.engines.architecture.metrics import ventilation_analysis

    report = ventilation_analysis(plan)
    return report.score >= 0.55, report.score, f"ventilation index {report.score:.2f}"


def _c_vastu(plan: FloorPlan, brief: ClientBrief):
    """Measured with the knowledge graph, not the rule table.

    The Vastu worker chooses swaps by graph score, so the manager must grade
    them the same way. Measuring with one metric while optimising against
    another made every proposal look worse than the worker predicted, and the
    manager rejected fixes that were in fact improvements.
    """
    from aip.engines.vastu.reasoner import get_reasoner

    if not brief.vastu.is_constraining:
        return True, 1.0, "Vastu is advisory for this client"

    reasoner = get_reasoner()
    rooms = [r for r in plan.all_rooms if not r.type.is_outdoor]
    if not rooms:
        return True, 1.0, "no rooms to place"

    total = weight = 0.0
    for room in rooms:
        verdict = reasoner.evaluate(room.type, plan.direction_of_room(room))
        if verdict.verdict == "not modelled":
            continue
        w = max(0.25, room.area / 20.0)          # bigger rooms matter more
        total += w * verdict.score
        weight += w
    score = total / weight if weight else 0.5
    return score >= 0.62, score, f"graph placement score {score:.2f} over {len(rooms)} rooms"


def _c_budget(plan: FloorPlan, brief: ClientBrief):
    from aip.engines.cost.estimator import estimate_cost

    if not brief.budget.is_specified:
        return True, 1.0, "no budget was stated"
    estimate = estimate_cost(plan, brief, monte_carlo_runs=200)
    ratio = estimate.total / brief.budget.amount
    ok = ratio <= 1.0 + brief.budget.flexibility_percent / 100
    return ok, max(0.0, min(1.0, 2.0 - ratio)), f"{ratio:.0%} of budget"


def _c_accessibility(plan: FloorPlan, brief: ClientBrief):
    from aip.engines.architecture.metrics import accessibility_analysis

    report = accessibility_analysis(plan, brief)
    return report.score >= 0.7, report.score, f"accessibility index {report.score:.2f}"


def default_constraints() -> list[Constraint]:
    """The constraint set the manager negotiates over.

    The hard/soft split is the whole point. A statutory breach or a room nobody
    can walk into makes a design inadmissible no matter how well it scores
    elsewhere; a Vastu preference or a budget target is a goal to optimise. A
    protocol that treats all seven identically would happily trade a fire-escape
    violation for a better kitchen orientation.
    """
    return [
        Constraint("code.no_critical", Severity.HARD,
                   "No critical statutory breach (NBC 2016 / local DCR)",
                   _c_no_critical_breach, owner="floorplan_architect"),
        Constraint("circulation.reachable", Severity.HARD,
                   "Every room reachable through a door",
                   _c_all_rooms_reachable, owner="floorplan_architect"),
        Constraint("daylight.statutory", Severity.HARD,
                   "Habitable rooms meet the statutory glazing ratio",
                   _c_habitable_daylight, owner="floorplan_architect"),
        Constraint("ventilation.adequate", Severity.SOFT,
                   "Adequate cross ventilation", _c_ventilation,
                   owner="floorplan_architect", target=0.55),
        Constraint("vastu.compliant", Severity.SOFT,
                   "Vastu placement within the client's stance",
                   _c_vastu, owner="vastu_compliance", target=0.62),
        Constraint("cost.within_budget", Severity.SOFT,
                   "Estimate within the stated budget and flexibility",
                   _c_budget, owner="cost_estimator", target=1.0),
        # Clearances, door widths and step-free circulation are geometry, and
        # geometry is the architect's. Naming a non-existent owner here would
        # orphan the constraint: no worker would ever be asked to repair it, and
        # the protocol would report it open having never tried.
        Constraint("access.usable", Severity.SOFT,
                   "Accessible circulation and clearances",
                   _c_accessibility, owner="floorplan_architect", target=0.7),
    ]


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


class Worker:
    """A specialist that proposes mutations for the constraints it owns."""

    name: str = "worker"
    charter: str = ""

    def explain_inaction(
        self, plan: FloorPlan, brief: ClientBrief, open_results: list[ConstraintResult]
    ) -> str:
        """Why this worker had nothing to propose for a constraint it owns.

        Returning "" means the worker has no explanation worth recording. Any
        other string is carried into the transcript and the report.
        """
        return ""

    def propose(
        self, plan: FloorPlan, brief: ClientBrief, open_results: list[ConstraintResult]
    ) -> list[Mutation]:
        raise NotImplementedError


#: Fixed so a re-pack is reproducible: an architect who re-runs the negotiation
#: on the same brief must get the same alternative to compare against.
_REPACK_SEED = 4177


class FloorplanArchitect(Worker):
    name = "floorplan_architect"
    charter = ("Owns geometry. Repairs glazing, ventilation openings, door "
               "connectivity and clearances by editing the plan directly.")

    def propose(self, plan, brief, open_results):
        from aip.agents.base import Severity as FindingSeverity
        from aip.engines.architecture.codes import compliance_analysis
        from aip.engines.architecture.metrics import analyse_all
        from aip.engines.architecture.repair import repair_plan

        mine = [r for r in open_results if r.owner == self.name]
        if not mine:
            return []

        findings = []
        for report in analyse_all(plan, brief).values():
            findings += [f for f in report.findings
                         if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.MAJOR}]
        findings += [f for f in compliance_analysis(plan, brief).findings
                     if f.severity is FindingSeverity.CRITICAL]
        if not findings:
            return []

        def mutate(p: FloorPlan) -> FloorPlan:
            repaired, _applied = repair_plan(p, findings, brief)
            return repaired

        proposals = [Mutation(
            worker=self.name,
            constraint_id=",".join(r.id for r in mine),
            description=f"apply {len(findings)} targeted geometric repair(s)",
            apply=mutate,
        )]

        # A room below its statutory minimum width cannot be repaired locally.
        # Nudging a wall to widen it steals the width from its neighbour, and
        # the repair engine correctly refuses to trade one breach for another.
        # The only real fix is to re-pack the envelope, so the architect offers
        # that as a second, more expensive proposal. The manager still accepts it
        # only if re-measurement shows the whole design improved, so a re-pack
        # that fixes the width but wrecks the daylight is rejected like any other.
        # Offer a re-pack whenever a *hard* constraint this agent owns is still
        # open. Undersized rooms are the clearest case, but the same reasoning
        # covers a room that cannot be glazed to the statutory ratio because its
        # only external wall is too short: no local edit reaches it, and the
        # honest move is to try a different packing of the envelope rather than
        # report the breach unresolved having only tried one.
        undersized = self._undersized_rooms(plan, brief)
        if undersized or any(r.blocking for r in mine):
            proposals.append(self._repack(brief, undersized, mine))

        return proposals

    @staticmethod
    def _undersized_rooms(plan: FloorPlan, brief: ClientBrief) -> dict[RoomType, float]:
        """Room types whose narrowest instance is below the code minimum."""
        from aip.domain.brief import NBC_MIN_WIDTH

        deficient: dict[RoomType, float] = {}
        for level in plan.levels:
            for room in level.rooms:
                floor = NBC_MIN_WIDTH.get(room.type)
                if floor is None:
                    continue
                box = room.bbox
                width = min(box.width, box.height)
                if width < floor - 1e-6:
                    shortfall = (floor / max(width, 0.1)) ** 2
                    deficient[room.type] = max(deficient.get(room.type, 1.0), shortfall)
        return deficient

    def _repack(
        self,
        brief: ClientBrief,
        undersized: dict[RoomType, float],
        mine: list[ConstraintResult],
    ) -> Mutation:
        """Re-run generation with the starved rooms given more area to work with.

        Raising the target area is what actually moves the slicing tree: the
        optimiser allocates cells proportionally, so a room asking for more area
        is given a fatter cell rather than a longer, thinner one.
        """
        from aip.engines.architecture.layout import GeneratorConfig, LayoutGenerator

        names = ", ".join(sorted(t.label for t in undersized))
        what = (
            f"give {names} its statutory width" if undersized
            else "clear the remaining statutory breach"
        )

        def mutate(p: FloorPlan) -> FloorPlan:
            widened = brief.model_copy(deep=True)
            for requirement in widened.requirements:
                factor = undersized.get(requirement.type)
                if factor is None:
                    continue
                # Cap the increase: a room asking for four times its area will
                # simply starve everything else and fail a different constraint.
                factor = min(factor, 1.6)
                requirement.preferred_area = round(requirement.target_area * factor, 2)
                requirement.priority = min(2.0, requirement.priority + 0.5)

            generated = LayoutGenerator(
                widened,
                GeneratorConfig(population=28, generations=24, seed=_REPACK_SEED),
            ).generate(count=1)
            if not generated:
                return p
            repacked = generated[0]
            repacked.variant_of = p.id
            repacked.generation = p.generation + 1
            repacked.metadata.update(p.metadata)
            repacked.metadata["repacked_for"] = sorted(t.value for t in undersized)
            return repacked

        return Mutation(
            worker=self.name,
            constraint_id=",".join(r.id for r in mine),
            description=f"re-pack the envelope to {what}",
            apply=mutate,
        )


class VastuCompliance(Worker):
    name = "vastu_compliance"
    charter = ("Owns orientation. Consults the Vastu Knowledge Graph and proposes "
               "room reassignments that improve placement without moving walls.")

    def propose(self, plan, brief, open_results):
        if not any(r.owner == self.name for r in open_results):
            return []
        if not brief.vastu.is_constraining:
            return []

        from aip.domain.brief import NBC_MIN_AREAS, NBC_MIN_WIDTH
        from aip.engines.vastu.reasoner import get_reasoner

        reasoner = get_reasoner()
        level = plan.level_at(0)
        if level is None or len(level.rooms) < 2:
            return []

        # Find the pair whose swap the graph says gains the most. Swapping room
        # *identities* between two cells keeps the geometry - and therefore every
        # hard constraint the architect just satisfied - completely intact, which
        # is why the Vastu worker is allowed to act after the architect.
        best: tuple[float, str, str] | None = None
        for i, a in enumerate(level.rooms):
            for b in level.rooms[i + 1:]:
                if a.type is b.type:
                    continue
                da = plan.direction_of_room(a)
                db = plan.direction_of_room(b)
                now = (reasoner.evaluate(a.type, da).score
                       + reasoner.evaluate(b.type, db).score)
                swapped = (reasoner.evaluate(a.type, db).score
                           + reasoner.evaluate(b.type, da).score)
                gain = swapped - now
                if gain <= 0.12:
                    continue
                # Comparable size, or the programme breaks.
                if not (0.6 <= a.area / max(b.area, 0.1) <= 1.7):
                    continue
                # And the swap must not push either room below its statutory
                # minimum. Without this the worker cheerfully proposes putting a
                # living room in a 3.5 m2 puja cell: the manager measures it,
                # rejects it, and the round is wasted. A worker that proposes
                # only admissible mutations is the difference between a
                # negotiation and a guessing game.
                if (NBC_MIN_AREAS.get(b.type, 0.0) > a.area
                        or NBC_MIN_AREAS.get(a.type, 0.0) > b.area):
                    continue
                if (NBC_MIN_WIDTH.get(b.type, 0.0) > min(a.bbox.width, a.bbox.height)
                        or NBC_MIN_WIDTH.get(a.type, 0.0) > min(b.bbox.width, b.bbox.height)):
                    continue
                if best is None or gain > best[0]:
                    best = (gain, a.id, b.id)

        if best is None:
            return []
        gain, id_a, id_b = best

        def mutate(p: FloorPlan) -> FloorPlan:
            out = p.clone()
            ra = out.room_by_id(id_a)
            rb = out.room_by_id(id_b)
            if ra is None or rb is None:
                return out
            ra.type, rb.type = rb.type, ra.type
            ra.name, rb.name = rb.name, ra.name
            return out

        return [Mutation(
            worker=self.name,
            constraint_id="vastu.compliant",
            description=f"swap two room assignments for a projected +{gain:.2f} placement gain",
            apply=mutate,
        )]


class CostEstimator(Worker):
    name = "cost_estimator"
    charter = ("Owns money. When the estimate exceeds budget it proposes a "
               "specification step-down rather than shrinking the programme.")

    def explain_inaction(self, plan, brief, open_results):
        if not any(r.owner == self.name for r in open_results):
            return ""
        from aip.engines.cost.estimator import _infer_tier

        current = str(brief.metadata.get("finish_tier", "")).lower() or _infer_tier(brief).value
        if current == "economy":
            return (
                "cost_estimator: already specified at the lowest finish tier, so no "
                "further step-down exists. The overrun is driven by the size of the "
                "programme, not by the specification, and cannot be closed without "
                "the client either raising the budget or dropping accommodation."
            )
        return ""

    def propose(self, plan, brief, open_results):
        if not any(r.owner == self.name for r in open_results):
            return []
        current = str(brief.metadata.get("finish_tier", "")).lower()
        ladder = ["luxury", "premium", "standard", "economy"]
        if not current:
            from aip.engines.cost.estimator import _infer_tier
            current = _infer_tier(brief).value
        if current not in ladder or current == "economy":
            return []
        nxt = ladder[ladder.index(current) + 1]

        def mutate(p: FloorPlan) -> FloorPlan:
            out = p.clone()
            out.metadata["finish_tier"] = nxt
            return out

        return [Mutation(
            worker=self.name,
            constraint_id="cost.within_budget",
            description=f"step the specification down from {current} to {nxt}",
            apply=mutate,
        )]


class InteriorRenderer(Worker):
    name = "interior_renderer"
    charter = ("Owns habitability of the furnished room. Flags rooms whose "
               "solved furniture layout fails, so geometry can be revisited.")

    def propose(self, plan, brief, open_results):
        from aip.engines.interior.engine import design_interior

        scheme = design_interior(plan, brief)
        broken = [r for r in scheme.rooms
                  if any(u.get("essential") for u in r.unplaced)]
        if not broken:
            return []

        # This worker deliberately proposes no mutation: furniture cannot fix a
        # room that is too small, and pretending otherwise would let the machine
        # terminate on a design that does not work. It records the finding so
        # the transcript carries it to the architect and to the report.
        plan.metadata.setdefault("interior_blocked_rooms",
                                 [r.room_name for r in broken])
        return []


def default_workers() -> list[Worker]:
    return [FloorplanArchitect(), VastuCompliance(), CostEstimator(), InteriorRenderer()]


# ---------------------------------------------------------------------------
# The manager
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProtocolConfig:
    max_rounds: int = 4
    time_budget_seconds: float = 60.0
    #: Stop early when a round yields less than this aggregate gain.
    convergence_epsilon: float = 0.004


class ConsensusProtocol:
    """Manager node. Owns the state, routes to workers, decides termination."""

    def __init__(
        self,
        constraints: list[Constraint] | None = None,
        workers: list[Worker] | None = None,
        config: ProtocolConfig | None = None,
    ) -> None:
        self.constraints = constraints or default_constraints()
        self.workers = workers or default_workers()
        self.config = config or ProtocolConfig()

    # -- measurement -------------------------------------------------------

    def measure(self, plan: FloorPlan, brief: ClientBrief) -> list[ConstraintResult]:
        return [c.evaluate(plan, brief) for c in self.constraints]

    @staticmethod
    def aggregate(results: list[ConstraintResult]) -> float:
        """Scalar fitness. Hard constraints dominate by construction.

        Weighting hard constraints three times a soft one is not a tuning knob:
        it guarantees that no accumulation of soft gains can ever outrank fixing
        a breach, which is the property that makes the loop safe to run
        unattended.
        """
        if not results:
            return 0.0
        total = weight = 0.0
        for r in results:
            w = 3.0 if r.severity is Severity.HARD else 1.0
            total += w * (r.value if r.satisfied else r.value * 0.5)
            weight += w
        return total / weight

    # -- the machine -------------------------------------------------------

    def run(
        self,
        plan: FloorPlan,
        brief: ClientBrief,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> tuple[FloorPlan, Transcript]:
        """Negotiate until satisfied, converged, or out of budget."""
        started = time.perf_counter()
        transcript = Transcript()
        state = plan

        def emit(phase: Phase, detail: dict[str, Any]) -> None:
            if on_event:
                on_event(phase.value, detail)

        emit(Phase.INTAKE, {"constraints": len(self.constraints),
                            "workers": [w.name for w in self.workers]})

        results = self.measure(state, brief)
        score = self.aggregate(results)

        for index in range(1, self.config.max_rounds + 1):
            if time.perf_counter() - started > self.config.time_budget_seconds:
                transcript.outcome = "exhausted"
                break

            round_started = time.perf_counter()
            rnd = Round(index=index, score_before=score,
                        hard_open_before=sum(1 for r in results if r.blocking),
                        results=list(results))
            rnd.phase_sequence.append(Phase.MEASURE.value)

            if rnd.hard_open_before == 0 and all(r.satisfied for r in results):
                # Nothing to negotiate. The round still closes properly: leaving
                # score_after at its zero default would publish a transcript
                # showing the design collapsing to nought in the round where it
                # was in fact already correct.
                rnd.score_after = rnd.score_before
                rnd.hard_open_after = rnd.hard_open_before
                rnd.seconds = time.perf_counter() - round_started
                rnd.phase_sequence.append(Phase.SETTLED.value)
                transcript.outcome = "satisfied"
                transcript.rounds.append(rnd)
                break

            # NEGOTIATE: every worker sees the open constraints and proposes.
            rnd.phase_sequence.append(Phase.NEGOTIATE.value)
            open_results = [r for r in results if not r.satisfied]
            proposals: list[Mutation] = []
            for worker in self.workers:
                try:
                    offered = worker.propose(state, brief, open_results)
                except Exception as exc:  # noqa: BLE001
                    log_event(logger, "worker.failed", level=30,
                              worker=worker.name, error=str(exc))
                    continue

                proposals += offered
                if not offered:
                    try:
                        note = worker.explain_inaction(state, brief, open_results)
                    except Exception:  # noqa: BLE001
                        note = ""
                    if note:
                        rnd.notes.append(note)

            # APPLY: the manager accepts a mutation only if it measurably helps.
            rnd.phase_sequence.append(Phase.APPLY.value)
            for mutation in proposals:
                try:
                    candidate = mutation.apply(state)
                except Exception as exc:  # noqa: BLE001
                    log_event(logger, "mutation.failed", level=30,
                              worker=mutation.worker, error=str(exc))
                    mutation.accepted = False
                    rnd.mutations.append(mutation)
                    continue

                trial = self.measure(candidate, brief)
                trial_score = self.aggregate(trial)
                trial_hard = sum(1 for r in trial if r.blocking)
                current_hard = sum(1 for r in results if r.blocking)

                better = trial_hard < current_hard or (
                    trial_hard == current_hard and trial_score > score + 1e-6)
                mutation.accepted = better
                mutation.delta = round(trial_score - score, 6)
                rnd.mutations.append(mutation)

                if better:
                    state, results, score = candidate, trial, trial_score

            rnd.phase_sequence.append(Phase.DECIDE.value)
            rnd.score_after = score
            rnd.hard_open_after = sum(1 for r in results if r.blocking)
            rnd.seconds = time.perf_counter() - round_started
            transcript.rounds.append(rnd)

            emit(Phase.DECIDE, {
                "round": index, "score": round(score, 4),
                "hard_open": rnd.hard_open_after,
                "accepted": sum(1 for m in rnd.mutations if m.accepted),
                "proposed": len(rnd.mutations),
            })

            if rnd.hard_open_after == 0 and all(r.satisfied for r in results):
                transcript.outcome = "satisfied"
                break
            if not rnd.improved or (rnd.score_after - rnd.score_before) < self.config.convergence_epsilon:
                if rnd.hard_open_after == 0:
                    transcript.outcome = "converged"
                else:
                    transcript.outcome = "converged_with_open_constraints"
                break
        else:
            transcript.outcome = "exhausted"

        transcript.final_score = score
        transcript.hard_open = sum(1 for r in results if r.blocking)
        transcript.seconds = time.perf_counter() - started

        log_event(logger, "protocol.finished",
                  outcome=transcript.outcome, rounds=len(transcript.rounds),
                  score=round(score, 4), hard_open=transcript.hard_open,
                  seconds=round(transcript.seconds, 2))
        return state, transcript


def negotiate(
    plan: FloorPlan, brief: ClientBrief, config: ProtocolConfig | None = None
) -> tuple[FloorPlan, Transcript]:
    """Convenience entry point."""
    return ConsensusProtocol(config=config).run(plan, brief)
