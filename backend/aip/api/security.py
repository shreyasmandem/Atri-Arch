"""Authentication, tenancy and rate limiting.

Two key classes exist because the widget runs in a browser where nothing can be
kept secret:

* **Public keys** (`aip_pk_...`) ship in the embed snippet. They are origin-bound
  and can only reach client-facing endpoints. A leaked public key lets someone
  generate designs against the firm's quota from an allowed domain - annoying,
  bounded, and revocable - but never read the firm's project list.
* **Secret keys** (`aip_sk_...`) stay server-side and carry full access.

Treating a browser-embedded credential as if it were secret is the standard way
these integrations get breached, so the split is enforced at the dependency
level rather than left to each endpoint to remember.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aip.core.config import get_settings
from aip.core.logging import get_logger, log_event
from aip.db.models import ApiKey, Firm
from aip.db.session import get_session

logger = get_logger("aip.api.security")

DEMO_FIRM_SLUG = "demo"


@dataclass(slots=True)
class Principal:
    """The authenticated caller."""

    firm: Firm
    scope: str = "public"
    key_id: str = ""
    origin: str | None = None

    @property
    def is_secret(self) -> bool:
        return self.scope == "secret"

    def require_secret(self) -> None:
        if not self.is_secret:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This endpoint requires a secret API key. Public keys are "
                    "browser-visible and are limited to client-facing operations."
                ),
            )


class RateLimiter:
    """Sliding-window limiter, keyed per firm and per endpoint class."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        now = time.monotonic()
        window_hits = self._hits[key]
        while window_hits and now - window_hits[0] > window:
            window_hits.popleft()
        if len(window_hits) >= limit:
            return False, 0
        window_hits.append(now)
        return True, limit - len(window_hits)


_limiter = RateLimiter()


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _lookup_key(session: AsyncSession, raw: str) -> ApiKey | None:
    digest = hash_key(raw)
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.active.is_(True))
    )
    return result.scalar_one_or_none()


async def ensure_demo_firm(session: AsyncSession) -> Firm:
    """Create the demo tenant on first boot so the platform is usable immediately."""
    result = await session.execute(select(Firm).where(Firm.slug == DEMO_FIRM_SLUG))
    firm = result.scalar_one_or_none()
    if firm is not None:
        return firm

    firm = Firm(
        name="Demo Architecture Practice",
        slug=DEMO_FIRM_SLUG,
        contact_email="demo@example.com",
        allowed_origins=[],
        theme={"accent": "#c2603a", "logo_text": "Demo Practice"},
    )
    session.add(firm)
    await session.flush()
    log_event(logger, "firm.demo_created", firm=firm.id)
    return firm


async def get_principal(
    request: Request,
    session: AsyncSession = Depends(get_session),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    origin: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller, falling back to the demo tenant in development."""
    settings = get_settings()
    raw = x_api_key
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()

    if not raw:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="An API key is required. Send it as X-API-Key or a Bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Development convenience: unauthenticated calls act as the demo firm.
        firm = await ensure_demo_firm(session)
        return Principal(firm=firm, scope="secret", key_id="dev", origin=origin)

    api_key = await _lookup_key(session, raw)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key."
        )

    firm = await session.get(Firm, api_key.firm_id)
    if firm is None or not firm.active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is inactive.")

    # A public key is only valid from a domain the firm registered.
    if api_key.scope == "public" and not firm.origin_allowed(origin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Origin {origin or '(none)'} is not permitted for this public key. "
                f"Add it to the firm's allowed origins."
            ),
        )

    api_key.last_used_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    allowed, remaining = _limiter.check(
        f"{firm.id}:{api_key.scope}", limit=120 if api_key.scope == "secret" else 40
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Try again shortly.",
            headers={"Retry-After": "30"},
        )
    request.state.rate_remaining = remaining
    return Principal(firm=firm, scope=api_key.scope, key_id=api_key.id, origin=origin)


async def require_secret(principal: Principal = Depends(get_principal)) -> Principal:
    principal.require_secret()
    return principal


def check_design_quota(firm: Firm) -> None:
    """Enforce the monthly design allowance.

    The quota exists to bound cost even though model access is free: generation
    is CPU work, and an unbounded embedded widget on a public website is a
    denial-of-service vector.
    """
    if firm.monthly_design_quota <= 0:
        return
    if firm.designs_this_month >= firm.monthly_design_quota:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Monthly design quota of {firm.monthly_design_quota} reached. "
                f"It resets at the start of next month."
            ),
        )
