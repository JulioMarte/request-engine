from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.worker.delivery_worker import (
    CommunicationDeliveryWorker,
    DeliveryWorkerState,
)
from request_engine.modules.communications.application.errors import (
    DeliveryProviderNotConfigured,
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
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker

from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]

PAST = datetime(2000, 1, 1, tzinfo=UTC)
POLICY = {
    "channels": ["email"],
    "provider_key": "provider-a",
    "reconcile_after_seconds": 30,
    "retry_after_seconds": 30,
}


class ScriptedProvider(CommunicationDeliveryProvider):
    def __init__(
        self,
        *,
        send: ProviderDeliveryResult | Exception | None = None,
        lookup: ProviderDeliveryResult | Exception | None = None,
    ) -> None:
        self.send_result = send
        self.lookup_result = lookup
        self.send_calls: list[ProviderSendRequest] = []
        self.lookup_calls: list[ProviderLookupRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_calls.append(request)
        result = self.send_result
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise AssertionError("unexpected provider.send call")
        return result

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        result = self.lookup_result
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise AssertionError("unexpected provider.lookup call")
        return result


@asynccontextmanager
async def _worker_stack(
    credentials: support.RuntimeCredentialsLike,
    providers: Mapping[str, CommunicationDeliveryProvider],
) -> AsyncIterator[tuple[PostgresScheduledActionWorker, CommunicationDeliveryWorker]]:
    engine = create_postgres_engine(credentials.database_url)
    factory: SessionFactory = create_session_factory(engine)
    scheduler = PostgresScheduledActionWorker(factory)
    worker = CommunicationDeliveryWorker(factory, scheduler, providers)
    try:
        yield scheduler, worker
    finally:
        await engine.dispose()


def _seed_task(
    conn: support.PgConnection,
    organization_id: UUID,
    *,
    status: str = "pending",
) -> UUID:
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_id = support.new_contact_point(conn, organization_id, party_id, "delivery")
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id,
            recipient_party_id,
            contact_point_id,
            purpose,
            template_key,
            template_version,
            render_context,
            channel_policy,
            dedupe_key,
            status
        ) VALUES (
            %s, %s, %s, 'confirmation', 'booking-confirmed', 1,
            '{}'::jsonb, %s::jsonb, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_id,
            json.dumps(POLICY),
            f"delivery-e2e:{uuid4().hex}",
            status,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _seed_action(
    conn: support.PgConnection,
    organization_id: UUID,
    *,
    action_type: str,
    subject_kind: str,
    subject_id: UUID,
    payload_field: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            action_version,
            subject_kind,
            subject_id,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at
        ) VALUES (
            %s, 'communications', %s, 1, %s, %s, %s::jsonb, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            action_type,
            subject_kind,
            subject_id,
            json.dumps({payload_field: str(subject_id)}),
            f"communications-e2e:{action_type}:{uuid4().hex}",
            PAST,
            PAST,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _seed_dispatch(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
) -> UUID:
    return _seed_action(
        conn,
        organization_id,
        action_type="dispatch_task",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload_field="communication_task_id",
    )


def _seed_delivery(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    status: str,
    retryable: bool = False,
    provider_message_id: str | None = None,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id,
            communication_task_id,
            attempt_no,
            channel,
            provider_key,
            provider_idempotency_key,
            provider_message_id,
            status,
            result_data
        ) VALUES (
            %s, %s, 1, 'email', 'provider-a', %s, %s, %s, %s::jsonb
        )
        RETURNING id
        """,
        (
            organization_id,
            task_id,
            f"communication:{task_id}:attempt:1",
            provider_message_id,
            status,
            json.dumps({"retryable": retryable}),
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _seed_reconciliation(
    conn: support.PgConnection,
    organization_id: UUID,
    delivery_id: UUID,
) -> UUID:
    return _seed_action(
        conn,
        organization_id,
        action_type="reconcile_delivery",
        subject_kind="CommunicationDelivery",
        subject_id=delivery_id,
        payload_field="delivery_id",
    )


def _one_lease_type(
    leases: tuple[object, ...],
    expected_type: str,
) -> object:
    assert len(leases) == 1
    lease = leases[0]
    assert getattr(lease, "action_type") == expected_type
    return lease


@pytest.mark.asyncio
async def test_delivery_worker_delivered_send_completes_task_action_and_outbox(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-send-success")
    task_id = _seed_task(e2e_admin_conn, organization_id)
    action_id = _seed_dispatch(e2e_admin_conn, organization_id, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{uuid4().hex}",
        )
    )

    async with _worker_stack(
        worker_runtime_credentials,
        {"provider-a": provider},
    ) as (scheduler, worker):
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        lease = leases[0]
        assert lease.id == action_id
        outcome = await worker.process(lease)

    assert outcome.state is DeliveryWorkerState.COMPLETED
    assert outcome.detail == "delivered"
    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    request = provider.send_calls[0]
    assert request.communication_task_id == task_id
    assert request.provider_idempotency_key == f"communication:{task_id}:attempt:1"

    task = e2e_admin_conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (task_id,),
    ).fetchone()
    assert task == ("completed",)
    delivery = e2e_admin_conn.execute(
        """
        SELECT status, provider_message_id, result_data->>'retryable'
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery is not None
    assert delivery[0] == "delivered"
    assert delivery[1] is not None
    assert delivery[2] == "false"
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone() == ("completed",)
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'communication.task_completed.v1'
          AND aggregate_id = %s
        """,
        (organization_id, task_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_send_exception_becomes_ambiguous_and_schedules_reconciliation_not_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-ambiguous")
    task_id = _seed_task(e2e_admin_conn, organization_id)
    action_id = _seed_dispatch(e2e_admin_conn, organization_id, task_id)
    provider = ScriptedProvider(send=TimeoutError("provider response lost"))

    async with _worker_stack(
        worker_runtime_credentials,
        {"provider-a": provider},
    ) as (scheduler, worker):
        lease = (await scheduler.claim(limit=1))[0]
        outcome = await worker.process(lease)

    assert outcome.state is DeliveryWorkerState.COMPLETED
    assert outcome.detail == "ambiguous"
    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone() == ("completed",)
    delivery = e2e_admin_conn.execute(
        """
        SELECT id, status, result_data->>'error_phase'
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery is not None
    assert delivery[1:] == ("ambiguous", "send")
    delivery_id = cast(UUID, delivery[0])
    scheduled = e2e_admin_conn.execute(
        """
        SELECT action_type, subject_id, status, payload->>'delivery_id'
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND owner_module = 'communications'
          AND action_type = 'reconcile_delivery'
        """,
        (organization_id,),
    ).fetchall()
    assert scheduled == [("reconcile_delivery", delivery_id, "pending", str(delivery_id))]
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND status = 'pending'
        """,
        (organization_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_reconciliation_lookup_delivered_finishes_existing_delivery_without_send(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-reconcile")
    task_id = _seed_task(e2e_admin_conn, organization_id, status="delivering")
    delivery_id = _seed_delivery(
        e2e_admin_conn,
        organization_id,
        task_id,
        status="ambiguous",
        provider_message_id=f"msg-{uuid4().hex}",
    )
    action_id = _seed_reconciliation(e2e_admin_conn, organization_id, delivery_id)
    provider = ScriptedProvider(
        lookup=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-final-{uuid4().hex}",
        )
    )

    async with _worker_stack(
        worker_runtime_credentials,
        {"provider-a": provider},
    ) as (scheduler, worker):
        lease = (await scheduler.claim(limit=1))[0]
        assert lease.id == action_id
        outcome = await worker.process(lease)

    assert outcome.detail == "delivered"
    assert provider.send_calls == []
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == delivery_id
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (task_id,),
    ).fetchone() == ("completed",)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.communication_deliveries WHERE id = %s",
        (delivery_id,),
    ).fetchone() == ("delivered",)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone() == ("completed",)


@pytest.mark.asyncio
async def test_lookup_exception_retries_same_reconciliation_lease_without_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-lookup-retry")
    task_id = _seed_task(e2e_admin_conn, organization_id, status="delivering")
    delivery_id = _seed_delivery(
        e2e_admin_conn,
        organization_id,
        task_id,
        status="accepted",
        provider_message_id=f"msg-{uuid4().hex}",
    )
    action_id = _seed_reconciliation(e2e_admin_conn, organization_id, delivery_id)
    provider = ScriptedProvider(lookup=ConnectionError("provider unavailable"))

    async with _worker_stack(
        worker_runtime_credentials,
        {"provider-a": provider},
    ) as (scheduler, worker):
        lease = (await scheduler.claim(limit=1))[0]
        outcome = await worker.process(lease)

    assert outcome.state is DeliveryWorkerState.DEFERRED
    assert outcome.detail == "lookup_pending"
    assert provider.send_calls == []
    assert len(provider.lookup_calls) == 1
    action = e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, attempt_count, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert action is not None
    assert action[0:3] == ("pending", None, None)
    assert action[3] == 1
    assert action[4] == "lookup_ConnectionError"
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.communication_deliveries WHERE id = %s",
        (delivery_id,),
    ).fetchone() == ("accepted",)


@pytest.mark.asyncio
async def test_retryable_send_failure_schedules_exactly_one_future_dispatch(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-retryable")
    task_id = _seed_task(e2e_admin_conn, organization_id)
    original_action_id = _seed_dispatch(e2e_admin_conn, organization_id, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            retryable=True,
            result_data={"error_class": "provider_503"},
        )
    )

    async with _worker_stack(
        worker_runtime_credentials,
        {"provider-a": provider},
    ) as (scheduler, worker):
        lease = (await scheduler.claim(limit=1))[0]
        outcome = await worker.process(lease)

    assert outcome.detail == "failed"
    assert len(provider.send_calls) == 1
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (task_id,),
    ).fetchone() == ("pending",)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (original_action_id,),
    ).fetchone() == ("completed",)
    retries = e2e_admin_conn.execute(
        """
        SELECT id, status, subject_id, payload->>'communication_task_id'
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND id <> %s
        """,
        (organization_id, original_action_id),
    ).fetchall()
    assert len(retries) == 1
    assert retries[0][1:] == ("pending", task_id, str(task_id))
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'communication.task_failed.v1'
        """,
        (organization_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_non_retryable_send_failure_is_terminal_and_emits_failure_outbox(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-terminal-failure")
    task_id = _seed_task(e2e_admin_conn, organization_id)
    action_id = _seed_dispatch(e2e_admin_conn, organization_id, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            retryable=False,
            result_data={"error_class": "invalid_destination"},
        )
    )

    async with _worker_stack(
        worker_runtime_credentials,
        {"provider-a": provider},
    ) as (scheduler, worker):
        lease = (await scheduler.claim(limit=1))[0]
        outcome = await worker.process(lease)

    assert outcome.detail == "failed"
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (task_id,),
    ).fetchone() == ("failed",)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone() == ("completed",)
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND status = 'pending'
        """,
        (organization_id,),
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'communication.task_failed.v1'
          AND aggregate_id = %s
        """,
        (organization_id, task_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_missing_provider_dead_letters_claimed_dispatch_instead_of_releasing_it(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-provider-missing")
    task_id = _seed_task(e2e_admin_conn, organization_id)
    action_id = _seed_dispatch(e2e_admin_conn, organization_id, task_id)

    async with _worker_stack(worker_runtime_credentials, {}) as (scheduler, worker):
        lease = (await scheduler.claim(limit=1))[0]
        with pytest.raises(DeliveryProviderNotConfigured):
            await worker.process(lease)

    assert e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, last_error_class
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone() == ("dead", None, None, "provider_not_configured")
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (task_id,),
    ).fetchone() == ("delivering",)
