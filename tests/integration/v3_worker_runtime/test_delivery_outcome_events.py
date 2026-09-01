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
async def test_persisted_delivered_report_finalizes_delivery_and_completes_task(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "delivered")
    task_id = world.new_task(admin_conn, org, status="delivering")
    delivery_id, idempotency_key = world.new_delivery(admin_conn, org, task_id)
    receipt = await world.record_outcome_event(
        app_session_factory,
        org,
        provider_event_id=f"evt-{uuid4().hex}",
        payload={
            "dedupe_key": idempotency_key,
            "status": "delivered",
            "provider_message_id": f"msg-{uuid4().hex}",
        },
    )
    runtime = world.outcome_event_runtime(worker_session_factory, app_session_factory)

    outcomes = await runtime.run_once()

    assert [outcome.state for outcome in outcomes] == [WorkerItemState.COMPLETED]
    assert probe.delivery_status(admin_conn, delivery_id) == "delivered"
    assert probe.task_status(admin_conn, task_id) == "completed"
    assert probe.outbox_count(admin_conn, org, "communication.task_completed.v1", task_id) == 1
    assert probe.event_row(admin_conn, receipt.id) == ("processed", None)


@pytest.mark.asyncio
async def test_unknown_identity_report_is_durable_no_op_without_side_effects(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "unknown-key")
    task_id = world.new_task(admin_conn, org, status="delivering")
    delivery_id, _ = world.new_delivery(admin_conn, org, task_id)
    receipt = await world.record_outcome_event(
        app_session_factory,
        org,
        provider_event_id=f"evt-{uuid4().hex}",
        payload={
            "dedupe_key": f"communication:{uuid4()}:attempt:9",
            "status": "delivered",
        },
    )
    runtime = world.outcome_event_runtime(worker_session_factory, app_session_factory)

    outcomes = await runtime.run_once()

    assert [outcome.state for outcome in outcomes] == [WorkerItemState.COMPLETED]
    assert probe.event_row(admin_conn, receipt.id) == ("processed", None)
    assert probe.delivery_status(admin_conn, delivery_id) == "accepted"
    assert probe.task_status(admin_conn, task_id) == "delivering"
    assert probe.outbox_count(admin_conn, org, "communication.task_completed.v1", task_id) == 0
    assert probe.outbox_count(admin_conn, org, "communication.task_failed.v1", task_id) == 0
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s
        """,
        (org,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_malformed_report_is_rejected_as_typed_poison_fact(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "malformed")
    task_id = world.new_task(admin_conn, org, status="delivering")
    delivery_id, _ = world.new_delivery(admin_conn, org, task_id)
    receipt = await world.record_outcome_event(
        app_session_factory,
        org,
        provider_event_id=f"evt-{uuid4().hex}",
        payload={"status": "delivered"},
    )
    runtime = world.outcome_event_runtime(worker_session_factory, app_session_factory)

    outcomes = await runtime.run_once()

    assert [outcome.state for outcome in outcomes] == [WorkerItemState.REJECTED]
    assert probe.event_row(admin_conn, receipt.id) == (
        "rejected",
        "delivery_outcome_report_missing_identity",
    )
    assert probe.delivery_status(admin_conn, delivery_id) == "accepted"
    assert probe.task_status(admin_conn, task_id) == "delivering"
    assert probe.outbox_count(admin_conn, org, "communication.task_completed.v1", task_id) == 0
