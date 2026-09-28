"""Structured logging, redaction and bounded error tracking for the console.

The console is an operator-facing surface, so diagnostics must be useful without
ever persisting secrets: only method/path/status/timing and redacted structured
fields are logged. Recent failures are kept in a bounded in-memory ring so the
dashboard can surface them with their request id.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

LOGGER_NAME = "request_engine.admin_console"
ERROR_TRACKER_CAPACITY = 200

_SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "credential",
    "authorization",
    "cookie",
    "csrf",
    "recovery",
    "verification",
    "private",
    "key",
)


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:
    """Recursively mask values whose key looks secret-bearing."""

    if isinstance(value, dict):
        source = cast("dict[object, object]", value)
        return {
            str(key): "***" if _is_sensitive(str(key)) else redact(item)
            for key, item in source.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        return [redact(item) for item in cast("tuple[object, ...]", value)]
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, with optional ``extra_fields``."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Install the JSON formatter once and return the console logger."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class ErrorEvent:
    at: str
    request_id: str
    kind: str
    message: str
    method: str = ""
    path: str = ""
    status: int | None = None
    detail: str | None = None


class ErrorTracker:
    """Bounded, thread-safe ring of recent errors for the diagnostics view."""

    def __init__(self, capacity: int = ERROR_TRACKER_CAPACITY) -> None:
        self._events: deque[ErrorEvent] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def record(self, event: ErrorEvent) -> None:
        with self._lock:
            self._events.append(event)

    def recent(self, limit: int = 50) -> list[ErrorEvent]:
        with self._lock:
            events = list(self._events)
        return list(reversed(events))[:limit]

    def total(self) -> int:
        with self._lock:
            return len(self._events)


class ConsoleMetrics:
    """Thread-safe counters exposed by the diagnostics view."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.errors = 0
        self.control_calls = 0
        self.control_errors = 0
        self.started_at = time.time()

    def observe_request(self, *, error: bool) -> None:
        with self._lock:
            self.requests += 1
            if error:
                self.errors += 1

    def observe_control_call(self, *, error: bool) -> None:
        with self._lock:
            self.control_calls += 1
            if error:
                self.control_errors += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requests": self.requests,
                "errors": self.errors,
                "control_calls": self.control_calls,
                "control_errors": self.control_errors,
                "uptime_seconds": round(time.time() - self.started_at, 1),
            }


__all__ = [
    "LOGGER_NAME",
    "ConsoleMetrics",
    "ErrorEvent",
    "ErrorTracker",
    "JsonFormatter",
    "configure_logging",
    "get_logger",
    "redact",
]
