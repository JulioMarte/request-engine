from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import prepare_dispatch
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
    tenant_transaction,
)
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.worker.runtime import LeaseLostWorkError

from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.concurrency]


class ReclaimDuringSendProvider(CommunicationDeliveryProvider):
    def __init__(
        self,
        admin_conn: support.PgConnection,
        action_id: UUID,
        competitor: PostgresScheduledActionWorker,
    ) -> None:
        self._admin_conn = admin_conn
        self._action_id = action_id
        self._competitor = competitor
        self.send_calls: list[ProviderSendRequest] = []
        self.lookup_calls: list[ProviderLookupRequest] = []
        self.reclaimed: ScheduledActionLease | None = None

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_calls.append(request)
        self._admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (self._action_id,),
        )
        reclaimed = await self._competitor.claim(limit=1)
        assert len(reclaimed) == 1
        self.reclaimed = reclaimed[0]
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{request.delivery_id}",
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{request.delivery_id}",
        )


class ReplayRecoveryProvider(CommunicationDeliveryProvider):
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
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{request.delivery_id}",
        )


@asynccontextmanager
async def _worker_stack(
    credentials: support.RuntimeCredentialsLike,
    providers: dict[str, CommunicationDeliveryProvider],
) -> AsyncGenerator[
    tuple[
        SessionFactory,
        SessionFactory,
        PostgresScheduledActionWorker,
        CommunicationDeliveryScheduledHandler,
    ]
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
            worker_factory,
            scheduler,
            CommunicationDeliveryScheduledHandler(domain_factory, scheduler, providers),
        )
    finally:
        await domain_engine.dispose()
        await worker_engine.dispose()


def _task_and_action(
    conn: support.PgConnection,
    organization_id: UUID,
    *,
    max_attempts: int = 8,
) -> tuple[UUID, UUID]:
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_id = support.new_contact_point(conn, organization_id, party_id, "lease-fence")
    policy = {
        "channels": ["email"],
        "provider_key": "provider-a",
        "reconcile_after_seconds": 30,
        "retry_after_seconds": 30,
    }
    task_row = conn.execute(
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
            f"lease-fence-task:{uuid4().hex}",
        ),
    ).fetchone()
    assert task_row is not None
    task_id = cast(UUID, task_row[0])
    execute_at = datetime(2000, 1, 1, tzinfo=UTC)
    action_row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at, max_attempts
        ) VALUES (
            %s, 'communications', 'dispatch_task', 1,
            'CommunicationTask', %s, %s::jsonb, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            task_id,
            json.dumps({"communication_task_id": str(task_id)}),
            f"lease-fence-action:{uuid4().hex}",
            execute_at,
            execute_at,
            max_attempts,
        ),
    ).fetchone()
    assert action_row is not None
    return task_id, cast(UUID, action_row[0])


def _principal(conn: support.PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"replay-operator-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


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


def _delivery_id(conn: support.PgConnection, task_id: UUID) -> UUID:
    row = conn.execute(
        """
        SELECT id
        FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _completion_events(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
) -> int:
    row = conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'communication.task_completed.v1'
          AND aggregate_id = %s
        """,
        (organization_id, task_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.asyncio
async def test_reclaimed_lease_fences_stale_provider_result_then_reconciles_without_resend(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-finalization-fence")
    task_id, action_id = _task_and_action(e2e_admin_conn, organization_id)
    providers: dict[str, CommunicationDeliveryProvider] = {}

    async with _worker_stack(worker_runtime_credentials, providers) as stack:
        _, worker_factory, scheduler, handler = stack
        competitor = PostgresScheduledActionWorker(worker_factory)
        provider = ReclaimDuringSendProvider(e2e_admin_conn, action_id, competitor)
        providers["provider-a"] = provider

        leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(leases) == 1
        first_lease = leases[0]
        assert first_lease.id == action_id

        with pytest.raises(
            LeaseLostWorkError,
            match="provider_result_finalization_fence_lost",
        ):
            await handler.handle(first_lease)

        assert provider.reclaimed is not None
        assert provider.reclaimed.id == action_id
        assert provider.reclaimed.claim_token != first_lease.claim_token
        delivery_id = _delivery_id(e2e_admin_conn, task_id)
        assert _task_status(e2e_admin_conn, task_id) == "delivering"
        assert _delivery_status(e2e_admin_conn, delivery_id) == "attempting"
        assert _action_status(e2e_admin_conn, action_id) == "leased"
        assert _completion_events(e2e_admin_conn, organization_id, task_id) == 0

        await handler.handle(provider.reclaimed)
        assert await scheduler.complete(provider.reclaimed) is True

    assert len(provider.send_calls) == 1
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == delivery_id
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert _delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert _action_status(e2e_admin_conn, action_id) == "completed"
    assert _completion_events(e2e_admin_conn, organization_id, task_id) == 1


@pytest.mark.asyncio
async def test_exhausted_crash_dead_letter_replay_recovers_without_second_send(
    e2e_admin_conn: support.PgConnection,
    worker_runtime_credentials: support.RuntimeCredentialsLike,
) -> None:
    organization_id = support.new_org(e2e_admin_conn, "delivery-exhausted-replay")
    task_id, action_id = _task_and_action(
        e2e_admin_conn,
        organization_id,
        max_attempts=1,
    )
    provider = ReplayRecoveryProvider()

    async with _worker_stack(
        worker_runtime_credentials,
        {"provider-a": provider},
    ) as (domain_factory, _, scheduler, handler):
        leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(leases) == 1
        first_lease = leases[0]
        assert first_lease.id == action_id
        assert first_lease.attempt_count == 1

        async with tenant_transaction(domain_factory, organization_id) as session:
            prepared = await prepare_dispatch(
                session,
                organization_id=organization_id,
                communication_task_id=task_id,
            )
        assert prepared.send_request is not None
        assert prepared.delivery_id is not None
        provider_result = await provider.send(prepared.send_request)
        assert provider_result.status is ProviderDeliveryStatus.DELIVERED
        delivery_id = prepared.delivery_id

        # Simulate a process crash after provider I/O but before result persistence
        # and before the ScheduledAction acknowledgement.
        e2e_admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (action_id,),
        )
        assert await scheduler.claim(limit=1) == ()

        dead_state = e2e_admin_conn.execute(
            """
            SELECT status, attempt_count, max_attempts, last_error_class
            FROM request_engine.scheduled_actions
            WHERE id = %s
            """,
            (action_id,),
        ).fetchone()
        assert dead_state == ("dead", 1, 1, "max_attempts_exhausted")
        assert _task_status(e2e_admin_conn, task_id) == "delivering"
        assert _delivery_status(e2e_admin_conn, delivery_id) == "attempting"
        assert _completion_events(e2e_admin_conn, organization_id, task_id) == 0

        actor_id = _principal(e2e_admin_conn, organization_id)
        correlation_id = uuid4()
        with e2e_admin_conn.transaction():
            e2e_admin_conn.execute(
                """
                SELECT
                    set_config('request_engine.organization_id', %s, true),
                    set_config('request_engine.authenticated_principal_id', %s, true),
                    set_config('request_engine.principal_kind', 'human', true),
                    set_config('request_engine.authentication_method', 'e2e_test_adapter', true),
                    set_config('request_engine.correlation_id', %s, true)
                """,
                (str(organization_id), str(actor_id), str(correlation_id)),
            )
            replayed = e2e_admin_conn.execute(
                """
                SELECT request_admin.replay_dead_scheduled_action(
                    %s, %s, 1, 'recover ambiguous provider attempt'
                )
                """,
                (organization_id, action_id),
            ).fetchone()
            assert replayed == (True,)

        replay_leases = await scheduler.claim(limit=1, lease=timedelta(seconds=30))
        assert len(replay_leases) == 1
        assert replay_leases[0].id == action_id
        assert replay_leases[0].attempt_count == 2
        await handler.handle(replay_leases[0])
        assert await scheduler.complete(replay_leases[0]) is True

    assert len(provider.send_calls) == 1
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == delivery_id
    assert _task_status(e2e_admin_conn, task_id) == "completed"
    assert _delivery_status(e2e_admin_conn, delivery_id) == "delivered"
    assert _action_status(e2e_admin_conn, action_id) == "completed"
    assert _completion_events(e2e_admin_conn, organization_id, task_id) == 1

    replay_state = e2e_admin_conn.execute(
        """
        SELECT attempt_count, max_attempts, replay_count,
               last_replayed_at IS NOT NULL
        FROM request_engine.scheduled_actions
        WHERE id = %s
        """,
        (action_id,),
    ).fetchone()
    assert replay_state == (2, 2, 1, True)
    audit = e2e_admin_conn.execute(
        """
        SELECT command_name,
               actor_principal_id,
               details->>'reason',
               correlation_data->>'correlation_id',
               correlation_data->>'principal_kind',
               correlation_data->>'authentication_method'
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'ScheduledAction'
          AND aggregate_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (organization_id, action_id),
    ).fetchone()
    assert audit == (
        "admin.replay_scheduled_action",
        actor_id,
        "recover ambiguous provider attempt",
        str(correlation_id),
        "human",
        "e2e_test_adapter",
    )
