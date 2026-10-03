"""Real PostgreSQL intent, lease and cancellation proofs; only SMTP is doubled."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_staff_membership_lifecycle import provision_staff_root

from request_engine.modules.communications.adapters.db.staff_invitation_delivery import (
    PostgresStaffInvitationDeliveryRecorder,
)
from request_engine.modules.communications.adapters.worker.staff_invitation_delivery import (
    StaffInvitationDeliveryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker
from request_engine.platform.scheduling.store import cancel_action
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryRetryable,
    StagedRecoverySecret,
)
from request_engine.platform.worker.runtime import LeaseLostWorkError, RetryableWorkError

pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.adversarial]


class InvitationTransport:
    def __init__(
        self,
        outcome: DeliveryOutcome = DeliveryOutcome.DELIVERED,
        hook: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.outcome = outcome
        self.hook = hook
        self.sent: list[str] = []
        self.looked_up: list[str] = []
        self.lookup_outcome: DeliveryOutcome | None = None
        self.nontransmission = False

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        raise AssertionError("worker must not stage or regenerate invitation proofs")

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        raise AssertionError("worker must not discard owner invitation proofs")

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        assert reference == "governed-invitation-reference"
        assert destination_reference == "new-staff@example.test"
        self.sent.append(idempotency_key)
        if self.hook:
            await self.hook()
        if self.nontransmission:
            raise RecoveryDeliveryRetryable("connection refused before message transmission")
        return self.outcome

    async def reconcile(self, *, reference: str, idempotency_key: str) -> DeliveryOutcome | None:
        self.looked_up.append(idempotency_key)
        return self.lookup_outcome


def invitation_prerequisite(conn: Connection[Any]) -> tuple[UUID, UUID, datetime]:
    org, _party, principal, _binding, _provisioner = provision_staff_root(conn)
    invitation = uuid4()
    expiry = datetime.now(UTC) + timedelta(hours=1)
    conn.execute(
        "SELECT set_config('request_engine.organization_id',%s,false), "
        "set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(org), str(principal)),
    )
    # Valid authoritative input for the Communications boundary, not the delivery result.
    conn.execute(
        """INSERT INTO request_engine.staff_invitations (
            id, organization_id, email, invited_by_principal_id,
            provenance_reference, token_digest, expires_at
        ) VALUES (%s,%s,'new-staff@example.test',%s,'delivery-test',%s,%s)""",
        (invitation, org, principal, "a" * 64, expiry),
    )
    return org, invitation, expiry


async def record_delivery(
    factory: SessionFactory, org: UUID, invitation: UUID, expiry: datetime
) -> UUID:
    async with tenant_transaction(factory, org) as session:
        return await PostgresStaffInvitationDeliveryRecorder().record(
            session,
            organization_id=org,
            invitation_id=invitation,
            generation=1,
            destination_address="new-staff@example.test",
            secret_reference="governed-invitation-reference",
            secret_digest="a" * 64,
            expires_at=expiry,
        )


def delivery_state(conn: Connection[Any], delivery: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status,attempt_no FROM request_engine.staff_invitation_deliveries WHERE id=%s",
        (delivery,),
    ).fetchone()
    assert row is not None
    return row


@pytest.mark.asyncio
async def test_intent_replay_conflict_and_transaction_rollback(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, invitation, expiry = invitation_prerequisite(admin_conn)
    delivery = await record_delivery(command_session_factory, org, invitation, expiry)
    assert await record_delivery(command_session_factory, org, invitation, expiry) == delivery
    async with tenant_transaction(command_session_factory, org) as session:
        recorder = PostgresStaffInvitationDeliveryRecorder()
        assert (
            await recorder.status(
                session,
                organization_id=org,
                invitation_id=invitation,
                generation=1,
            )
            == "pending"
        )
        assert (
            await recorder.status(
                session,
                organization_id=org,
                invitation_id=invitation,
                generation=2,
            )
            is None
        )
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.scheduled_actions WHERE subject_id=%s",
        (delivery,),
    ).fetchone() == (1,)
    with pytest.raises(ValueError, match="conflicts"):
        async with tenant_transaction(command_session_factory, org) as session:
            await PostgresStaffInvitationDeliveryRecorder().record(
                session,
                organization_id=org,
                invitation_id=invitation,
                generation=1,
                destination_address="different@example.test",
                secret_reference="different",
                secret_digest="b" * 64,
                expires_at=expiry,
            )
    with pytest.raises(RuntimeError, match="rollback"):
        async with tenant_transaction(command_session_factory, org) as session:
            await PostgresStaffInvitationDeliveryRecorder().record(
                session,
                organization_id=org,
                invitation_id=invitation,
                generation=2,
                destination_address="new-staff@example.test",
                secret_reference="second",
                secret_digest="b" * 64,
                expires_at=expiry,
            )
            raise RuntimeError("rollback owner command")
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_invitation_deliveries WHERE invitation_id=%s",
        (invitation,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.scheduled_actions WHERE owner_module='communications'",
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_batch_status_exact_pairs_missing_foreign_and_old_generation(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, first, expiry = invitation_prerequisite(admin_conn)
    second = uuid4()
    admin_conn.execute(
        """INSERT INTO request_engine.staff_invitations (
            id, organization_id, email, invited_by_principal_id,
            provenance_reference, token_digest, expires_at
        ) SELECT %s, organization_id, 'second@example.test', invited_by_principal_id,
            'batch-query-input', %s, expires_at
        FROM request_engine.staff_invitations WHERE id=%s""",
        (second, "b" * 64, first),
    )
    recorder = PostgresStaffInvitationDeliveryRecorder()
    await record_delivery(command_session_factory, org, first, expiry)
    async with tenant_transaction(command_session_factory, org) as session:
        await recorder.record(
            session,
            organization_id=org,
            invitation_id=second,
            generation=1,
            destination_address="second@example.test",
            secret_reference="second-invitation",
            secret_digest="b" * 64,
            expires_at=expiry,
        )
    async with tenant_transaction(command_session_factory, org) as session:
        await recorder.cancel(session, organization_id=org, invitation_id=first)
        await recorder.record(
            session,
            organization_id=org,
            invitation_id=first,
            generation=2,
            destination_address="new-staff@example.test",
            secret_reference="next-generation",
            secret_digest="c" * 64,
            expires_at=expiry,
        )
    foreign_org, foreign, foreign_expiry = invitation_prerequisite(admin_conn)
    await record_delivery(command_session_factory, foreign_org, foreign, foreign_expiry)
    pairs = ((first, 2), (second, 1), (second, 1), (second, 2), (foreign, 1), (uuid4(), 1))
    async with tenant_transaction(command_session_factory, org) as session:
        assert await recorder.statuses(session, organization_id=org, generations=pairs) == {
            (first, 2): "pending",
            (second, 1): "pending",
        }
        # Asking the supported adapter for another organization never bypasses RLS.
        assert (
            await recorder.statuses(
                session, organization_id=foreign_org, generations=((foreign, 1),)
            )
            == {}
        )
        assert await recorder.statuses(session, organization_id=org, generations=((first, 1),)) == {
            (first, 1): "cancelled",
        }


@pytest.mark.asyncio
async def test_unknown_reconciles_without_resending(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org, invitation, expiry = invitation_prerequisite(admin_conn)
    delivery = await record_delivery(command_session_factory, org, invitation, expiry)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    lease = (await scheduler.claim(limit=1))[0]
    transport = InvitationTransport(DeliveryOutcome.UNKNOWN)
    handler = StaffInvitationDeliveryScheduledHandler(command_session_factory, scheduler, transport)
    with pytest.raises(RetryableWorkError):
        await handler.handle(lease)
    assert delivery_state(admin_conn, delivery) == ("unknown", 1)
    with pytest.raises(RetryableWorkError):
        await handler.handle(lease)
    assert len(transport.sent) == 1
    assert transport.looked_up == transport.sent
    assert delivery_state(admin_conn, delivery) == ("unknown", 1)
    transport.lookup_outcome = DeliveryOutcome.DELIVERED
    await handler.handle(lease)
    assert len(transport.sent) == 1
    assert delivery_state(admin_conn, delivery) == ("delivered", 1)


@pytest.mark.asyncio
async def test_definite_nontransmission_can_retry(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org, invitation, expiry = invitation_prerequisite(admin_conn)
    delivery = await record_delivery(command_session_factory, org, invitation, expiry)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    lease = (await scheduler.claim(limit=1))[0]
    transport = InvitationTransport()
    transport.nontransmission = True
    handler = StaffInvitationDeliveryScheduledHandler(command_session_factory, scheduler, transport)
    with pytest.raises(RetryableWorkError):
        await handler.handle(lease)
    assert delivery_state(admin_conn, delivery) == ("pending", 1)
    transport.nontransmission = False
    await handler.handle(lease)
    assert delivery_state(admin_conn, delivery) == ("delivered", 2)
    assert transport.sent[0] == transport.sent[1]
    assert not transport.looked_up


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during_send", [False, True])
async def test_cancellation_prevents_send_or_preserves_cancelled_finalization(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
    cancel_during_send: bool,
) -> None:
    org, invitation, expiry = invitation_prerequisite(admin_conn)
    delivery = await record_delivery(command_session_factory, org, invitation, expiry)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    lease = (await scheduler.claim(limit=1))[0]

    async def cancel() -> None:
        if cancel_during_send:
            # Independent committed read observes attempting before provider I/O.
            assert delivery_state(admin_conn, delivery) == ("attempting", 1)
        async with tenant_transaction(command_session_factory, org) as session:
            await PostgresStaffInvitationDeliveryRecorder().cancel(
                session,
                organization_id=org,
                invitation_id=invitation,
            )

    if not cancel_during_send:
        await cancel()
    transport = InvitationTransport(hook=cancel if cancel_during_send else None)
    handler = StaffInvitationDeliveryScheduledHandler(command_session_factory, scheduler, transport)
    await asyncio.wait_for(handler.handle(lease), timeout=5)
    assert delivery_state(admin_conn, delivery) == ("cancelled", int(cancel_during_send))
    assert len(transport.sent) == int(cancel_during_send)


@pytest.mark.asyncio
async def test_lost_claim_cannot_finalize_provider_result(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org, invitation, expiry = invitation_prerequisite(admin_conn)
    delivery = await record_delivery(command_session_factory, org, invitation, expiry)
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    lease = (await scheduler.claim(limit=1))[0]

    async def steal_claim() -> None:
        async with tenant_transaction(command_session_factory, org) as session:
            await cancel_action(session, organization_id=org, action_id=lease.id)

    transport = InvitationTransport(hook=steal_claim)
    handler = StaffInvitationDeliveryScheduledHandler(command_session_factory, scheduler, transport)
    with pytest.raises(LeaseLostWorkError):
        await handler.handle(lease)
    assert delivery_state(admin_conn, delivery) == ("attempting", 1)
    assert len(transport.sent) == 1


@pytest.mark.asyncio
@pytest.mark.security
async def test_foreign_tenant_cannot_read_cancel_or_record_delivery(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, invitation, expiry = invitation_prerequisite(admin_conn)
    delivery = await record_delivery(command_session_factory, org, invitation, expiry)
    foreign, *_ = provision_staff_root(admin_conn)
    recorder = PostgresStaffInvitationDeliveryRecorder()
    async with tenant_transaction(command_session_factory, foreign) as session:
        assert (
            await recorder.status(
                session,
                organization_id=org,
                invitation_id=invitation,
                generation=1,
            )
            is None
        )
        assert (
            await session.execute(
                text(
                    "SELECT secret_reference FROM request_engine.staff_invitation_deliveries "
                    "WHERE id=:id"
                ),
                {"id": delivery},
            )
        ).all() == []
        await recorder.cancel(session, organization_id=org, invitation_id=invitation)
    assert delivery_state(admin_conn, delivery) == ("pending", 0)
    with pytest.raises(DBAPIError) as rejected:
        async with tenant_transaction(command_session_factory, foreign) as session:
            await recorder.record(
                session,
                organization_id=foreign,
                invitation_id=invitation,
                generation=2,
                destination_address="new-staff@example.test",
                secret_reference="foreign",
                secret_digest="b" * 64,
                expires_at=expiry,
            )
    assert getattr(rejected.value.orig, "sqlstate", None) == "23503"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_invitation_deliveries",
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.scheduled_actions WHERE owner_module='communications'",
    ).fetchone() == (1,)
