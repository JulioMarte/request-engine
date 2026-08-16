from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.worker.delivery_worker import (
    CommunicationDeliveryWorker,
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


@asynccontextmanager
async def _worker_stack(
    credentials: support.RuntimeCredentialsLike,
    providers: dict[str, CommunicationDeliveryProvider],
) -> AsyncGenerator[
    tuple[SessionFactory, PostgresScheduledActionWorker, CommunicationDeliveryWorker]
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
            worker_factory,
            scheduler,
            CommunicationDeliveryWorker(domain_factory, scheduler, providers),
        )
    finally:
        await domain_engine.dispose()
        await worker_engine.dispose()


def _task_and_action(
    conn: support.PgConnection,
    organization_id: UUID,
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
            execute_at, next_attempt_at
        ) VALUES (
            %s, 'communications', 'dispatch_task', 1,
            'CommunicationTask', %s, %s::jsonb, %s, %s, %s
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
        ),
    ).fetchone()
    assert action_row is not None
    return task_id, cast(UUID, action_row[0])


def _status(conn: support.PgConnection, table: str, row_id: UUID) -> str:
    assert table in {"communication_tasks", "communication_deliveries", "scheduled_actions"}
    row = conn.execute(
        f"SELECT status FROM request_engine.{table} WHERE id = %s",
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
        worker_factory, scheduler, worker = stack
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
            await worker.process(first_lease)

        assert provider.reclaimed is not None
        assert provider.reclaimed.id == action_id
        assert provider.reclaimed.claim_token != first_lease.claim_token
        delivery_id = _delivery_id(e2e_admin_conn, task_id)
        assert _status(e2e_admin_conn, "communication_tasks", task_id) == "delivering"
        assert _status(e2e_admin_conn, "communication_deliveries", delivery_id) == "attempting"
        assert _status(e2e_admin_conn, "scheduled_actions", action_id) == "leased"
        assert _completion_events(e2e_admin_conn, organization_id, task_id) == 0

        outcome = await worker.process(provider.reclaimed)

    assert outcome.detail == "delivered"
    assert len(provider.send_calls) == 1
    assert len(provider.lookup_calls) == 1
    assert provider.lookup_calls[0].delivery_id == delivery_id
    assert _status(e2e_admin_conn, "communication_tasks", task_id) == "completed"
    assert _status(e2e_admin_conn, "communication_deliveries", delivery_id) == "delivered"
    assert _status(e2e_admin_conn, "scheduled_actions", action_id) == "completed"
    assert _completion_events(e2e_admin_conn, organization_id, task_id) == 1
