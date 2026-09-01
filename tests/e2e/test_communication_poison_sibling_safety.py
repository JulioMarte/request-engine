from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)
from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.worker.runtime import PermanentWorkError

from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


class DeliveredProvider(CommunicationDeliveryProvider):
    def __init__(self) -> None:
        self.send_calls: list[ProviderSendRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_calls.append(request)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{request.delivery_id}",
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        raise AssertionError(f"unexpected provider lookup for {request.delivery_id}")


@asynccontextmanager
async def _worker_stack(
    credentials: support.RuntimeCredentialsLike,
    provider: CommunicationDeliveryProvider,
) -> AsyncGenerator[tuple[PostgresScheduledActionWorker, CommunicationDeliveryScheduledHandler]]:
    domain_database_url = getattr(credentials, "domain_database_url", None)
    assert domain_database_url is not None, "delivery work requires separate app credentials"
    worker_engine = create_postgres_engine(credentials.database_url)
    domain_engine = create_postgres_engine(domain_database_url)
    worker_factory: SessionFactory = create_session_factory(worker_engine)
    domain_factory: SessionFactory = create_session_factory(domain_engine)
    scheduler = PostgresScheduledActionWorker(worker_factory)
    try:
        yield (
            scheduler,
            CommunicationDeliveryScheduledHandler(
                domain_factory,
                scheduler,
                {"provider-a": provider},
            ),
        )
    finally:
        await domain_engine.dispose()
        await worker_engine.dispose()


async def _fail_poisoned_action(
    scheduler: PostgresScheduledActionWorker,
    handler: CommunicationDeliveryScheduledHandler,
    lease: ScheduledActionLease,
) -> str:
    """Drive poison work to its typed permanent failure, then fence the action
    into the dead letter exactly as the ``FencedWorkerRuntime`` does for a
    ``PermanentWorkError``."""

    with pytest.raises(PermanentWorkError) as exc_info:
        await handler.handle(lease)
    assert await scheduler.dead_letter(lease, error_class=exc_info.value.error_class)
    return exc_info.value.error_class


def _task(conn: support.PgConnection, organization_id: UUID) -> UUID:
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_id = support.new_contact_point(conn, organization_id, party_id, "poison-sibling")
    policy = {
        "channels": ["email"],
        "provider_key": "provider-a",
        "reconcile_after_seconds": 30,
        "retry_after_seconds": 30,
    }
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id,
            purpose, template_key, template_version, render_context,
            channel_policy, dedupe_key, status
        ) VALUES (
            %s, %s, %s, 'confirmation', 'booking-confirmed', 1,
            '{}'::jsonb, %s::jsonb, %s, 'pending'
        )
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_id,
            json.dumps(policy),
            f"poison-sibling-task:{uuid4().hex}",
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _action(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    action_type: str,
    payload: dict[str, str],
    execute_at: datetime,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at
        ) VALUES (
            %s, 'communications', %s, 1,
            'CommunicationTask', %s, %s::jsonb, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            action_type,
            task_id,
            json.dumps(payload),
            f"poison-sibling-action:{uuid4().hex}",
            execute_at,
            execute_at,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _task_status(conn: support.PgConnection, task_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (task_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def _action_status(conn: support.PgConnection, action_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def _event_count(
    conn: support.PgConnection,
    organization_id: UUID,
    event_type: str,
    task_id: UUID,
) -> int:
    row = conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = %s
          AND aggregate_id = %s
        """,
        (organization_id, event_type, task_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.asyncio
async def test_poison_action_does_not_terminalize_task_with_valid_dispatch_sibling(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-poison-sibling")
    task_id = _task(e2e_admin_conn, organization_id)
    poison_id = _action(
        e2e_admin_conn,
        organization_id,
        task_id,
        action_type="unknown_action",
        payload={},
        execute_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    valid_id = _action(
        e2e_admin_conn,
        organization_id,
        task_id,
        action_type="dispatch_task",
        payload={"communication_task_id": str(task_id).upper()},
        execute_at=datetime(2000, 1, 2, tzinfo=UTC),
    )
    provider = DeliveredProvider()

    async with _worker_stack(worker_runtime_credentials, provider) as (scheduler, handler):
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        assert leases[0].id == poison_id
        await _fail_poisoned_action(scheduler, handler, leases[0])

        assert _action_status(e2e_admin_conn, poison_id) == "dead"
        assert _action_status(e2e_admin_conn, valid_id) == "pending"
        assert _task_status(e2e_admin_conn, task_id) == "pending"
        assert (
            _event_count(
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
    assert _action_status(e2e_admin_conn, valid_id) == "completed"
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert (
        _event_count(
            e2e_admin_conn,
            organization_id,
            "communication.task_failed.v1",
            task_id,
        )
        == 0
    )
    assert (
        _event_count(
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
    task_id = _task(e2e_admin_conn, organization_id)
    poison_id = _action(
        e2e_admin_conn,
        organization_id,
        task_id,
        action_type="unknown_action",
        payload={},
        execute_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    malformed_sibling_id = _action(
        e2e_admin_conn,
        organization_id,
        task_id,
        action_type="dispatch_task",
        payload={"communication_task_id": str(uuid4())},
        execute_at=datetime(2000, 1, 2, tzinfo=UTC),
    )
    provider = DeliveredProvider()

    async with _worker_stack(worker_runtime_credentials, provider) as (scheduler, handler):
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        assert leases[0].id == poison_id
        await _fail_poisoned_action(scheduler, handler, leases[0])

    assert provider.send_calls == []
    assert _action_status(e2e_admin_conn, poison_id) == "dead"
    assert _action_status(e2e_admin_conn, malformed_sibling_id) == "pending"
    assert _task_status(e2e_admin_conn, task_id) == "failed"
    assert (
        _event_count(
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
    task_id = _task(e2e_admin_conn, organization_id)
    poison_id = _action(
        e2e_admin_conn,
        organization_id,
        task_id,
        action_type="unknown_action",
        payload={},
        execute_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    exhausted_sibling_id = _action(
        e2e_admin_conn,
        organization_id,
        task_id,
        action_type="dispatch_task",
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

    async with _worker_stack(worker_runtime_credentials, provider) as (scheduler, handler):
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        assert leases[0].id == poison_id
        await _fail_poisoned_action(scheduler, handler, leases[0])

    assert provider.send_calls == []
    assert _action_status(e2e_admin_conn, poison_id) == "dead"
    exhausted_state = e2e_admin_conn.execute(
        """
        SELECT status, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (exhausted_sibling_id,),
    ).fetchone()
    assert exhausted_state == ("dead", "max_attempts_exhausted")
    assert _task_status(e2e_admin_conn, task_id) == "failed"
    assert (
        _event_count(
            e2e_admin_conn,
            organization_id,
            "communication.task_failed.v1",
            task_id,
        )
        == 1
    )
