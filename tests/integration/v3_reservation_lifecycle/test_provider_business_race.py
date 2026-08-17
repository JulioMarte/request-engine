# pyright: reportPrivateUsage=false

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.worker.provider_event_router import ProviderEventRouter
from request_engine.modules.booking.adapters.db.attendance_commands import PostgresAttendanceCommands
from request_engine.modules.booking.adapters.db.reservation_commands import PostgresReservationCommands
from request_engine.modules.booking.application.attendance_errors import AttendanceReservationNotActive
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    cancel_reservation,
)
from request_engine.modules.booking.application.commands.record_attendance import confirm_attendance
from request_engine.modules.booking.application.errors import ReservationRevisionConflict
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.events.provider_events import ProviderEventLease

from .test_reservation_lifecycle import _fixture, _future_start

PgConnection = Connection[object]


def _provider_lease(organization_id: UUID, reservation_id: UUID) -> ProviderEventLease:
    now = datetime.now(UTC)
    return ProviderEventLease(
        id=uuid4(),
        organization_id=organization_id,
        claim_token=uuid4(),
        provider_key="attendance-provider",
        connection_key="primary",
        provider_event_id=f"attendance-{uuid4().hex}",
        payload_hash=uuid4().hex,
        payload={
            "reservation_id": str(reservation_id),
            "response": "accepted",
        },
        attempt_count=1,
        lease_until=now + timedelta(minutes=1),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r18_provider_semantic_callback_vs_business_cancellation_serializes_on_reservation(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={},
        start_at=_future_start(),
    )
    attendance = PostgresAttendanceCommands(session_factory)
    reservations = PostgresReservationCommands(session_factory)
    lease = _provider_lease(fixture.organization_id, fixture.reservation_id)

    async def provider_handler(event: ProviderEventLease) -> object:
        assert event.organization_id == fixture.organization_id
        reservation_id = UUID(cast(str, event.payload["reservation_id"]))
        return await confirm_attendance(
            attendance,
            organization_id=event.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=reservation_id,
            source_key=f"provider:{event.provider_key}:{event.provider_event_id}",
            idempotency_key=f"provider-attendance:{event.provider_event_id}",
            expected_revision=1,
            allow_subject_override=True,
        )

    router = ProviderEventRouter({("attendance-provider", "primary"): provider_handler})
    cancel_command = CancelReservationCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        expected_revision=1,
        reason="R18 concurrent business cancellation",
        idempotency_key=f"r18-cancel-{uuid4().hex}",
        allow_subject_override=True,
    )

    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
            FROM request_engine.reservations
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (fixture.organization_id, fixture.reservation_id),
        ).fetchone()
        provider_task = asyncio.create_task(router.process(lease))
        cancel_task = asyncio.create_task(cancel_reservation(reservations, cancel_command))
        await asyncio.sleep(0.1)
        assert not provider_task.done()
        assert not cancel_task.done()

    provider_result, cancel_result = await asyncio.gather(
        provider_task,
        cancel_task,
        return_exceptions=True,
    )

    provider_succeeded = not isinstance(provider_result, BaseException)
    cancel_succeeded = isinstance(cancel_result, Reservation)
    assert provider_succeeded + cancel_succeeded == 1

    reservation = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    active_claim_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    attendance_rows = admin_conn.execute(
        """
        SELECT response, source_key
        FROM request_engine.attendance_responses
        WHERE organization_id = %s AND reservation_id = %s
        ORDER BY responded_at, id
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()

    if provider_succeeded:
        assert isinstance(cancel_result, ReservationRevisionConflict)
        assert reservation == ("confirmed", 2)
        assert active_claim_count == (1,)
        assert len(attendance_rows) == 1
        assert attendance_rows[0][0] == "accepted"
        assert cast(str, attendance_rows[0][1]).startswith("provider:attendance-provider:")
    else:
        assert isinstance(provider_result, AttendanceReservationNotActive)
        assert cancel_succeeded
        assert reservation == ("cancelled", 2)
        assert active_claim_count == (0,)
        assert attendance_rows == []
