from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.communications.adapters.db.communication_commands import (
    PostgresCommunicationCommands,
)
from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.modules.communications.application.commands.create_communication_task import (
    CreateCommunicationTaskCommand,
    create_communication_task,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.worker.runtime import LeaseLostWorkError

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class Fixture:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    contact_point_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection) -> Fixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"fence-{suffix}", f"Fence {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'worker', %s)
        RETURNING id
        """,
        (organization_id, f"worker-{suffix}"),
    )
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Recipient {suffix}"),
    )
    contact_point_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, 'whatsapp', %s, true)
        RETURNING id
        """,
        (organization_id, party_id, f"+1809{suffix[:7]}"),
    )
    return Fixture(organization_id, principal_id, party_id, contact_point_id)


async def _create_task(fixture: Fixture, session_factory: SessionFactory) -> UUID:
    task = await create_communication_task(
        PostgresCommunicationCommands(session_factory),
        CreateCommunicationTaskCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            recipient_party_id=fixture.party_id,
            contact_point_id=fixture.contact_point_id,
            purpose="appointment_confirmation",
            template_key="appointment-confirmation",
            template_version=1,
            channel_policy={
                "channels": ["whatsapp"],
                "provider_key": "stealing-provider",
                "reconcile_after_seconds": 30,
                "retry_after_seconds": 30,
            },
            render_context={"reservation_id": str(uuid4())},
            dedupe_key=f"fence-task:{uuid4().hex}",
            idempotency_key=f"fence-command:{uuid4().hex}",
        ),
    )
    return task.id


async def _claim_for_subject(
    scheduler: PostgresScheduledActionWorker,
    subject_id: UUID,
) -> ScheduledActionLease:
    leases = await scheduler.claim(limit=500)
    return next(lease for lease in leases if lease.subject_id == subject_id)


class LeaseStealingProvider:
    def __init__(
        self,
        *,
        admin_conn: PgConnection,
        scheduler: PostgresScheduledActionWorker,
        action_id: UUID,
    ) -> None:
        self._admin_conn = admin_conn
        self._scheduler = scheduler
        self._action_id = action_id
        self.replacement_lease: ScheduledActionLease | None = None
        self.send_count = 0
        self.lookup_count = 0

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        del request
        self.send_count += 1
        self._admin_conn.execute(
            """
            UPDATE request_engine.scheduled_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (self._action_id,),
        )
        leases = await self._scheduler.claim(limit=500)
        self.replacement_lease = next(lease for lease in leases if lease.id == self._action_id)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id="provider-message-1",
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        del request
        self.lookup_count += 1
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id="provider-message-1",
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_worker_that_loses_lease_during_provider_io_cannot_finalize_delivery(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    task_id = await _create_task(fixture, session_factory)
    scheduler = PostgresScheduledActionWorker(session_factory)
    original_lease = await _claim_for_subject(scheduler, task_id)
    provider = LeaseStealingProvider(
        admin_conn=admin_conn,
        scheduler=scheduler,
        action_id=original_lease.id,
    )
    handler = CommunicationDeliveryScheduledHandler(
        session_factory,
        scheduler,
        {"stealing-provider": provider},
    )

    with pytest.raises(LeaseLostWorkError):
        await handler.handle(original_lease)

    assert provider.replacement_lease is not None
    assert provider.replacement_lease.claim_token != original_lease.claim_token
    assert admin_conn.execute(
        """
        SELECT status
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s AND communication_task_id = %s
        ORDER BY attempt_no DESC
        LIMIT 1
        """,
        (fixture.organization_id, task_id),
    ).fetchone() == ("attempting",)
    assert admin_conn.execute(
        """
        SELECT status
        FROM request_engine.communication_tasks
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, task_id),
    ).fetchone() == ("delivering",)

    await handler.handle(provider.replacement_lease)
    assert await scheduler.complete(provider.replacement_lease) is True

    assert provider.send_count == 1
    assert provider.lookup_count == 1
    assert admin_conn.execute(
        """
        SELECT status, provider_message_id
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s AND communication_task_id = %s
        ORDER BY attempt_no DESC
        LIMIT 1
        """,
        (fixture.organization_id, task_id),
    ).fetchone() == ("delivered", "provider-message-1")
    assert admin_conn.execute(
        """
        SELECT status
        FROM request_engine.communication_tasks
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, task_id),
    ).fetchone() == ("completed",)
