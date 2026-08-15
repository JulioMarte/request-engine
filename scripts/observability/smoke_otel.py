#!/usr/bin/env python3
"""Verify the pinned OpenTelemetry runtime without requiring a remote backend."""

from __future__ import annotations

import shutil
from importlib.metadata import version

from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

EXPECTED_VERSIONS = {
    "opentelemetry-distro": "0.65b0",
    "opentelemetry-sdk": "1.44.0",
    "opentelemetry-exporter-otlp-proto-http": "1.44.0",
    "opentelemetry-instrumentation-fastapi": "0.65b0",
    "opentelemetry-instrumentation-sqlalchemy": "0.65b0",
    "opentelemetry-instrumentation-logging": "0.65b0",
}


def _verify_versions() -> None:
    mismatches = {
        distribution: (expected, version(distribution))
        for distribution, expected in EXPECTED_VERSIONS.items()
        if version(distribution) != expected
    }
    if mismatches:
        raise RuntimeError(f"OpenTelemetry version mismatch: {mismatches}")


def _verify_sdk_signals() -> None:
    resource = Resource.create({"service.name": "request-engine-otel-smoke"})

    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    tracer = tracer_provider.get_tracer(__name__)
    with tracer.start_as_current_span("request-engine.observability.smoke") as span:
        span.set_attribute("request_engine.smoke", True)
    tracer_provider.force_flush()
    spans = span_exporter.get_finished_spans()
    if len(spans) != 1 or spans[0].name != "request-engine.observability.smoke":
        raise RuntimeError("trace SDK smoke test did not emit the expected span")

    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    counter = meter_provider.get_meter(__name__).create_counter(
        "request_engine.observability.smoke"
    )
    counter.add(1, {"component": "ci"})
    metrics = metric_reader.get_metrics_data()
    if not metrics.resource_metrics:
        raise RuntimeError("metrics SDK smoke test emitted no resource metrics")

    tracer_provider.shutdown()
    meter_provider.shutdown()


def _verify_otlp_http_exporters() -> None:
    trace_exporter = OTLPSpanExporter(endpoint="http://127.0.0.1:4318/v1/traces")
    metric_exporter = OTLPMetricExporter(endpoint="http://127.0.0.1:4318/v1/metrics")
    trace_exporter.shutdown()
    metric_exporter.shutdown()


def main() -> int:
    _verify_versions()
    if shutil.which("opentelemetry-instrument") is None:
        raise RuntimeError("opentelemetry-instrument executable is missing")
    _verify_sdk_signals()
    _verify_otlp_http_exporters()
    print("OpenTelemetry runtime smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
