"""Plan cache.

Generated schemes need to outlive the request that made them, because drawings,
the 3D model, Vastu re-runs and cost re-pricing are all separate calls against
the same plan. Persisting every candidate to the database would be wasteful -
most are discarded within seconds - so plans live in a bounded in-process LRU,
with the *selected* scheme additionally written to the project row where it
belongs permanently.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from aip.core.logging import get_logger, log_event
from aip.domain.plan import FloorPlan

logger = get_logger("aip.api.store")


class PlanStore:
    """Thread-safe bounded LRU of recently generated plans."""

    def __init__(self, capacity: int = 400) -> None:
        self.capacity = capacity
        self._items: OrderedDict[str, tuple[str, FloorPlan]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, firm_id: str, plan: FloorPlan) -> None:
        with self._lock:
            self._items[plan.id] = (firm_id, plan)
            self._items.move_to_end(plan.id)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def put_many(self, firm_id: str, plans: list[FloorPlan]) -> None:
        for plan in plans:
            self.put(firm_id, plan)

    def get(self, plan_id: str, firm_id: str | None = None) -> FloorPlan | None:
        """Fetch a plan, enforcing tenant isolation when a firm is given."""
        with self._lock:
            entry = self._items.get(plan_id)
            if entry is None:
                return None
            owner, plan = entry
            # Never return another tenant's plan, even to a caller who guessed
            # the id: plan ids appear in URLs and must not be a capability.
            if firm_id is not None and owner != firm_id:
                log_event(
                    logger, "store.cross_tenant_denied", level=30,
                    plan=plan_id, requester=firm_id,
                )
                return None
            self._items.move_to_end(plan_id)
            return plan

    def discard(self, plan_id: str) -> None:
        with self._lock:
            self._items.pop(plan_id, None)

    def __len__(self) -> int:
        return len(self._items)


_store = PlanStore()


def get_plan_store() -> PlanStore:
    return _store
