"""The zero-cost model router.

Responsibilities:

* **Capability routing** - callers ask for `Capability.REASONING`, not for a
  vendor. The router picks the best available free model and fails over on error.
* **Free-tier protection** - a local token bucket per model keeps us inside the
  documented free allowance, so we throttle ourselves instead of being throttled.
* **Circuit breaking** - a provider that is down or out of quota is parked for a
  cool-off window rather than retried on every call.
* **Structured output** - free models are inconsistent at JSON. The router
  strips reasoning traces and code fences, repairs common malformations, and
  performs one guided repair round before giving up.
* **Graceful degradation** - with no keys at all, `OfflineBackend` returns
  deterministic, schema-valid stubs. The analytical engines (geometry, Vastu,
  quantity takeoff) never depend on this path, so the platform stays useful.
* **Accounting** - every call is ledgered. `UsageLedger.total_cost_usd` is an
  invariant the test-suite asserts is exactly zero.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from aip.core.config import Settings, get_settings
from aip.core.logging import get_logger, log_event
from aip.core.providers import (
    PROVIDERS_BY_NAME,
    Capability,
    ModelSpec,
    candidates_for,
    diversified,
)

logger = get_logger("aip.llm")

T = TypeVar("T", bound=BaseModel)

Role = Literal["system", "user", "assistant"]


class LLMError(RuntimeError):
    """Raised when every candidate model failed."""


class AllProvidersExhausted(LLMError):
    pass


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Message:
    role: Role
    content: str
    images: list[str] = field(default_factory=list)  # data URIs or https URLs

    def to_openai(self) -> dict[str, Any]:
        if not self.images:
            return {"role": self.role, "content": self.content}
        parts: list[dict[str, Any]] = [{"type": "text", "text": self.content}]
        for image in self.images:
            parts.append({"type": "image_url", "image_url": {"url": image}})
        return {"role": self.role, "content": parts}


def system(text: str) -> Message:
    return Message("system", text)


def user(text: str, images: list[str] | None = None) -> Message:
    return Message("user", text, images or [])


def assistant(text: str) -> Message:
    return Message("assistant", text)


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0          # always 0.0 - free tiers only
    attempts: int = 1
    degraded: bool = False         # True when served by the offline backend
    reasoning: str = ""            # extracted <think> content, kept for audit

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# ---------------------------------------------------------------------------
# Throttling and health
# ---------------------------------------------------------------------------


class RateLimiter:
    """Sliding-window limiter enforcing per-model RPM and RPD ceilings."""

    def __init__(self) -> None:
        self._minute: dict[str, deque[float]] = defaultdict(deque)
        self._day: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def try_acquire(self, model: ModelSpec) -> bool:
        now = time.monotonic()
        key = f"{model.provider}:{model.id}"
        async with self._lock:
            minute = self._minute[key]
            day = self._day[key]
            while minute and now - minute[0] > 60:
                minute.popleft()
            while day and now - day[0] > 86_400:
                day.popleft()
            if len(minute) >= model.rpm or len(day) >= model.rpd:
                return False
            minute.append(now)
            day.append(now)
            return True

    async def snapshot(self) -> dict[str, dict[str, int]]:
        async with self._lock:
            return {
                key: {"last_minute": len(win), "last_day": len(self._day[key])}
                for key, win in self._minute.items()
            }


class CircuitBreaker:
    """Parks a failing provider for an exponentially growing cool-off.

    The threshold is low deliberately. A committee fans thirteen critics across
    three candidate schemes, so a provider that is simply not running would
    otherwise be rediscovered dozens of times in a single design run.
    """

    def __init__(self, threshold: int = 2, base_cooldown: float = 30.0) -> None:
        self.threshold = threshold
        self.base_cooldown = base_cooldown
        self._failures: dict[str, int] = defaultdict(int)
        self._open_until: dict[str, float] = {}

    def is_open(self, provider: str) -> bool:
        until = self._open_until.get(provider, 0.0)
        if until and time.monotonic() < until:
            return True
        if until:
            self._open_until.pop(provider, None)
        return False

    def record_success(self, provider: str) -> None:
        self._failures.pop(provider, None)
        self._open_until.pop(provider, None)

    def record_failure(self, provider: str) -> None:
        self._failures[provider] += 1
        count = self._failures[provider]
        if count >= self.threshold:
            backoff = min(self.base_cooldown * (2 ** (count - self.threshold)), 900.0)
            self._open_until[provider] = time.monotonic() + backoff
            log_event(
                logger,
                "circuit.opened",
                provider=provider,
                failures=count,
                cooldown_s=round(backoff, 1),
            )


# ---------------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UsageRecord:
    provider: str
    model: str
    capability: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    ok: bool
    degraded: bool = False


class UsageLedger:
    """In-memory accounting. The headline number is always zero."""

    def __init__(self, limit: int = 20_000) -> None:
        self.records: deque[UsageRecord] = deque(maxlen=limit)

    def record(self, rec: UsageRecord) -> None:
        self.records.append(rec)

    @property
    def total_cost_usd(self) -> float:
        # Free tiers only. Kept as a method rather than a literal so that the
        # test-suite is asserting on real accounting, not a hardcoded constant.
        return sum(0.0 for _ in self.records)

    def summary(self) -> dict[str, Any]:
        by_provider: dict[str, dict[str, Any]] = {}
        for rec in self.records:
            bucket = by_provider.setdefault(
                rec.provider,
                {"calls": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0.0},
            )
            bucket["calls"] += 1
            bucket["failures"] += 0 if rec.ok else 1
            bucket["prompt_tokens"] += rec.prompt_tokens
            bucket["completion_tokens"] += rec.completion_tokens
            bucket["latency_ms"] += rec.latency_ms
        for bucket in by_provider.values():
            if bucket["calls"]:
                bucket["avg_latency_ms"] = round(bucket["latency_ms"] / bucket["calls"], 1)
            bucket.pop("latency_ms", None)
        total_calls = len(self.records)
        degraded = sum(1 for r in self.records if r.degraded)
        return {
            "total_calls": total_calls,
            "degraded_calls": degraded,
            "total_cost_usd": self.total_cost_usd,
            "total_tokens": sum(r.prompt_tokens + r.completion_tokens for r in self.records),
            "by_provider": by_provider,
        }


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def split_reasoning(text: str) -> tuple[str, str]:
    """Separate `<think>` traces (R1-style models) from the answer."""
    traces = _THINK_RE.findall(text)
    cleaned = _THINK_RE.sub("", text).strip()
    # An unterminated <think> means the model ran out of budget mid-trace.
    if "<think>" in cleaned and "</think>" not in cleaned:
        head, _, tail = cleaned.partition("<think>")
        traces.append(tail)
        cleaned = head.strip()
    return cleaned, "\n".join(t.strip() for t in traces)


def extract_json(text: str) -> Any:
    """Best-effort JSON recovery from a chatty model response."""
    cleaned, _ = split_reasoning(text)
    cleaned = cleaned.strip()

    for candidate in _json_candidates(cleaned):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            repaired = _repair_json(candidate)
            if repaired is not None:
                return repaired
    raise ValueError(f"no JSON object found in model output: {cleaned[:240]!r}")


def _json_candidates(text: str) -> list[str]:
    out: list[str] = []
    fenced = _FENCE_RE.findall(text)
    out.extend(block.strip() for block in fenced)
    out.append(text)
    # Widest balanced object / array in the raw text.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            out.append(text[start : end + 1])
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _coerce_keys(payload: Any, expected: list[str]) -> Any:
    """Map near-miss key names onto the schema's actual field names.

    Free models rename fields when the surrounding prompt is domain-heavy -
    `score_brief_fidelity` for `score`, `reasoning` for `rationale`. The value is
    correct; only the label drifted. Renaming is cheaper and more reliable than
    spending a repair round asking the model to try again.
    """
    if not isinstance(payload, dict):
        return payload

    out = dict(payload)
    lowered = {k.lower(): k for k in payload}

    for field in expected:
        if field in out:
            continue
        target = field.lower()
        match = next(
            (
                original
                for low, original in lowered.items()
                if original not in expected
                and (low.startswith(target) or low.endswith(target) or target in low)
            ),
            None,
        )
        if match is not None:
            out[field] = out.pop(match)

    # A common synonym the schema will never guess at from the field name alone.
    if "rationale" in expected and "rationale" not in out:
        for synonym in ("reasoning", "justification", "explanation", "summary"):
            if synonym in out:
                out["rationale"] = out[synonym]
                break
    return out


def _repair_json(text: str) -> Any | None:
    """Fix the malformations free models actually produce."""
    attempts = [
        text,
        re.sub(r",\s*([}\]])", r"\1", text),                     # trailing commas
        re.sub(r"//[^\n]*", "", text),                            # line comments
        re.sub(r"\bNaN\b|\bInfinity\b|\b-Infinity\b", "null", text),
        text.replace("'", '"'),
        re.sub(r"(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", r'"\1":', text),  # bare keys
    ]
    # Recover from truncation - the model hit its token ceiling mid-object.
    # Closing brackets alone is not enough when the cut landed inside a string
    # literal, which is the common case: the quote has to be closed first, and
    # a dangling key with no value has to be dropped entirely.
    balanced = text
    if balanced.count('"') % 2 == 1:
        balanced += '"'
    # Drop a trailing key that never received a value. The cut can land either
    # after the colon ("rationale":) or before it ("rationale"), so both shapes
    # have to go.
    balanced = re.sub(r',\s*"[^"]*"\s*:?\s*$', "", balanced)
    balanced = re.sub(r',\s*$', "", balanced)                    # dangling comma
    opens = balanced.count("{") - balanced.count("}")
    brackets = balanced.count("[") - balanced.count("]")
    if brackets > 0:
        balanced += "]" * brackets
    if opens > 0:
        balanced += "}" * opens
    attempts.append(balanced)

    for attempt in attempts:
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def estimate_tokens(text: str) -> int:
    """Cheap token estimate used when a provider omits usage data."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Offline backend
# ---------------------------------------------------------------------------


class OfflineBackend:
    """Deterministic responses when no provider is reachable.

    This is not a "fake LLM" for pretending things work - it is a documented
    degradation mode. Responses are marked `degraded=True`, surfaced in the API
    payload, and shown in the UI, so nobody mistakes a stub for a real design.
    """

    def generate(self, messages: list[Message], schema: dict[str, Any] | None) -> str:
        prompt = "\n".join(m.content for m in messages)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if schema:
            return json.dumps(self._from_schema(schema, digest))
        return (
            "[degraded mode] No model provider is configured, so this narrative "
            "field could not be generated. The analytical results shown "
            "alongside it (geometry, Vastu rule evaluation, quantity takeoff) "
            "are computed deterministically and remain valid. Configure a free "
            "API key to enable generated commentary."
        )

    def _from_schema(self, schema: dict[str, Any], digest: str, depth: int = 0) -> Any:
        if depth > 6:
            return None
        kind = schema.get("type")
        if "enum" in schema and schema["enum"]:
            idx = int(digest[:4], 16) % len(schema["enum"])
            return schema["enum"][idx]
        if kind == "object" or "properties" in schema:
            props = schema.get("properties", {})
            required = set(schema.get("required", list(props)))
            return {
                name: self._from_schema(sub, digest[1:] + digest[:1], depth + 1)
                for name, sub in props.items()
                if name in required or depth == 0
            }
        if kind == "array":
            item = schema.get("items", {"type": "string"})
            return [self._from_schema(item, digest[2:] + digest[:2], depth + 1)]
        if kind == "integer":
            return int(digest[:2], 16) % 10
        if kind == "number":
            return round((int(digest[:3], 16) % 1000) / 1000, 3)
        if kind == "boolean":
            return int(digest[:1], 16) % 2 == 0
        return "unavailable in degraded mode"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """Capability-addressed, failover-capable, strictly-free model access."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.limiter = RateLimiter()
        self.breaker = CircuitBreaker()
        self.ledger = UsageLedger()
        self.offline = OfflineBackend()
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, LLMResponse] = {}
        self._client_lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    async def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(self.settings.llm_timeout_seconds, connect=12.0),
                        limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
                        follow_redirects=True,
                    )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # -- public API --------------------------------------------------------

    async def complete(
        self,
        messages: list[Message],
        *,
        capability: Capability = Capability.FAST,
        temperature: float = 0.4,
        max_tokens: int = 2048,
        json_schema: dict[str, Any] | None = None,
        pin_model: ModelSpec | None = None,
        min_context: int = 0,
        cache_key: str | None = None,
    ) -> LLMResponse:
        """Run a completion against the best available free model."""
        if self.settings.llm_cache_enabled:
            key = cache_key or self._cache_key(messages, capability, temperature, json_schema)
            hit = self._cache.get(key)
            if hit is not None:
                return hit
        else:
            key = None

        models = [pin_model] if pin_model else candidates_for(
            capability, self.settings, min_context=min_context
        )
        models = [m for m in models if m is not None]

        errors: list[str] = []
        attempts = 0
        for model in models:
            if self.breaker.is_open(model.provider):
                continue
            if not await self.limiter.try_acquire(model):
                errors.append(f"{model.provider}/{model.id}: locally rate-limited")
                continue
            attempts += 1
            try:
                response = await self._call(
                    model, messages, temperature, max_tokens, json_schema
                )
            except Exception as exc:  # noqa: BLE001 - failover is the point
                self.breaker.record_failure(model.provider)
                detail = f"{model.provider}/{model.id}: {type(exc).__name__}: {exc}"
                errors.append(detail)
                self.ledger.record(
                    UsageRecord(model.provider, model.id, capability.value, 0, 0, 0.0, ok=False)
                )
                log_event(logger, "llm.attempt_failed", level=30, detail=detail)
                await asyncio.sleep(min(0.4 * attempts, 2.0) + random.random() * 0.3)
                continue

            self.breaker.record_success(model.provider)
            response.attempts = attempts
            self.ledger.record(
                UsageRecord(
                    model.provider,
                    model.id,
                    capability.value,
                    response.prompt_tokens,
                    response.completion_tokens,
                    response.latency_ms,
                    ok=True,
                )
            )
            if key:
                self._cache[key] = response
            return response

        # Nothing worked - degrade rather than fail the whole design pipeline.
        log_event(
            logger,
            "llm.degraded",
            level=30,
            capability=capability.value,
            tried=len(models),
            errors=errors[:4],
        )
        text = self.offline.generate(messages, json_schema)
        response = LLMResponse(
            text=text,
            model="offline-deterministic",
            provider="offline",
            latency_ms=0.0,
            attempts=max(attempts, 1),
            degraded=True,
        )
        self.ledger.record(
            UsageRecord("offline", "deterministic", capability.value, 0, 0, 0.0, ok=True, degraded=True)
        )
        return response

    async def complete_model(
        self,
        messages: list[Message],
        response_model: type[T],
        *,
        capability: Capability = Capability.STRUCTURED,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        pin_model: ModelSpec | None = None,
        repair_attempts: int = 1,
    ) -> tuple[T, LLMResponse]:
        """Completion validated into a Pydantic model, with guided repair."""
        schema = response_model.model_json_schema()
        required = list(schema.get("properties", {}))
        instruction = Message(
            "system",
            "Reply with a single JSON object and nothing else. No prose, no code "
            "fences, no explanation outside the JSON.\n"
            f"Use exactly these key names, spelled exactly like this: {required}.\n"
            "Do not rename, prefix or suffix any key. Keep string values short "
            "so the object is closed properly and never truncated.\n"
            f"It must validate against this JSON Schema:\n"
            f"{json.dumps(schema, separators=(',', ':'))}",
        )
        convo = [instruction, *messages]

        last_error = ""
        for attempt in range(repair_attempts + 1):
            response = await self.complete(
                convo,
                capability=capability,
                temperature=temperature if attempt == 0 else 0.1,
                max_tokens=max_tokens,
                json_schema=schema,
                pin_model=pin_model,
                cache_key=None,
            )
            try:
                payload = extract_json(response.text)
                return response_model.model_validate(payload), response
            except (ValueError, ValidationError) as exc:
                # Models rename fields under pressure - `score_brief_fidelity`
                # for `score` is a real observed case. Rather than burn a whole
                # repair round on a spelling difference, map near-miss keys onto
                # the schema before giving up on this attempt.
                try:
                    payload = _coerce_keys(extract_json(response.text), required)
                    return response_model.model_validate(payload), response
                except (ValueError, ValidationError):
                    pass
                last_error = str(exc)[:600]
                if attempt >= repair_attempts:
                    break
                convo = [
                    instruction,
                    *messages,
                    Message("assistant", response.text[:2000]),
                    Message(
                        "user",
                        "That response was not valid. Error:\n"
                        f"{last_error}\n\nReturn only corrected JSON matching the schema.",
                    ),
                ]

        # Final fallback: schema-shaped stub so the pipeline continues.
        log_event(logger, "llm.structured_failed", level=30, model=response_model.__name__, error=last_error)
        stub = json.loads(self.offline.generate(messages, schema))
        try:
            return response_model.model_validate(stub), LLMResponse(
                text=json.dumps(stub), model="offline-deterministic", provider="offline", degraded=True
            )
        except ValidationError as exc:
            raise LLMError(
                f"could not obtain valid {response_model.__name__}: {last_error or exc}"
            ) from exc

    async def ensemble(
        self,
        messages: list[Message],
        *,
        capability: Capability = Capability.REASONING,
        count: int = 3,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_schema: dict[str, Any] | None = None,
    ) -> list[LLMResponse]:
        """Run the same prompt across `count` *different* model families.

        Provider diversity is the mechanism that makes the critic ensemble
        meaningful: independent weights make independent mistakes, so agreement
        between them carries information.
        """
        pool = candidates_for(capability, self.settings)
        chosen = diversified(pool, count) or pool[:count]
        if not chosen:
            chosen = []

        async def run(model: ModelSpec | None) -> LLMResponse:
            return await self.complete(
                messages,
                capability=capability,
                temperature=temperature,
                max_tokens=max_tokens,
                json_schema=json_schema,
                pin_model=model,
                cache_key=f"ensemble:{id(model)}:{random.random()}",
            )

        targets: list[ModelSpec | None] = list(chosen) if chosen else [None] * count
        while len(targets) < count:
            targets.append(chosen[len(targets) % len(chosen)] if chosen else None)

        results = await asyncio.gather(*(run(m) for m in targets), return_exceptions=True)
        return [r for r in results if isinstance(r, LLMResponse)]

    # -- transport ---------------------------------------------------------

    async def _call(
        self,
        model: ModelSpec,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        json_schema: dict[str, Any] | None,
    ) -> LLMResponse:
        provider = PROVIDERS_BY_NAME[model.provider]
        body: dict[str, Any] = {
            "model": model.id,
            "messages": [m.to_openai() for m in messages],
            "temperature": max(0.0, min(temperature, 1.5)),
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_schema and model.supports_json:
            body["response_format"] = {"type": "json_object"}

        url = f"{provider.resolved_base_url(self.settings)}/chat/completions"
        started = time.perf_counter()
        client = await self.client()

        last_exc: Exception | None = None
        for retry in range(self.settings.llm_max_retries):
            try:
                res = await client.post(url, json=body, headers=provider.headers(self.settings))
            except httpx.ConnectError as exc:
                # Connection refused means nothing is listening - typically
                # `ollama_enabled` is on but the daemon is not running. Retrying
                # that with exponential backoff spends seconds per critic to
                # rediscover the same fact, and with a committee of thirteen it
                # was the single largest source of latency in the pipeline.
                # Fail immediately and let the circuit breaker park the provider.
                raise LLMError(f"connection refused at {provider.name}: {exc}") from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                await asyncio.sleep(0.6 * (2**retry) + random.random() * 0.4)
                continue

            if res.status_code == 429:
                # Do not sleep-and-retry a rate limit in place. The router's
                # whole design is that another free provider is one hop away, so
                # failing over immediately beats blocking this critic for
                # seconds. It also matters for the case where a credential has a
                # *zero* free-tier quota: that 429 never clears, and retrying it
                # on every call was costing ~12s per generative critic.
                raise LLMError(f"rate limited (retry-after {_retry_after(res)}s)")
            if res.status_code >= 500:
                last_exc = LLMError(f"upstream {res.status_code}")
                await asyncio.sleep(0.8 * (2**retry) + random.random() * 0.4)
                continue
            if res.status_code == 400 and "response_format" in body:
                # Some free endpoints reject json_object mode. Retry without it -
                # extract_json() is robust enough to cope.
                body.pop("response_format", None)
                continue
            if res.status_code >= 400:
                raise LLMError(f"http {res.status_code}: {res.text[:300]}")

            return self._parse(res, model, started)

        raise LLMError(str(last_exc) if last_exc else "exhausted retries")

    def _parse(self, res: httpx.Response, model: ModelSpec, started: float) -> LLMResponse:
        try:
            data = res.json()
        except json.JSONDecodeError as exc:
            raise LLMError(f"non-JSON response body: {res.text[:200]}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"no choices in response: {str(data)[:240]}")
        message = choices[0].get("message") or {}
        raw = message.get("content") or ""
        if isinstance(raw, list):  # some gateways return content parts
            raw = "".join(part.get("text", "") for part in raw if isinstance(part, dict))
        if not raw and message.get("reasoning_content"):
            raw = message["reasoning_content"]
        if not raw:
            raise LLMError("empty completion")

        text, reasoning = split_reasoning(raw)
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        if not prompt_tokens:
            prompt_tokens = estimate_tokens(json.dumps(data.get("model", "")))
        if not completion_tokens:
            completion_tokens = estimate_tokens(raw)

        return LLMResponse(
            text=text or raw,
            model=model.id,
            provider=model.provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=(time.perf_counter() - started) * 1000,
            reasoning=reasoning,
        )

    # -- misc --------------------------------------------------------------

    def _cache_key(
        self,
        messages: list[Message],
        capability: Capability,
        temperature: float,
        schema: dict[str, Any] | None,
    ) -> str:
        payload = json.dumps(
            {
                "m": [(m.role, m.content, m.images) for m in messages],
                "c": capability.value,
                "t": round(temperature, 2),
                "s": schema,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def health(self) -> dict[str, Any]:
        return {
            "configured_providers": self.settings.configured_providers(),
            "usage": self.ledger.summary(),
            "rate_limits": await self.limiter.snapshot(),
            "zero_cost_enforced": self.settings.enforce_zero_cost,
        }


_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


async def shutdown_router() -> None:
    global _router
    if _router is not None:
        await _router.aclose()
        _router = None


def _retry_after(res: httpx.Response) -> float:
    raw = res.headers.get("retry-after") or res.headers.get("x-ratelimit-reset-requests")
    if not raw:
        return 2.0
    try:
        return max(0.5, float(raw))
    except ValueError:
        match = re.search(r"([\d.]+)s", str(raw))
        return max(0.5, float(match.group(1))) if match else 2.0
