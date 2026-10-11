"""Emit bounded worker/backlog metrics through the configured OTLP Collector."""

from __future__ import annotations

import os
import time
from importlib import import_module
from typing import Any

from request_engine.platform.observability.worker_telemetry import OpenTelemetryWorkerMetrics


def main() -> None:
    metrics: Any = import_module("opentelemetry.metrics")
    exporter_module: Any = import_module("opentelemetry.exporter.otlp.proto.http.metric_exporter")
    sdk_metrics: Any = import_module("opentelemetry.sdk.metrics")
    sdk_export: Any = import_module("opentelemetry.sdk.metrics.export")
    sdk_resources: Any = import_module("opentelemetry.sdk.resources")

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    reader = sdk_export.PeriodicExportingMetricReader(
        exporter_module.OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics"),
        export_interval_millis=250,
    )
    provider = sdk_metrics.MeterProvider(
        resource=sdk_resources.Resource.create(
            {"service.name": "operator-alert-smoke", "service.instance.id": "smoke-unique"}
        ),
        metric_readers=[reader],
    )
    metrics.set_meter_provider(provider)
    worker = OpenTelemetryWorkerMetrics("scheduled_action", metrics.get_meter("smoke"))
    worker.cycle()
    worker.claimed(1)
    worker.outcome("completed", "smoke-no-private-label")
    worker.outcome("stale", "smoke-no-private-label")
    worker.processing_seconds(0.01)
    meter = metrics.get_meter("smoke.backlog")
    for name, value in (
        ("scheduled_action.backlog", 1),
        ("scheduled_action.oldest_age", 1),
        ("outbox.backlog", 0),
        ("outbox.oldest_age", 0),
        ("provider_event.backlog", 0),
        ("provider_event.oldest_age", 0),
    ):
        gauge = meter.create_gauge(name, unit="{work_item}" if name.endswith("backlog") else "s")
        gauge.set(value)
    provider.force_flush(timeout_millis=5000)
    time.sleep(0.5)
    provider.shutdown(timeout_millis=5000)


if __name__ == "__main__":
    main()
