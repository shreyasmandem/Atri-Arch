"""The seam between this pipeline and the shipped reasoner.

Wires the calibration module to `aip.engines.vastu.knowledge.RULES` and
`aip.engines.vastu.engine.VastuReport`.

The contract is narrow on purpose -- one call per plan, returning per-rule
satisfaction and assessability.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

import numpy as np

from .schema import CalibrationSet, PlanObservation, RuleCard


def cards_from_corpus(corpus: Iterable[Any] | None = None) -> tuple[RuleCard, ...]:
    """Expected per rule object: .rule_id / .id, .provenance / .school, .modern_validity,
    and .weight if the corpus already carries a hand-set weight.

    If corpus is omitted, defaults directly to `aip.engines.vastu.knowledge.RULES`.
    Ordering is fixed here and must not change between building the panel set
    and fitting -- the design matrix is positional.
    """
    if corpus is None:
        from aip.engines.vastu.knowledge import RULES
        corpus = RULES

    cards = []
    for rule in corpus:
        rid = getattr(rule, "rule_id", None) or getattr(rule, "id")
        school = getattr(rule, "school", None)
        provenance = getattr(rule, "provenance", None) or (school.value if hasattr(school, "value") else str(school or "contemporary"))
        cards.append(
            RuleCard(
                rule_id=str(rid),
                provenance=str(provenance),
                modern_validity=float(getattr(rule, "modern_validity", 1.0)),
                prior_weight=float(getattr(rule, "weight", 1.0)),
            )
        )
    return tuple(sorted(cards, key=lambda c: c.rule_id))


def observation_from_report(
    plan_id: str, report: Any, cards: tuple[RuleCard, ...],
) -> PlanObservation:
    """Expected per finding/verdict in `report`: .rule_id, .compliance / .satisfaction in [0,1],
    and .assessable (or a status of "not_assessable").

    A rule absent from the report is treated as not assessable, never as zero.
    """
    by_rule = {}
    items = getattr(report, "verdicts", getattr(report, "findings", report))
    if isinstance(items, dict):
        items = items.values()

    for f in items:
        rid = str(getattr(f, "rule_id", None) or getattr(f, "id", ""))
        if not rid:
            continue
        status = str(getattr(f, "status", "")).lower()
        assessable = bool(getattr(f, "assessable", status != "not_assessable"))
        satisfaction = float(getattr(f, "compliance", getattr(f, "satisfaction", 0.0)))
        by_rule[rid] = (satisfaction, assessable)

    sat = np.zeros(len(cards))
    msk = np.zeros(len(cards), dtype=bool)
    for i, c in enumerate(cards):
        if c.rule_id in by_rule:
            sat[i], msk[i] = by_rule[c.rule_id]
    return PlanObservation(
        plan_id=plan_id,
        rule_ids=tuple(c.rule_id for c in cards),
        satisfaction=sat,
        assessable=msk,
    )


def build_set(
    plans: dict[str, Any],
    cards: tuple[RuleCard, ...] | None = None,
    evaluate: Callable[[Any], Any] | None = None,
) -> CalibrationSet:
    """`evaluate` is the reasoner call: design -> report.
    Defaults to cards_from_corpus() and VastuEngine().analyse().
    """
    if cards is None:
        cards = cards_from_corpus()
    if evaluate is None:
        from aip.engines.vastu.engine import VastuEngine
        _engine = VastuEngine()
        evaluate = lambda p: _engine.analyse(p)

    cs = CalibrationSet(cards=cards)
    for pid, design in plans.items():
        cs.add_plan(observation_from_report(pid, evaluate(design), cards))
    return cs


def write_back(weights: dict[str, float], identifiable: dict[str, bool],
               prior: dict[str, float]) -> dict[str, float]:
    """Only weights the bootstrap identified are allowed to change.

    Everything else keeps the editor's value, so a rule the panel never
    exercised is not quietly re-weighted by noise.
    """
    return {
        rid: (weights[rid] if identifiable.get(rid, False) else prior.get(rid, 1.0))
        for rid in weights
    }
