from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    finalize_provider_result,
    prepare_dispatch,
)
from request_engine.modules.communications.adapters.worker.delivery_worker import (
    CommunicationDeliveryWorker,
    DeliveryWorkerOutcome,
    DeliveryWorkerState,
)
from request_engine.modules.communications.application.errors import (
    DeliveryProviderNotConfigured,
    UnsupportedScheduledAction,
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
    tenant_transaction,
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
        if isinstance(self.send_result, Exception):
            raise self.send_result
        if self.send_result is None:
            raise AssertionError("unexpected provider.send call")
        return self.send_result

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        if isinstance(self.lookup_result, Exception):
            raise self.lookup_result
        if self.lookup_result is None:
            raise AssertionError("unexpected provider.lookup call")
        return self.lookup_result


class UniqueDeliveredProvider(CommunicationDeliveryProvider):
    def __init__(self) -> None:
        self.send_calls: list[ProviderSendRequest] = []
        self.lookup_calls: list[ProviderLookupRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_calls.append(request)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{request.delivery_id}",
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        raise AssertionError("contention scenario must not reconcile")


@asynccontextmanager
async def _worker_stack(
    credentials: support.RuntimeCredentialsLike,
    providers: Mapping[str, CommunicationDeliveryProvider],
) -> AsyncGenerator[
    tuple[SessionFactory, PostgresScheduledActionWorker, CommunicationDeliveryWorker],
]:
    domain_database_url = getattr(credentials, "domain_database_url", None)
    assert domain_database_url is not None, "delivery work requires separate app credentials"
    worker_engine = create_postgres_engine(credentials.database_url)
    domain_engine = create_postgres_engine(domain_database_url)
    worker_factory: SessionFactory = create_session_factory(worker_engine)
    domain_factory: SessionFactory = create_session_factory(domain_engine)
    scheduler = PostgresScheduledActionWorker(worker_factory)
    try:
        yield (
            domain_factory,
            scheduler,
            CommunicationDeliveryWorker(domain_factory, scheduler, providers),
        )
    finally:
        await domain_engine.dispose()
        await worker_engine.dispose()


def _task(
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
            organization_id, recipient_party_id, contact_point_id,
            purpose, template_key, template_version, render_context,
            channel_policy, dedupe_key, status
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


def _action(
    conn: support.PgConnection,
    organization_id: UUID,
    *,
    action_type: str,
    subject_kind: str,
    subject_id: UUID,
    payload: dict[str, str],
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at
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
            json.dumps(payload),
            f"communications-e2e:{action_type}:{uuid4().hex}",
            PAST,
            PAST,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _dispatch(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    payload_task_id: UUID | None = None,
) -> UUID:
    return _action(
        conn,
        organization_id,
        action_type="dispatch_task",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={"communication_task_id": str(payload_task_id or task_id)},
    )


def _delivery(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    status: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, provider_message_id,
            status, result_data
        ) VALUES (%s, %s, 1, 'email', 'provider-a', %s, %s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            task_id,
            f"communication:{task_id}:attempt:1",
            f"msg-{uuid4().hex}",
            status,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _reconcile(
    conn: support.PgConnection,
    organization_id: UUID,
    delivery_id: UUID,
) -> UUID:
    return _action(
        conn,
        organization_id,
        action_type="reconcile_delivery",
        subject_kind="CommunicationDelivery",
        subject_id=delivery_id,
        payload={"delivery_id": str(delivery_id)},
    )


def _task_status(conn: support.PgConnection, row_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (row_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def _delivery_status(conn: support.PgConnection, row_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.communication_deliveries WHERE id = %s",
        (row_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def _action_status(conn: support.PgConnection, row_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (row_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def _events(
    conn: support.PgConnection,
    organization_id: UUID,
    event_type: str,
    aggregate_id: UUID,
) -> int:
    row = conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s AND event_type = %s AND aggregate_id = %s
        """,
        (organization_id, event_type, aggregate_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


async def _claim_and_process(
    scheduler: PostgresScheduledActionWorker,
    worker: CommunicationDeliveryWorker,
) -> DeliveryWorkerOutcome:
    leases = await scheduler.claim(limit=1)
    assert len(leases) == 1
    return await worker.process(leases[0])


@pytest.mark.asyncio
async def test_delivered_send_completes_task_action_and_outbox(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-success")
    task_id = _task(e2e_admin_conn, org)
    action_id = _dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{uuid4().hex}",
        )
    )

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, scheduler, worker = stack
        outcome = await _claim_and_process(scheduler, worker)

    assert outcome.detail == "delivered"
    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert provider.send_calls[0].provider_idempotency_key == (f"communication:{task_id}:attempt:1")
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert _action_status(e2e_admin_conn, action_id) == "completed"
    assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1


@pytest.mark.asyncio
async def test_send_exception_becomes_ambiguous_and_schedules_lookup_not_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-ambiguous")
    task_id = _task(e2e_admin_conn, org)
    action_id = _dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(send=TimeoutError("provider response lost"))

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, scheduler, worker = stack
        outcome = await _claim_and_process(scheduler, worker)

    assert outcome.detail == "ambiguous"
    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert _action_status(e2e_admin_conn, action_id) == "completed"
    delivery = e2e_admin_conn.execute(
        """
        SELECT id, status, result_data->>'error_phase'
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery is not None
    delivery_id = cast(UUID, delivery[0])
    assert delivery[1:] == ("ambiguous", "send")
    reconciliations = e2e_admin_conn.execute(
        """
        SELECT subject_id, status
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s AND action_type = 'reconcile_delivery'
        """,
        (org,),
    ).fetchall()
    assert reconciliations == [(delivery_id, "pending")]
    pending_resends = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND status = 'pending'
        """,
        (org,),
    ).fetchone()
    assert pending_resends == (0,)


@pytest.mark.asyncio
async def test_reconciliation_delivered_uses_lookup_without_second_send(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-reconcile")
    task_id = _task(e2e_admin_conn, org, status="delivering")
    delivery_id = _delivery(e2e_admin_conn, org, task_id, status="ambiguous")
    action_id = _reconcile(e2e_admin_conn, org, delivery_id)
    provider = ScriptedProvider(
        lookup=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-final-{uuid4().hex}",
        )
    )

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, scheduler, worker = stack
        outcome = await _claim_and_process(scheduler, worker)

    assert outcome.detail == "delivered"
    assert provider.send_calls == []
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == delivery_id
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert _delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert _action_status(e2e_admin_conn, action_id) == "completed"


@pytest.mark.asyncio
async def test_lookup_exception_retries_same_action_without_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-lookup-retry")
    task_id = _task(e2e_admin_conn, org, status="delivering")
    delivery_id = _delivery(e2e_admin_conn, org, task_id, status="accepted")
    action_id = _reconcile(e2e_admin_conn, org, delivery_id)
    provider = ScriptedProvider(lookup=ConnectionError("provider unavailable"))

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, scheduler, worker = stack
        outcome = await _claim_and_process(scheduler, worker)

    assert outcome.state is DeliveryWorkerState.DEFERRED
    assert outcome.detail == "lookup_pending"
    assert provider.send_calls == []
    action = e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, attempt_count, last_error_class
        FROM request_engine.scheduled_actions WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert action == ("pending", None, None, 1, "lookup_ConnectionError")
    assert _delivery_status(e2e_admin_conn, delivery_id) == "accepted"


@pytest.mark.asyncio
async def test_retryable_failure_schedules_exactly_one_future_dispatch(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-retryable")
    task_id = _task(e2e_admin_conn, org)
    original_id = _dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            retryable=True,
            result_data={"error_class": "provider_503"},
        )
    )

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, scheduler, worker = stack
        outcome = await _claim_and_process(scheduler, worker)

    assert outcome.detail == "failed"
    assert _task_status(e2e_admin_conn, task_id) == "failed"
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1
    assert _action_status(e2e_admin_conn, original_id) == "completed"
    retries = e2e_admin_conn.execute(
        """
        SELECT status, subject_id
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND id <> %s
        """,
        (org, original_id),
    ).fetchall()
    assert retries == [("pending", task_id)]
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 0


@pytest.mark.asyncio
async def test_non_retryable_failure_is_terminal_and_emits_failure_event(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-terminal")
    task_id = _task(e2e_admin_conn, org)
    action_id = _dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        send=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.FAILED,
            retryable=False,
            result_data={"error_class": "invalid_destination"},
        )
    )

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        _, scheduler, worker = stack
        await _claim_and_process(scheduler, worker)

    assert _task_status(e2e_admin_conn, task_id) == "failed"
    assert _action_status(e2e_admin_conn, action_id) == "completed"
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1


@pytest.mark.asyncio
async def test_missing_provider_fails_domain_state_before_dead_lettering_action(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-provider-missing")
    task_id = _task(e2e_admin_conn, org)
    action_id = _dispatch(e2e_admin_conn, org, task_id)

    async with _worker_stack(worker_runtime_credentials, {}) as stack:
        _, scheduler, worker = stack
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        with pytest.raises(DeliveryProviderNotConfigured):
            await worker.process(leases[0])

    action = e2e_admin_conn.execute(
        """
        SELECT status, claim_token, lease_until, last_error_class
        FROM request_engine.scheduled_actions WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert action == ("dead", None, None, "provider_not_configured")
    assert _task_status(e2e_admin_conn, task_id) == "failed"
    delivery = e2e_admin_conn.execute(
        """
        SELECT status, result_data->>'error_class', result_data->>'error_phase'
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery == ("failed", "provider_not_configured", "provider_resolution")
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1


@pytest.mark.asyncio
async def test_unsupported_action_is_dead_lettered_as_permanent_poison_work(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-poison-type")
    task_id = _task(e2e_admin_conn, org)
    action_id = _action(
        e2e_admin_conn,
        org,
        action_type="unknown_action",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={},
    )

    async with _worker_stack(worker_runtime_credentials, {}) as stack:
        _, scheduler, worker = stack
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        with pytest.raises(UnsupportedScheduledAction):
            await worker.process(leases[0])

    row = e2e_admin_conn.execute(
        "SELECT status, last_error_class FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert row == ("dead", "unsupported_scheduled_action")
    assert _task_status(e2e_admin_conn, task_id) == "pending"


@pytest.mark.asyncio
async def test_payload_identity_mismatch_dead_letters_action_and_fails_orphaned_task(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-poison-payload")
    task_id = _task(e2e_admin_conn, org)
    action_id = _dispatch(e2e_admin_conn, org, task_id, payload_task_id=uuid4())

    async with _worker_stack(worker_runtime_credentials, {}) as stack:
        _, scheduler, worker = stack
        leases = await scheduler.claim(limit=1)
        assert len(leases) == 1
        with pytest.raises(ValueError, match="does not match subject identity"):
            await worker.process(leases[0])

    row = e2e_admin_conn.execute(
        "SELECT status, last_error_class FROM request_engine.scheduled_actions WHERE id = %s",
        (action_id,),
    ).fetchone()
    assert row == ("dead", "invalid_scheduled_action")
    assert _task_status(e2e_admin_conn, task_id) == "failed"
    assert _events(e2e_admin_conn, org, "communication.task_failed.v1", task_id) == 1
    delivery_count = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery_count == (0,)


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_crash_after_provider_finalize_before_action_ack_reclaims_without_second_send(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-crash-after-finalize")
    task_id = _task(e2e_admin_conn, org)
    action_id = _dispatch(e2e_admin_conn, org, task_id)
    provider = UniqueDeliveredProvider()

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        factory, scheduler, worker = stack
        leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(leases) == 1
        first_lease = leases[0]
        assert first_lease.id == action_id

        async with tenant_transaction(factory, org) as session:
            prepared = await prepare_dispatch(
                session,
                organization_id=org,
                communication_task_id=task_id,
            )
        assert prepared.send_request is not None
        provider_result = await provider.send(prepared.send_request)
        assert prepared.delivery_id is not None
        async with tenant_transaction(factory, org) as session:
            finalized = await finalize_provider_result(
                session,
                organization_id=org,
                delivery_id=prepared.delivery_id,
                result=provider_result,
            )
        assert finalized.status is ProviderDeliveryStatus.DELIVERED
        assert _task_status(e2e_admin_conn, task_id) == "completed"
        assert _action_status(e2e_admin_conn, action_id) != "completed"

        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (action_id,),
        )
        reclaimed = await scheduler.claim(limit=1)
        assert len(reclaimed) == 1
        assert reclaimed[0].id == action_id
        assert reclaimed[0].claim_token != first_lease.claim_token

        replay = await worker.process(reclaimed[0])
        assert replay.detail in {"already_delivered", "task_completed"}
        assert await scheduler.complete(first_lease) is False

    assert len(provider.send_calls) == 1
    assert provider.lookup_calls == []
    assert _action_status(e2e_admin_conn, action_id) == "completed"
    delivery_count = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert delivery_count == (1,)
    assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_crash_after_prepare_reconciles_existing_attempt_before_any_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-crash-after-prepare")
    task_id = _task(e2e_admin_conn, org)
    action_id = _dispatch(e2e_admin_conn, org, task_id)
    provider = ScriptedProvider(
        lookup=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"reconciled-{uuid4().hex}",
        )
    )

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        factory, scheduler, worker = stack
        leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(leases) == 1
        first_lease = leases[0]

        async with tenant_transaction(factory, org) as session:
            prepared = await prepare_dispatch(
                session,
                organization_id=org,
                communication_task_id=task_id,
            )
        assert prepared.delivery_id is not None
        assert prepared.send_request is not None

        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (action_id,),
        )
        reclaimed = await scheduler.claim(limit=1)
        assert len(reclaimed) == 1
        assert reclaimed[0].claim_token != first_lease.claim_token
        outcome = await worker.process(reclaimed[0])

    assert outcome.detail == "delivered"
    assert provider.send_calls == []
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == prepared.delivery_id
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert _delivery_status(e2e_admin_conn, prepared.delivery_id) == "delivered"
    assert _action_status(e2e_admin_conn, action_id) == "completed"
    assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_three_delivery_workers_claim_disjoint_work_and_each_task_sends_once(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    org = support.new_org(e2e_admin_conn, "delivery-contention")
    task_ids = tuple(_task(e2e_admin_conn, org) for _ in range(12))
    action_ids = tuple(_dispatch(e2e_admin_conn, org, task_id) for task_id in task_ids)
    provider = UniqueDeliveredProvider()

    async with _worker_stack(worker_runtime_credentials, {"provider-a": provider}) as stack:
        factory, _, _ = stack
        schedulers = tuple(PostgresScheduledActionWorker(factory) for _ in range(3))
        workers = tuple(
            CommunicationDeliveryWorker(factory, scheduler, {"provider-a": provider})
            for scheduler in schedulers
        )
        claimed_groups = await asyncio.gather(
            *(scheduler.claim(limit=4) for scheduler in schedulers)
        )
        claimed = tuple(lease for group in claimed_groups for lease in group)
        assert len(claimed) == 12
        assert {lease.id for lease in claimed} == set(action_ids)
        assert len({lease.claim_token for lease in claimed}) == 12

        await asyncio.gather(
            *(
                worker.process(lease)
                for worker, group in zip(workers, claimed_groups, strict=True)
                for lease in group
            )
        )

    assert len(provider.send_calls) == 12
    assert provider.lookup_calls == []
    assert len({call.provider_idempotency_key for call in provider.send_calls}) == 12
    for task_id in task_ids:
        assert _task_status(e2e_admin_conn, task_id) == "completed"
        assert _events(e2e_admin_conn, org, "communication.task_completed.v1", task_id) == 1
    for action_id in action_ids:
        assert _action_status(e2e_admin_conn, action_id) == "completed"
