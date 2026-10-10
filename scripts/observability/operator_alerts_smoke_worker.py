"""Exercise the production fenced provider-event worker against PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from request_engine.entrypoints.worker.provider_event_router import ProviderEventRouter
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.events.provider_events import PostgresProviderEventWorker
from request_engine.platform.observability.worker_telemetry import OpenTelemetryWorkerMetrics
from request_engine.platform.worker.runtime import (
    FencedWorkerRuntime,
    PermanentWorkError,
    WorkerRuntimeConfig,
)

DATABASE_URL_ENV = "OPERATOR_ALERT_SMOKE_WORKER_DATABASE_URL"
ADMIN_DATABASE_URL_ENV = "OPERATOR_ALERT_SMOKE_WORKER_ADMIN_URL"
CONTROL_DIR_ENV = "OPERATOR_ALERT_SMOKE_CONTROL_DIR"
OTLP_ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"


async def _create_event(engine: Any) -> tuple[str, str]:
    organization_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO request_engine.organizations (id, organization_key, display_name) "
                "VALUES (:id, :key, 'Operator alert integration probe')"
            ),
            {"id": organization_id, "key": f"operator-smoke-{organization_id}"},
        )
        row = (
            await connection.execute(
                text(
                    """
                    INSERT INTO request_engine.provider_events (
                        organization_id, provider_key, connection_key, provider_event_id,
                        payload_hash, payload
                    ) VALUES (
                        :organization_id, 'operator-smoke', 'worker-failure',
                        :event_key, :payload_hash, '{}'::jsonb
                    ) RETURNING id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "event_key": f"probe-{uuid4()}",
                    "payload_hash": f"sha256-{uuid4().hex}",
                },
            )
        ).one()
    return str(organization_id), str(row[0])


async def _replay_event(engine: Any, organization_id: str, event_id: str) -> bool:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                SELECT
                    set_config('request_engine.organization_id', :organization_id, true),
                    set_config('request_engine.authenticated_principal_id', :principal_id, true)
                """
            ),
            {"organization_id": organization_id, "principal_id": str(uuid4())},
        )
        return bool(
            await connection.scalar(
                text(
                    "SELECT request_admin.replay_provider_event("
                    ":organization_id, :event_id, 1, 'operator alert smoke recovery')"
                ),
                {"organization_id": organization_id, "event_id": event_id},
            )
        )


def _telemetry() -> tuple[Any, OpenTelemetryWorkerMetrics]:
    metrics_api: Any = import_module("opentelemetry.metrics")
    exporter_module: Any = import_module("opentelemetry.exporter.otlp.proto.http.metric_exporter")
    sdk_metrics: Any = import_module("opentelemetry.sdk.metrics")
    sdk_export: Any = import_module("opentelemetry.sdk.metrics.export")
    sdk_resources: Any = import_module("opentelemetry.sdk.resources")
    endpoint = os.environ.get(OTLP_ENDPOINT_ENV, "http://otel-collector:4318")
    reader = sdk_export.PeriodicExportingMetricReader(
        exporter_module.OTLPMetricExporter(endpoint=f"{endpoint.rstrip('/')}/v1/metrics"),
        export_interval_millis=1000,
        export_timeout_millis=5000,
    )
    provider = sdk_metrics.MeterProvider(
        resource=sdk_resources.Resource.create(
            {
                "service.name": "request-engine-worker",
                "service.instance.id": "operator-smoke-worker",
                "deployment.environment.name": "ci",
            }
        ),
        metric_readers=[reader],
    )
    metrics_api.set_meter_provider(provider)
    meter = metrics_api.get_meter("request_engine.operator_alert_smoke", "1")
    return provider, OpenTelemetryWorkerMetrics("provider_event", meter)


async def _run_phase(
    worker: FencedWorkerRuntime[Any],
    provider: Any,
    result_path: Path,
    phase: str,
) -> str:
    outcomes = await worker.run_once()
    provider.force_flush(timeout_millis=5000)
    if len(outcomes) != 1:
        raise RuntimeError(f"{phase} worker phase did not process exactly one event")
    state = outcomes[0].state.value
    await asyncio.to_thread(_append_result, result_path, f"{phase}|{state}\n")
    return state


def _append_result(path: Path, line: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)


async def _run() -> None:
    database_url = os.environ.get(DATABASE_URL_ENV)
    admin_database_url = os.environ.get(ADMIN_DATABASE_URL_ENV)
    control_dir_value = os.environ.get(CONTROL_DIR_ENV)
    if not database_url or not admin_database_url or not control_dir_value:
        raise RuntimeError("worker/admin smoke databases and control paths are required")
    control_dir = Path(control_dir_value)
    await asyncio.to_thread(control_dir.mkdir, parents=True, exist_ok=True)
    state_path = control_dir / "worker-state.json"
    result_path = control_dir / "worker-results.txt"
    worker_engine = create_postgres_engine(database_url)
    admin_engine = create_postgres_engine(admin_database_url)
    provider, telemetry = _telemetry()
    session_factory = create_session_factory(worker_engine)
    store = PostgresProviderEventWorker(session_factory)
    config = WorkerRuntimeConfig(
        max_concurrency=1,
        claim_batch_size=1,
        lease_duration=timedelta(seconds=10),
        heartbeat_interval=timedelta(seconds=1),
        processing_timeout=timedelta(seconds=5),
        idle_sleep=timedelta(milliseconds=100),
    )
    try:
        await _verify_worker_role(worker_engine)
        organization_id, event_id = await _create_event(admin_engine)

        async def fail_handler(_: Any) -> None:
            raise PermanentWorkError("operator_smoke_failure")

        failing_router = ProviderEventRouter({("operator-smoke", "worker-failure"): fail_handler})
        failing_worker = FencedWorkerRuntime(
            store,
            failing_router,
            config=config,
            telemetry=telemetry,
        )
        failure_state = await _run_phase(failing_worker, provider, result_path, "failure")
        if failure_state != "dead":
            raise RuntimeError("expected provider-event failure did not reach dead-letter state")
        await asyncio.to_thread(
            state_path.write_text,
            json.dumps({"organization_id": organization_id, "event_id": event_id}),
            encoding="utf-8",
        )
        await asyncio.to_thread((control_dir / "worker-ready").touch)

        recover_path = control_dir / "recover-worker"
        deadline = time.monotonic() + 540
        while not await asyncio.to_thread(recover_path.exists):
            if time.monotonic() >= deadline:
                raise TimeoutError("worker recovery command was not received")
            await asyncio.sleep(1)

        if not await _replay_event(admin_engine, organization_id, event_id):
            raise RuntimeError("operator replay did not return the failed event to the queue")

        async def succeed_handler(_: Any) -> None:
            return None

        recovery_router = ProviderEventRouter(
            {("operator-smoke", "worker-failure"): succeed_handler}
        )
        recovery_worker = FencedWorkerRuntime(
            store,
            recovery_router,
            config=config,
            telemetry=telemetry,
        )
        recovery_state = await _run_phase(recovery_worker, provider, result_path, "recovery")
        if recovery_state != "completed":
            raise RuntimeError("replayed provider event did not complete")
    finally:
        provider.force_flush(timeout_millis=5000)
        provider.shutdown(timeout_millis=5000)
        await worker_engine.dispose()
        await admin_engine.dispose()


async def _verify_worker_role(engine: Any) -> None:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    """
                    SELECT current_user, role.rolsuper,
                           pg_has_role(current_user, 'request_engine_worker', 'member'),
                           has_function_privilege(
                               current_user,
                               'request_cmd.claim_provider_events(integer, interval)',
                               'EXECUTE'
                           )
                      FROM pg_roles role WHERE role.rolname = current_user
                    """
                )
            )
        ).one()
    expected_login = os.environ.get("OPERATOR_ALERT_SMOKE_WORKER_ROLE")
    if row[0] != expected_login or row[1:] != (False, True, True):
        raise RuntimeError("smoke worker login does not have the least-privilege worker role")


if __name__ == "__main__":
    asyncio.run(_run())
