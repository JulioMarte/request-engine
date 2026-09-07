from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
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
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker

from .booking_boundary_fixture import (
    contextual_booking_command,
    create_booking_boundary_fixture,
)

PgConnection = Connection[Any]
PgRow = tuple[object, ...]
BookingState = tuple[PgRow, tuple[PgRow, ...], tuple[PgRow, ...]]


class BoundaryProvider:
    def __init__(self) -> None:
        self.send_requests: list[ProviderSendRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_requests.append(request)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"boundary-{uuid4().hex}",
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        raise AssertionError(f"unexpected provider lookup: {request.delivery_id}")


def _contact_point(
    conn: PgConnection,
    *,
    organization_id: UUID,
    party_id: UUID,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, 'whatsapp', %s, true)
        RETURNING id
        """,
        (organization_id, party_id, f"+1809{uuid4().hex[:7]}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _booking_state(
    conn: PgConnection,
    *,
    organization_id: UUID,
    reservation_id: UUID,
) -> BookingState:
    reservation = conn.execute(
        """
        SELECT status, revision, offering_version_id, subject_party_id,
               location_id, during::text, origin_request_id
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, reservation_id),
    ).fetchone()
    assert reservation is not None
    claims = conn.execute(
        """
        SELECT resource_id, requirement_id, during::text, quantity, status,
               hold_id, reservation_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s AND reservation_id = %s
        ORDER BY id
        """,
        (organization_id, reservation_id),
    ).fetchall()
    attendance = conn.execute(
        """
        SELECT response, source_key, responded_at
        FROM request_engine.attendance_responses
        WHERE organization_id = %s AND reservation_id = %s
        ORDER BY responded_at, id
        """,
        (organization_id, reservation_id),
    ).fetchall()
    return (
        tuple(reservation),
        tuple(tuple(row) for row in claims),
        tuple(tuple(row) for row in attendance),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i47_provider_delivery_status_cannot_mutate_source_reservation_graph(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    fixture = create_booking_boundary_fixture(admin_conn)
    reservation = await book_appointment(
        CapacitySafeReservationCommands(session_factory),
        await contextual_booking_command(
            fixture,
            session_factory,
            start_at=datetime(2026, 8, 24, 13, 0, tzinfo=UTC),
            key_prefix="i47-book",
        ),
    )
    contact_point_id = _contact_point(
        admin_conn,
        organization_id=fixture.organization_id,
        party_id=fixture.subject_party_id,
    )
    task = await create_communication_task(
        PostgresCommunicationCommands(session_factory),
        CreateCommunicationTaskCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            recipient_party_id=fixture.subject_party_id,
            contact_point_id=contact_point_id,
            purpose="appointment_confirmation",
            source_kind="Reservation",
            source_id=reservation.id,
            template_key="appointment-confirmation",
            template_version=1,
            channel_policy={"channels": ["whatsapp"], "provider_key": "boundary"},
            render_context={"reservation_id": str(reservation.id)},
            dedupe_key=f"i47-reservation:{reservation.id}",
            idempotency_key=f"i47-communication-{uuid4().hex}",
        ),
    )

    before = _booking_state(
        admin_conn,
        organization_id=fixture.organization_id,
        reservation_id=reservation.id,
    )

    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    lease = next(item for item in await scheduler.claim(limit=500) if item.subject_id == task.id)
    provider = BoundaryProvider()
    handler = CommunicationDeliveryScheduledHandler(
        session_factory,
        scheduler,
        {"boundary": provider},
    )
    await handler.handle(lease)
    assert await scheduler.complete(lease) is True

    assert len(provider.send_requests) == 1
    assert provider.send_requests[0].communication_task_id == task.id
    after = _booking_state(
        admin_conn,
        organization_id=fixture.organization_id,
        reservation_id=reservation.id,
    )
    assert after == before
