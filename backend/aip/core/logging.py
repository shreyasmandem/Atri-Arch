"""Structured logging with request/trace correlation.

Every agent decision the platform makes is logged with a trace id so an
architect (or an auditor, or a reviewer of the research) can reconstruct exactly
which agents saw which evidence and why a design was chosen. Explainability is a
headline claim of this project, so the logging is part of the product, not an
afterthought.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("aip_trace_id", default="-")
_span_stack: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "aip_span_stack", default=()
)

_CONFIGURED = False


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(trace_id: str | None = None) -> str:
    tid = trace_id or new_trace_id()
    _trace_id.set(tid)
    return tid


@contextmanager
def trace_context(trace_id: str | None = None) -> Iterator[str]:
    token = _trace_id.set(trace_id or new_trace_id())
    try:
        yield _trace_id.get()
    finally:
        _trace_id.reset(token)


@contextmanager
def span(name: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Time a named unit of work and emit a structured completion record."""
    stack = _span_stack.get()
    token = _span_stack.set((*stack, name))
    log = get_logger("aip.span")
    started = time.perf_counter()
    payload: dict[str, Any] = dict(fields)
    try:
        yield payload
    except Exception as exc:  # pragma: no cover - re-raised immediately
        elapsed = (time.perf_counter() - started) * 1000
        log.error(
            "span.failed",
            extra={
                "extra_fields": {
                    "span": ".".join((*stack, name)),
                    "duration_ms": round(elapsed, 2),
                    "error": f"{type(exc).__name__}: {exc}",
                    **payload,
                }
            },
        )
        raise
    else:
        elapsed = (time.perf_counter() - started) * 1000
        log.info(
            "span.completed",
            extra={
                "extra_fields": {
                    "span": ".".join((*stack, name)),
                    "duration_ms": round(elapsed, 2),
                    **payload,
                }
            },
        )
    finally:
        _span_stack.reset(token)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": get_trace_id(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class _ConsoleFormatter(logging.Formatter):
    _COLOURS = {
        "DEBUG": "\033[38;5;244m",
        "INFO": "\033[38;5;39m",
        "WARNING": "\033[38;5;214m",
        "ERROR": "\033[38;5;203m",
        "CRITICAL": "\033[48;5;203m\033[38;5;231m",
    }
    _RESET = "\033[0m"

    def __init__(self, colour: bool = True) -> None:
        super().__init__()
        self.colour = colour and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = record.levelname[:4]
        if self.colour:
            level = f"{self._COLOURS.get(record.levelname, '')}{level}{self._RESET}"
        trace = get_trace_id()
        head = f"{ts} {level} [{trace}] {record.name}"
        body = record.getMessage()
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict) and extra:
            rendered = " ".join(f"{k}={_fmt(v)}" for k, v in extra.items())
            body = f"{body} {rendered}"
        out = f"{head} :: {body}"
        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)
        return out


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    text = str(value)
    if len(text) > 160:
        text = text[:157] + "..."
    if " " in text:
        return f'"{text}"'
    return text


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Install handlers. Safe to call repeatedly."""
    global _CONFIGURED
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter() if json_output else _ConsoleFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())

    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)


def log_event(logger: logging.Logger, message: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit a structured event with arbitrary key/value context."""
    logger.log(level, message, extra={"extra_fields": fields})
