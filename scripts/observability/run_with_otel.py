#!/usr/bin/env python3
"""Run a Request Engine process under OpenTelemetry zero-code instrumentation."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_COLLECTOR_ENDPOINT = "http://127.0.0.1:4318"
DEFAULT_SERVICE_VERSION = "0.1.0"
DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s [%(name)s] "
    "[trace_id=%(otelTraceID)s span_id=%(otelSpanID)s "
    "trace_sampled=%(otelTraceSampled)s] %(message)s"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-name", required=True)
    parser.add_argument("--service-version", default=DEFAULT_SERVICE_VERSION)
    parser.add_argument("--collector-endpoint")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate that the OpenTelemetry zero-code launcher is installed.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Process command after --, for example: -- python -m package",
    )
    return parser.parse_args()


def _instrument_executable() -> str:
    executable = shutil.which("opentelemetry-instrument")
    if executable is None:
        raise RuntimeError(
            "opentelemetry-instrument is not installed; install "
            "deploy/observability/requirements.txt"
        )
    return executable


def _runtime_environment(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    endpoint = args.collector_endpoint or env.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_COLLECTOR_ENDPOINT
    )
    resource_attributes = [f"service.version={args.service_version}"]
    deployment_environment = env.get("REQUEST_ENGINE_ENV")
    if deployment_environment:
        resource_attributes.append(
            f"deployment.environment.name={deployment_environment}"
        )

    defaults = {
        "OTEL_SERVICE_NAME": args.service_name,
        "OTEL_RESOURCE_ATTRIBUTES": ",".join(resource_attributes),
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "none",
        "OTEL_PROPAGATORS": "tracecontext,baggage",
        "OTEL_TRACES_SAMPLER": "parentbased_traceidratio",
        "OTEL_TRACES_SAMPLER_ARG": "1.0",
        "OTEL_PYTHON_LOG_CORRELATION": "true",
        "OTEL_PYTHON_LOG_FORMAT": DEFAULT_LOG_FORMAT,
        "OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "false",
    }
    for key, value in defaults.items():
        env.setdefault(key, value)

    return env


def main() -> int:
    args = parse_args()
    executable = _instrument_executable()

    if args.check:
        print(f"OpenTelemetry launcher ready: {Path(executable).name}")
        return 0

    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise SystemExit("a process command is required after --")

    result = subprocess.run(
        [executable, *command],
        env=_runtime_environment(args),
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
