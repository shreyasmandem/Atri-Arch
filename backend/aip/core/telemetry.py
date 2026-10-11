"""Neatlogs observability integration for the Architect Intelligence Platform.

Instruments the multi-agent pipeline (WORKFLOW), domain critics and refiners
(AGENT), RAG corpus retrieval (RETRIEVER), stage chains (CHAIN), and zero-cost
model router completions (LLM) with OpenInference / Neatlogs spans when
``NEATLOGS_API_KEY`` is configured. Remains a zero-overhead no-op in hermetic
tests or offline deployments without a key.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from aip.core.config import Settings, get_settings

_INITIALIZED = False
_ACTIVE = False


def is_telemetry_active() -> bool:
    return _ACTIVE


def init_telemetry(settings: Settings | None = None) -> bool:
    """Initialize the Neatlogs SDK if enabled and an API key is present."""
    global _INITIALIZED, _ACTIVE
    cfg = settings or get_settings()
    if not cfg.neatlogs_enabled:
        _ACTIVE = False
        return False

    api_key = (cfg.neatlogs_api_key or os.getenv("NEATLOGS_API_KEY", "")).strip()
    if not api_key:
        _ACTIVE = False
        return False

    if _INITIALIZED and _ACTIVE:
        return True

    try:
        import neatlogs

        neatlogs.init(
            api_key=api_key,
            endpoint=cfg.neatlogs_endpoint or "https://ingest.neatlogs.com",
            workflow_name="atriarch-design-pipeline",
            tags=["neathack-2026", "atriarch", cfg.environment],
            register_shutdown_handlers=False,
        )
        _INITIALIZED = True
        _ACTIVE = True
        return True
    except Exception:  # noqa: BLE001
        _ACTIVE = False
        return False


def flush_telemetry() -> None:
    """Flush buffered spans to Neatlogs."""
    if not _ACTIVE:
        return
    try:
        import neatlogs

        neatlogs.flush()
    except Exception:  # noqa: BLE001
        pass


def shutdown_telemetry() -> None:
    """Flush and shut down the Neatlogs tracer provider."""
    global _INITIALIZED, _ACTIVE
    if not _INITIALIZED:
        return
    try:
        import neatlogs

        neatlogs.flush()
        neatlogs.shutdown()
    except Exception:  # noqa: BLE001
        pass
    finally:
        _INITIALIZED = False
        _ACTIVE = False


def _sanitize_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            clean[k] = v
        else:
            clean[k] = str(v)[:1000]
    return clean


@contextmanager
def _trace(name: str, **kwargs: Any) -> Iterator[Any]:
    """A Neatlogs span that never breaks the code it wraps.

    Only opening and closing the span are guarded. An exception raised by the
    traced code itself is recorded on the span and re-raised - catching it and
    yielding again is what made `contextmanager` fail with "generator didn't
    stop after throw()", hiding the real error.
    """
    try:
        import neatlogs

        cm = neatlogs.trace(name, **kwargs)
        sp = cm.__enter__()
    except Exception:  # noqa: BLE001 - tracing is optional
        yield None
        return
    try:
        yield sp
    except BaseException as exc:
        try:
            suppressed = cm.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:  # noqa: BLE001
            suppressed = False
        if not suppressed:
            raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def workflow_span(
    name: str,
    *,
    session_id: str = "",
    input_value: str = "",
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a root WORKFLOW span in Neatlogs if active."""
    init_telemetry()
    if not _ACTIVE:
        yield None
        return

    cfg = get_settings()
    merged: dict[str, Any] = {
        "neatlogs.workflow.project_id": cfg.neatlogs_project_id,
        "neatlogs.workflow.surface": "architect-studio",
    }
    if input_value:
        merged["input.value"] = input_value[:4000]
    if attributes:
        merged.update(_sanitize_attrs(attributes))

    with _trace(name, kind="WORKFLOW", session_id=session_id or None, attributes=merged) as sp:
        yield sp


@contextmanager
def chain_span(name: str, **attributes: Any) -> Iterator[Any]:
    """Open a CHAIN span for a pipeline stage or sub-operation."""
    if not _ACTIVE:
        yield None
        return

    with _trace(name, kind="CHAIN", attributes=_sanitize_attrs(attributes)) as sp:
        yield sp


@contextmanager
def agent_span(
    agent_id: str,
    *,
    role: str,
    name: str,
    goal: str = "",
    analytical: bool = True,
    trace_id: str = "",
) -> Iterator[Any]:
    """Open an AGENT span for a committee critic, generator, or refiner."""
    if not _ACTIVE:
        yield None
        return

    attrs = _sanitize_attrs(
        {
            "neatlogs.agent.name": name,
            "neatlogs.agent.role": role,
            "neatlogs.agent.goal": goal,
            "neatlogs.agent.analytical": analytical,
            "aip.trace_id": trace_id,
        }
    )
    with _trace(agent_id, kind="AGENT", attributes=attrs) as sp:
        yield sp


@contextmanager
def retriever_span(name: str, **attributes: Any) -> Iterator[Any]:
    """Open a RETRIEVER span for corpus or statutory RAG queries."""
    if not _ACTIVE:
        yield None
        return

    with _trace(name, kind="RETRIEVER", attributes=_sanitize_attrs(attributes)) as sp:
        yield sp


@contextmanager
def llm_call_span(
    *,
    provider: str,
    model: str,
    messages: list[Any],
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> Iterator[dict[str, Any]]:
    """Record a canonical Neatlogs LLM span around a raw HTTP model call."""
    record: dict[str, Any] = {}
    if not _ACTIVE:
        yield record
        return

    span = None
    start = time.perf_counter()
    try:
        from neatlogs._wrap_utils import get_provider_tracer
        from opentelemetry.trace import StatusCode

        tracer = get_provider_tracer()
        span = tracer.start_span(
            name=f"{provider}.chat.completions",
            attributes={
                "neatlogs.span.kind": "llm",
                "neatlogs.llm.provider": provider,
                "neatlogs.llm.system": provider,
                "neatlogs.llm.model_name": model,
                "neatlogs.llm.is_streaming": False,
                "neatlogs.llm.temperature": temperature,
                "neatlogs.llm.max_tokens": max_tokens,
            },
        )
        for i, msg in enumerate(messages):
            role = getattr(msg, "role", "user")
            content = getattr(msg, "content", str(msg))
            span.set_attribute(f"neatlogs.llm.input_messages.{i}.role", str(role))
            span.set_attribute(f"neatlogs.llm.input_messages.{i}.content", str(content)[:4000])
    except Exception:  # noqa: BLE001
        span = None

    try:
        yield record
    except Exception as exc:
        if span is not None:
            try:
                from opentelemetry.trace import StatusCode

                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                span.end()
            except Exception:  # noqa: BLE001
                pass
        raise
    else:
        if span is not None:
            try:
                from opentelemetry.trace import StatusCode

                duration_ms = record.get("latency_ms") or ((time.perf_counter() - start) * 1000)
                text = str(record.get("text", ""))
                prompt_tokens = int(record.get("prompt_tokens", 0))
                completion_tokens = int(record.get("completion_tokens", 0))
                if text:
                    span.set_attribute("neatlogs.llm.output_messages.0.role", "assistant")
                    span.set_attribute("neatlogs.llm.output_messages.0.content", text[:4000])
                span.set_attribute("neatlogs.llm.token_count.prompt", prompt_tokens)
                span.set_attribute("neatlogs.llm.token_count.completion", completion_tokens)
                span.set_attribute(
                    "neatlogs.llm.token_count.total", prompt_tokens + completion_tokens
                )
                span.set_attribute("neatlogs.llm.metrics.duration_ms", round(float(duration_ms), 3))
                if record.get("degraded"):
                    span.set_attribute("aip.llm.degraded", True)
                span.set_status(StatusCode.OK)
                span.end()
            except Exception:  # noqa: BLE001
                pass
