"""Phase 5 - Explainable Vastu reasoning.

Almost every "Vastu app" is a lookup table that returns a verdict with no
reasoning, no citation and no way to disagree with it. This engine is built the
other way round: it is a defeasible rule system over a formally encoded corpus,
where every verdict carries its classical source, its modern justification (or
lack of one), a numeric contribution to the score, and a counterfactual showing
what would change if it were fixed.

That design is what allows the same engine to serve an orthodox client and a
sceptical one from one rule base, by reweighting rather than by switching
tables - the reconciliation of traditional and modern practice that the research
abstract sets as an objective.
"""

from aip.engines.vastu.engine import (
    VastuEngine,
    VastuReport,
    RuleVerdict,
    analyse_vastu,
    quick_vastu_score,
)
from aip.engines.vastu.knowledge import (
    RULES,
    School,
    RuleCategory,
    VastuRule,
    ideal_direction,
    rules_for_room,
)

__all__ = [
    "RULES",
    "RuleCategory",
    "RuleVerdict",
    "School",
    "VastuEngine",
    "VastuReport",
    "VastuRule",
    "analyse_vastu",
    "ideal_direction",
    "quick_vastu_score",
    "rules_for_room",
]
