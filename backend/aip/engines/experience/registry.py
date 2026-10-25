"""Which exteriors are taken: so no two clients' houses look the same.

When a client settles on an exterior, the house claims its exact design (the
id carries every choice: form, finishes, colours, site). Another house asking
for designs never sees a claimed building form, and a client who lands on
another house's exact design is told so and asked to change a detail.

Claims live in a small JSON file in the data directory, so they outlive a
restart; a plan claims one design at a time, its latest.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from aip.core.logging import get_logger

logger = get_logger("aip.exteriors.registry")

_lock = threading.Lock()
_claims: dict[str, str] | None = None      # plan id -> design id


def _path() -> Path | None:
    try:
        from aip.core.config import get_settings

        settings = get_settings()
        if settings.environment == "test":
            return None                           # tests claim in memory only
        return Path(settings.data_dir) / "claimed_exteriors.json"
    except Exception:  # noqa: BLE001 - claims are a courtesy, never a failure
        return None


def _load() -> dict[str, str]:
    global _claims
    if _claims is None:
        _claims = {}
        p = _path()
        if p is not None and p.exists():
            try:
                _claims = {str(k): str(v) for k, v in json.loads(p.read_text()).items()}
            except Exception as exc:  # noqa: BLE001
                logger.info("registry.unreadable %s", exc)
    return _claims


def _save() -> None:
    p = _path()
    if p is None or _claims is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_claims))
    except Exception as exc:  # noqa: BLE001
        logger.info("registry.unwritable %s", exc)


def claim(plan_id: str, design_id: str) -> dict[str, object]:
    """Claim this exact design for the plan; say whether another house has it."""
    from aip.engines.experience.exteriors import Exterior

    ex = Exterior.parse(design_id)
    if ex is None:
        return {"unique": False, "shared_with": 0}
    with _lock:
        claims = _load()
        others = sum(1 for pid, did in claims.items() if pid != plan_id and did == ex.id)
        if not others:
            claims[plan_id] = ex.id
            _save()
    return {"unique": others == 0, "shared_with": others}


def taken_forms(plan_id: str) -> set[str]:
    """Design ids other houses have claimed, for a batch to steer clear of."""
    with _lock:
        return {did for pid, did in _load().items() if pid != plan_id}


def reset() -> None:
    """Forget every claim (tests)."""
    global _claims
    with _lock:
        _claims = {}
