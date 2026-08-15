from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.communications.adapters.db.communication_commands import (
    PostgresCommunicationCommands,
)
from request_engine.modules.communications.adapters.worker.delivery_worker import (
    CommunicationDeliveryWorker,
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
from request_engine.modules.communications.contracts.tasks import CommunicationTaskStatus
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class DeliveryFixture:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    contact_point_id: UUID


class FakeProvider:
    def __init__(
        self,
        *,
        send_results: list[ProviderDeliveryResult | Exception],
        lookup_results: list[ProviderDeliveryResult | Exception] | None = None,
        lock_probe: Callable[[UUID], None] | None = None,
    ) -> None:
        self._send_results = send_results
        self._lookup_results = lookup_results or []
        self._lock_probe = lock_probe
        self.send_requests: list[ProviderSendRequest] = []
        self.lookup_requests: list[ProviderLookupRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_requests.append(request)
        if self._lock_probe is not None:
            self._lock_probe(request.communication_task_id)
        if not self._send_results:
            raise AssertionError("unexpected provider send")
        result = self._send_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_requests.append(request)
        if not self._lookup_results:
            raise AssertionError("unexpected provider lookup")
        result = self._lookup_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_fixture(conn: PgConnection) -> DeliveryFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"delivery-{suffix}", f"Delivery Practice {suffix}"),
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
    return DeliveryFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        contact_point_id=contact_point_id,
    )


async def _create_due_task(
    fixture: DeliveryFixture,
    session_factory: SessionFactory,
    *,
    reconcile_after_seconds: int = 30,
    retry_after_seconds: int = 30,
) -> UUID:
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
                "provider_key": "fake",
                "reconcile_after_seconds": reconcile_after_seconds,
                "retry_after_seconds": retry_after_seconds,
            },
            render_context={"reservation_id": str(uuid4())},
            dedupe_key=f"delivery-test:{uuid4().hex}",
            idempotency_key=f"delivery-test:{uuid4().hex}",
        ),
    )
    return task.id


async def _claim_action_for_subject(
    scheduler: PostgresScheduledActionWorker,
    *,
    subject_id: UUID,
) -> ScheduledActionLease:
    leases = await scheduler.claim(limit=500)
    return next(lease for lease in leases if lease.subject_id == subject_id)


def _force_action_due(
    conn: PgConnection,
    *,
    organization_id: UUID,
    action_type: str,
    subject_id: UUID,
) -> None:
    conn.execute(
        """
        UPDATE request_engine.scheduled_actions
        SET execute_at = clock_timestamp() - interval '1 second',
            next_attempt_at = clock_timestamp() - interval '1 second'
        WHERE organization_id = %s
          AND action_type = %s
          AND subject_id = %s
          AND status = 'pending'
        """,
        (organization_id, action_type, subject_id),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_delivery_provider_io_runs_after_authoritative_transaction_commit(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    task_id = await _create_due_task(fixture, session_factory)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    lease = await _claim_action_for_subject(scheduler, subject_id=task_id)

    def assert_task_is_not_locked(communication_task_id: UUID) -> None:
        row = admin_conn.execute(
            """
            SELECT id
            FROM request_engine.communication_tasks
            WHERE organization_id = %s AND id = %s
            FOR UPDATE NOWAIT
            """,
            (fixture.organization_id, communication_task_id),
        ).fetchone()
        assert row == (communication_task_id,)

    provider = FakeProvider(
        send_results=[
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.DELIVERED,
                provider_message_id="message-1",
            )
        ],
        lock_probe=assert_task_is_not_locked,
    )
    worker = CommunicationDeliveryWorker(
        worker_session_factory,
        scheduler,
        {"fake": provider},
    )

    outcome = await worker.process(lease)
    assert outcome.detail == "delivered"
    assert len(provider.send_requests) == 1
    assert len(provider.lookup_requests) == 0

    task_row = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.communication_tasks
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, task_id),
    ).fetchone()
    assert task_row == (CommunicationTaskStatus.COMPLETED.value,)

    delivery_row = admin_conn.execute(
        """
        SELECT status, provider_message_id, attempt_no
        FROM request_engine.communication_deliveries
        WHERE organization_id = %s AND communication_task_id = %s
        """,
        (fixture.organization_id, task_id),
    ).fetchone()
    assert delivery_row == ("delivered", "message-1", 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_ambiguous_send_reconciles_without_blind_resend(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    task_id = await _create_due_task(fixture, session_factory)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    dispatch_lease = await _claim_action_for_subject(scheduler, subject_id=task_id)
    provider = FakeProvider(
        send_results=[TimeoutError("provider timeout after request write")],
        lookup_results=[
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.DELIVERED,
                provider_message_id="message-after-timeout",
            )
        ],
    )
    worker = CommunicationDeliveryWorker(
        worker_session_factory,
        scheduler,
        {"fake": provider},
    )

    first = await worker.process(dispatch_lease)
    assert first.detail == "ambiguous"
    assert first.delivery_id is not None
    assert len(provider.send_requests) == 1

    _force_action_due(
        admin_conn,
        organization_id=fixture.organization_id,
        action_type="reconcile_delivery",
        subject_id=first.delivery_id,
    )
    reconcile_lease = await _claim_action_for_subject(
        scheduler,
        subject_id=first.delivery_id,
    )
    reconciled = await worker.process(reconcile_lease)

    assert reconciled.detail == "delivered"
    assert len(provider.send_requests) == 1
    assert len(provider.lookup_requests) == 1
    assert provider.lookup_requests[0].provider_idempotency_key == (
        provider.send_requests[0].provider_idempotency_key
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_repeated_accepted_reconciliation_schedules_one_future_followup(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    task_id = await _create_due_task(fixture, session_factory)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    provider = FakeProvider(
        send_results=[
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.ACCEPTED,
                provider_message_id="accepted-1",
            )
        ],
        lookup_results=[
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.ACCEPTED,
                provider_message_id="accepted-1",
            ),
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.DELIVERED,
                provider_message_id="accepted-1",
            ),
        ],
    )
    worker = CommunicationDeliveryWorker(
        worker_session_factory,
        scheduler,
        {"fake": provider},
    )

    dispatch_lease = await _claim_action_for_subject(scheduler, subject_id=task_id)
    accepted = await worker.process(dispatch_lease)
    assert accepted.detail == "accepted"
    assert accepted.delivery_id is not None

    _force_action_due(
        admin_conn,
        organization_id=fixture.organization_id,
        action_type="reconcile_delivery",
        subject_id=accepted.delivery_id,
    )
    first_reconcile = await _claim_action_for_subject(
        scheduler,
        subject_id=accepted.delivery_id,
    )
    still_accepted = await worker.process(first_reconcile)
    assert still_accepted.detail == "accepted"

    future_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'reconcile_delivery'
          AND subject_id = %s
          AND status = 'pending'
        """,
        (fixture.organization_id, accepted.delivery_id),
    ).fetchone()
    assert future_count == (1,)

    _force_action_due(
        admin_conn,
        organization_id=fixture.organization_id,
        action_type="reconcile_delivery",
        subject_id=accepted.delivery_id,
    )
    second_reconcile = await _claim_action_for_subject(
        scheduler,
        subject_id=accepted.delivery_id,
    )
    delivered = await worker.process(second_reconcile)
    assert delivered.detail == "delivered"
    assert len(provider.send_requests) == 1
    assert len(provider.lookup_requests) == 2


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_retryable_failure_keeps_backoff_work_separate_from_old_action(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    task_id = await _create_due_task(fixture, session_factory, retry_after_seconds=300)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    provider = FakeProvider(
        send_results=[
            ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=True,
                result_data={"error": "provider_503"},
            )
        ],
    )
    worker = CommunicationDeliveryWorker(
        worker_session_factory,
        scheduler,
        {"fake": provider},
    )

    original_lease = await _claim_action_for_subject(scheduler, subject_id=task_id)
    failed = await worker.process(original_lease)
    assert failed.detail == "failed"
    assert len(provider.send_requests) == 1

    retry_row = admin_conn.execute(
        """
        SELECT id, execute_at > clock_timestamp()
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND action_type = 'dispatch_task'
          AND subject_id = %s
          AND status = 'pending'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (fixture.organization_id, task_id),
    ).fetchone()
    assert retry_row is not None
    assert retry_row[1] is True

    # Defensive replay of the old lease object must observe the durable future retry
    # and must not invoke the provider a second time before that backoff is due.
    replay_outcome = await worker.process(original_lease)
    assert replay_outcome.detail == "retry_already_scheduled"
    assert len(provider.send_requests) == 1
