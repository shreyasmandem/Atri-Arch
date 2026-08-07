"""Phase 7 - Cost prediction.

Replaces manual bill-of-quantities preparation with a deterministic takeoff from
the model geometry, priced against a regional rate schedule, wrapped in a Monte
Carlo risk simulation and corrected by a model that learns each firm's own
historical deviation from the baseline.

The structure matters: a single "cost per square foot" number is what the
industry currently uses and it is wrong by 20-40% routinely, because it cannot
see that this scheme has twice the external wall area or six wet areas instead of
three. Taking quantities off the actual geometry removes that error class
entirely, leaving only rate uncertainty - which is what the simulation quantifies.
"""

from aip.engines.cost.estimator import (
    CostEstimate,
    CostLineItem,
    estimate_cost,
)
from aip.engines.cost.rates import (
    FinishTier,
    RateSchedule,
    Trade,
    default_schedule,
    region_multiplier,
)

__all__ = [
    "CostEstimate",
    "CostLineItem",
    "FinishTier",
    "RateSchedule",
    "Trade",
    "default_schedule",
    "estimate_cost",
    "region_multiplier",
]
