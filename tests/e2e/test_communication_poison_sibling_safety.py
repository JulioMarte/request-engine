from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from . import operational_support as support
from .delivery_provider_fakes import DeliveredProvider
from .delivery_resilience_readers import action_status, event_count, task_status
from .delivery_resilience_store import new_action, new_task
from .delivery_resilience_world import PAST, fail_poisoned_action, worker_stack

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_poison_action_does_not_terminalize_task_with_valid_dispatch_sibling(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-poison-sibling")
    task_id = new_task(e2e_admin_conn, organization_id)
    poison_id = new_action(
        e2e_admin_conn,
        organization_id,
        action_type="unknown_action",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={},
        execute_at=PAST,
    )
    valid_id = new_action(
        e2e_admin_conn,
        organization_id,
        action_type="dispatch_task",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={"communication_task_id": str(task_id).upper()},
        execute_at=datetime(2000, 1, 2, tzinfo=UTC),
    )
    provider = DeliveredProvider()

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as (
        _,
        _,
        scheduler,
        handler,
    ):
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        assert leases[0].id == poison_id
        await fail_poisoned_action(scheduler, handler, leases[0])

        assert action_status(e2e_admin_conn, poison_id) == "dead"
        assert action_status(e2e_admin_conn, valid_id) == "pending"
        assert task_status(e2e_admin_conn, task_id) == "pending"
        assert (
            event_count(
                e2e_admin_conn,
                organization_id,
                "communication.task_failed.v1",
                task_id,
            )
            == 0
        )

        valid_leases = await scheduler.claim(limit=1)
        assert len(valid_leases) == 1
        assert valid_leases[0].id == valid_id
        await handler.handle(valid_leases[0])
        assert await scheduler.complete(valid_leases[0]) is True

    assert len(provider.send_calls) == 1
    assert action_status(e2e_admin_conn, valid_id) == "completed"
    assert task_status(e2e_admin_conn, task_id) == "completed"
    assert (
        event_count(
            e2e_admin_conn,
            organization_id,
            "communication.task_failed.v1",
            task_id,
        )
        == 0
    )
    assert (
        event_count(
            e2e_admin_conn,
            organization_id,
            "communication.task_completed.v1",
            task_id,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_malformed_dispatch_sibling_does_not_mask_orphaned_poison_task(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-malformed-sibling")
    task_id = new_task(e2e_admin_conn, organization_id)
    poison_id = new_action(
        e2e_admin_conn,
        organization_id,
        action_type="unknown_action",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={},
        execute_at=PAST,
    )
    malformed_sibling_id = new_action(
        e2e_admin_conn,
        organization_id,
        action_type="dispatch_task",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={"communication_task_id": str(uuid4())},
        execute_at=datetime(2000, 1, 2, tzinfo=UTC),
    )
    provider = DeliveredProvider()

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as (
        _,
        _,
        scheduler,
        handler,
    ):
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        assert leases[0].id == poison_id
        await fail_poisoned_action(scheduler, handler, leases[0])

    assert provider.send_calls == []
    assert action_status(e2e_admin_conn, poison_id) == "dead"
    assert action_status(e2e_admin_conn, malformed_sibling_id) == "pending"
    assert task_status(e2e_admin_conn, task_id) == "failed"
    assert (
        event_count(
            e2e_admin_conn,
            organization_id,
            "communication.task_failed.v1",
            task_id,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_exhausted_dispatch_sibling_does_not_mask_orphaned_poison_task(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-exhausted-sibling")
    task_id = new_task(e2e_admin_conn, organization_id)
    poison_id = new_action(
        e2e_admin_conn,
        organization_id,
        action_type="unknown_action",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={},
        execute_at=PAST,
    )
    exhausted_sibling_id = new_action(
        e2e_admin_conn,
        organization_id,
        action_type="dispatch_task",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={"communication_task_id": str(task_id)},
        execute_at=datetime(2000, 1, 2, tzinfo=UTC),
    )
    e2e_admin_conn.execute(
        """
        UPDATE request_engine.scheduled_actions
        SET attempt_count = max_attempts
        WHERE id = %s
        """,
        (exhausted_sibling_id,),
    )
    provider = DeliveredProvider()

    async with worker_stack(worker_runtime_credentials, {"provider-a": provider}) as (
        _,
        _,
        scheduler,
        handler,
    ):
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        assert leases[0].id == poison_id
        await fail_poisoned_action(scheduler, handler, leases[0])

    assert provider.send_calls == []
    assert action_status(e2e_admin_conn, poison_id) == "dead"
    exhausted_state = e2e_admin_conn.execute(
        """
        SELECT status, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (exhausted_sibling_id,),
    ).fetchone()
    assert exhausted_state == ("dead", "max_attempts_exhausted")
    assert task_status(e2e_admin_conn, task_id) == "failed"
    assert (
        event_count(
            e2e_admin_conn,
            organization_id,
            "communication.task_failed.v1",
            task_id,
        )
        == 1
    )
