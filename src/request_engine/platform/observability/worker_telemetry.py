"""Optional OpenTelemetry adapter for the technical worker runtime boundary."""

from __future__ import annotations

from importlib import import_module
from typing import Any


class OpenTelemetryWorkerMetrics:
    """Bounded worker metrics with a fixed worker-kind dimension."""

    def __init__(self, worker: str, meter: Any) -> None:
        self._worker = worker
        self._cycles = meter.create_counter("worker.cycles", unit="{cycle}")
        self._claims = meter.create_counter("worker.claims", unit="{work_item}")
        self._outcomes = meter.create_counter("worker.outcomes", unit="{work_item}")
        self._lease_lost = meter.create_counter("worker.lease_lost", unit="{work_item}")
        self._duration = meter.create_histogram("worker.processing.duration", unit="s")

    def claimed(self, count: int) -> None:
        if count:
            self._claims.add(count, {"worker": self._worker})

    def cycle(self) -> None:
        self._cycles.add(1, {"worker": self._worker})

    def outcome(self, state: str, detail: str) -> None:
        del detail  # Error text and IDs must never become metric dimensions.
        self._outcomes.add(1, {"worker": self._worker, "outcome": state})
        if state == "stale":
            self._lease_lost.add(1, {"worker": self._worker})

    def processing_seconds(self, seconds: float) -> None:
        self._duration.record(seconds, {"worker": self._worker})


def create_worker_telemetry(worker: str) -> OpenTelemetryWorkerMetrics | None:
    """Return metrics when optional observability dependencies are installed."""
    try:
        metrics = import_module("opentelemetry.metrics")
    except ImportError:
        return None
    return OpenTelemetryWorkerMetrics(
        worker,
        metrics.get_meter("request_engine.platform.worker", "1"),
    )
