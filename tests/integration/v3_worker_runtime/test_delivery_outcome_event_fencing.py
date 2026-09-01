from __future__ import annotations

from uuid import uuid4

import delivery_outcome_probe as probe
import delivery_outcome_world as world
import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.worker.runtime import WorkerItemState

PgConnection = probe.PgConnection

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_late_contradictory_report_cannot_downgrade_delivered_state(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "late-contradiction")
    task_id = world.new_task(admin_conn, org, status="delivering")
    delivery_id, idempotency_key = world.new_delivery(admin_conn, org, task_id)
    delivered = await world.record_outcome_event(
        app_session_factory,
        org,
        provider_event_id=f"evt-delivered-{uuid4().hex}",
        payload={"dedupe_key": idempotency_key, "status": "delivered"},
    )
    contradictory = await world.record_outcome_event(
        app_session_factory,
        org,
        provider_event_id=f"evt-failed-{uuid4().hex}",
        payload={
            "dedupe_key": idempotency_key,
            "status": "failed",
            "retryable": False,
            "result_data": {"error_class": "late_terminal_failure"},
        },
    )
    runtime = world.outcome_event_runtime(worker_session_factory, app_session_factory)

    first = await runtime.run_once()
    second = await runtime.run_once()

    assert [o.state for o in first] == [WorkerItemState.COMPLETED]
    assert [o.state for o in second] == [WorkerItemState.COMPLETED]
    assert probe.event_row(admin_conn, delivered.id) == ("processed", None)
    assert probe.event_row(admin_conn, contradictory.id) == ("processed", None)
    assert probe.delivery_status(admin_conn, delivery_id) == "delivered"
    assert probe.task_status(admin_conn, task_id) == "completed"
    assert probe.outbox_count(admin_conn, org, "communication.task_completed.v1", task_id) == 1
    assert probe.outbox_count(admin_conn, org, "communication.task_failed.v1", task_id) == 0


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_concurrent_identical_reports_produce_exactly_one_finalize_effect(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "duplicate-reports")
    task_id = world.new_task(admin_conn, org, status="delivering")
    delivery_id, idempotency_key = world.new_delivery(admin_conn, org, task_id)
    payload: dict[str, object] = {
        "dedupe_key": idempotency_key,
        "status": "delivered",
        "provider_message_id": f"msg-{uuid4().hex}",
    }
    first = await world.record_outcome_event(
        app_session_factory,
        org,
        provider_event_id=f"evt-a-{uuid4().hex}",
        payload=payload,
    )
    second = await world.record_outcome_event(
        app_session_factory,
        org,
        provider_event_id=f"evt-b-{uuid4().hex}",
        payload=dict(payload),
    )
    runtime = world.outcome_event_runtime(
        worker_session_factory,
        app_session_factory,
        concurrency=2,
    )

    outcomes = await runtime.run_once()

    assert sorted(o.state for o in outcomes) == [
        WorkerItemState.COMPLETED,
        WorkerItemState.COMPLETED,
    ]
    assert probe.event_row(admin_conn, first.id) == ("processed", None)
    assert probe.event_row(admin_conn, second.id) == ("processed", None)
    assert probe.delivery_status(admin_conn, delivery_id) == "delivered"
    assert probe.task_status(admin_conn, task_id) == "completed"
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s AND communication_task_id = %s
        """,
        (org, task_id),
    ).fetchone() == (1,)
    assert probe.outbox_count(admin_conn, org, "communication.task_completed.v1", task_id) == 1
    assert probe.outbox_count(admin_conn, org, "communication.task_failed.v1", task_id) == 0
