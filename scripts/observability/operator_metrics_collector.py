"""Poll the private aggregate metrics function and export gauges through OTLP."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from request_engine.platform.observability.operator_metrics import (
    publish_recovery_evidence_metrics,
    validate_operator_metrics_database_url,
)
from request_engine.platform.observability.recovery_certification import (
    load_recovery_evidence,
)

LOGGER = logging.getLogger("request_engine.operator_metrics")
POLL_SECONDS = 15
METRICS_DATABASE_URL_ENV = "REQUEST_ENGINE_OPERATOR_METRICS_DATABASE_URL"
RECOVERY_CERTIFICATION_PATH_ENV = "REQUEST_ENGINE_RECOVERY_CERTIFICATION_PATH"
TOTAL_OPERATION_TIMEOUT_SECONDS = 8


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    scheduled_action_backlog: int
    scheduled_action_oldest_age_seconds: float
    outbox_backlog: int
    outbox_oldest_age_seconds: float
    provider_event_backlog: int
    provider_event_oldest_age_seconds: float
    provider_event_failures_10m: int
    communication_failures_10m: int
    communication_ambiguous_10m: int
    last_success_timestamp_seconds: float


def _metric_exporter() -> tuple[Any, Any]:
    otlp_exporter_module: Any = import_module(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter"
    )
    metrics_module: Any = import_module("opentelemetry.sdk.metrics")
    export_module: Any = import_module("opentelemetry.sdk.metrics.export")
    resources_module: Any = import_module("opentelemetry.sdk.resources")

    exporter = otlp_exporter_module.OTLPMetricExporter()
    reader = export_module.PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=POLL_SECONDS * 1000,
        export_timeout_millis=10_000,
    )
    provider = metrics_module.MeterProvider(
        resource=resources_module.Resource.create(
            {
                "service.name": "request-engine-operator-metrics",
                "deployment.environment.name": os.environ.get(
                    "OTEL_DEPLOYMENT_ENVIRONMENT", "production"
                ),
            }
        ),
        metric_readers=[reader],
    )
    return provider, provider.get_meter("request_engine.operator_metrics", "1")


def _register_gauges(
    meter: Any,
) -> tuple[dict[str, list[tuple[float, dict[str, str]]]], threading.Lock]:
    values: dict[str, list[tuple[float, dict[str, str]]]] = {}
    lock = threading.Lock()
    names = {
        "scheduled_action.backlog": "scheduled_action_backlog",
        "scheduled_action.oldest_age_seconds": "scheduled_action_oldest_age_seconds",
        "outbox.backlog": "outbox_backlog",
        "outbox.oldest_age_seconds": "outbox_oldest_age_seconds",
        "provider_event.backlog": "provider_event_backlog",
        "provider_event.oldest_age_seconds": "provider_event_oldest_age_seconds",
        "provider_event.failures_10m": "provider_event_failures_10m",
        "communication.failures_10m": "communication_failures_10m",
        "communication.ambiguous_10m": "communication_ambiguous_10m",
        "operator_metrics.collector_last_success_timestamp": "last_success_timestamp_seconds",
        "backup_evidence.verified": "backup_evidence_verified",
        "restore_drill.verified": "restore_drill_verified",
        "backup_evidence.age_seconds": "backup_evidence_age_seconds",
        "restore_drill.evidence_age_seconds": "restore_drill_evidence_age_seconds",
    }

    def callback(key: str) -> Any:
        def observe(_: Any) -> list[Any]:
            metrics_module: Any = import_module("opentelemetry.metrics")

            with lock:
                current = tuple(values.get(key, []))
            return [
                metrics_module.Observation(value, attributes=attributes)
                for value, attributes in current
            ]

        return observe

    for metric_name, key in names.items():
        meter.create_observable_gauge(metric_name, callbacks=[callback(key)])
        values[key] = (
            [(0.0, {})]
            if key
            in {
                "backup_evidence_verified",
                "restore_drill_verified",
            }
            else []
        )
    return values, lock


def _read_snapshot(row: Any) -> MetricSnapshot:
    return MetricSnapshot(
        scheduled_action_backlog=int(row[0]),
        scheduled_action_oldest_age_seconds=float(row[1]),
        outbox_backlog=int(row[2]),
        outbox_oldest_age_seconds=float(row[3]),
        provider_event_backlog=int(row[4]),
        provider_event_oldest_age_seconds=float(row[5]),
        provider_event_failures_10m=int(row[6]),
        communication_failures_10m=int(row[7]),
        communication_ambiguous_10m=int(row[8]),
        last_success_timestamp_seconds=time.time(),
    )


def _publish_snapshot(
    values: dict[str, list[tuple[float, dict[str, str]]]],
    snapshot: MetricSnapshot,
    lock: threading.Lock,
) -> None:
    with lock:
        for key in (
            "scheduled_action_backlog",
            "scheduled_action_oldest_age_seconds",
            "outbox_backlog",
            "outbox_oldest_age_seconds",
            "provider_event_backlog",
            "provider_event_oldest_age_seconds",
            "provider_event_failures_10m",
            "communication_failures_10m",
            "communication_ambiguous_10m",
            "last_success_timestamp_seconds",
        ):
            raw = getattr(snapshot, key)
            values[key] = [(float(raw), {})]


async def _verify_monitor_role(engine: Any) -> None:
    async with engine.connect() as connection:
        await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        role = (
            await connection.execute(
                text(
                    """
                    SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                           rolreplication, rolbypassrls, rolinherit,
                           pg_has_role(current_user, 'request_operator_metrics', 'member'),
                           has_function_privilege(
                               current_user, 'request_admin.read_operator_metrics()', 'EXECUTE'
                           ),
                           has_table_privilege(
                               current_user, 'request_engine.scheduled_actions', 'SELECT'
                           )
                      FROM pg_roles WHERE rolname = current_user
                    """
                )
            )
        ).one()
        memberships = (
            await connection.execute(
                text(
                    """
                    SELECT array_agg(parent.rolname ORDER BY parent.rolname)
                      FROM pg_auth_members membership
                      JOIN pg_roles member ON member.oid = membership.member
                      JOIN pg_roles parent ON parent.oid = membership.roleid
                     WHERE member.rolname = current_user
                    """
                )
            )
        ).scalar_one()
        if tuple(role) != (True, False, False, False, False, False, False, True, True, False):
            raise RuntimeError("operator metrics database role violates its read-only contract")
        if memberships != ["request_operator_metrics"]:
            raise RuntimeError("operator metrics login has unexpected role memberships")


async def collect_forever(stop: asyncio.Event) -> None:
    database_url = os.environ.get(METRICS_DATABASE_URL_ENV)
    if not database_url:
        raise RuntimeError(f"{METRICS_DATABASE_URL_ENV} is required")
    parsed_url = validate_operator_metrics_database_url(database_url)

    provider, meter = _metric_exporter()
    values, values_lock = _register_gauges(meter)
    try:
        engine = create_async_engine(
            parsed_url,
            connect_args={
                "timeout": 3.0,
                "server_settings": {"statement_timeout": "4000", "lock_timeout": "1000"},
            },
            pool_size=1,
            max_overflow=0,
            pool_timeout=3.0,
        )
    except Exception as exc:
        raise RuntimeError(
            f"operator metrics database initialization failed ({type(exc).__name__})"
        ) from None
    try:
        try:
            async with asyncio.timeout(TOTAL_OPERATION_TIMEOUT_SECONDS):
                await _verify_monitor_role(engine)
        except Exception as exc:
            raise RuntimeError(
                f"operator metrics login verification failed ({type(exc).__name__})"
            ) from None
        while not stop.is_set():
            certification_path_value = os.environ.get(RECOVERY_CERTIFICATION_PATH_ENV)
            certification_path = (
                None if not certification_path_value else Path(certification_path_value)
            )
            publish_recovery_evidence_metrics(
                values,
                load_recovery_evidence(certification_path),
                values_lock,
            )
            try:
                async with asyncio.timeout(TOTAL_OPERATION_TIMEOUT_SECONDS):
                    async with engine.connect() as connection:
                        await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                        result = await connection.execute(
                            text("SELECT * FROM request_admin.read_operator_metrics()")
                        )
                        row = result.one()
                _publish_snapshot(values, _read_snapshot(row), values_lock)
            except Exception as exc:
                # Preserve the last successful values; the success timestamp becomes stale.
                LOGGER.warning("operator metrics query failed: %s", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
            except TimeoutError:
                continue
    finally:
        await engine.dispose()
        provider.force_flush()
        provider.shutdown()


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for received_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(received_signal, stop.set)
    await collect_forever(stop)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(_main())
