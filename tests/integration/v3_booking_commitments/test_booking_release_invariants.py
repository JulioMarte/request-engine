from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.commitment_commands import (
    PostgresBookingCommitmentCommands,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    PostgresReservationCommands,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
    acquire_capacity_hold,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.application.commands.cancel_request import (
    CancelRequestCommand,
    cancel_request,
)
from request_engine.platform.db.session import SessionFactory

from .test_booking_commitments import _choice, _create_fixture

PgConnection = Connection[Any]


def _uuid_row(conn: PgConnection, sql: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i14_request_cancellation_does_not_cancel_origin_reservation(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    request_definition_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name
        ) VALUES (%s, %s, 'Booking origin request')
        RETURNING id
        """,
        (fixture.organization_id, f"origin-{uuid4().hex}"),
    )
    request_version_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version, input_schema
        ) VALUES (%s, %s, 1, '{}'::jsonb)
        RETURNING id
        """,
        (fixture.organization_id, request_definition_id),
    )
    request_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.requests (
            organization_id, request_definition_version_id,
            requester_party_id, payload
        ) VALUES (%s, %s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (
            fixture.organization_id,
            request_version_id,
            fixture.subject_party_id,
        ),
    )

    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    reservation = await book_appointment(
        PostgresReservationCommands(session_factory),
        BookAppointmentCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_version_id=fixture.offering_version_id,
            subject_party_id=fixture.subject_party_id,
            location_id=fixture.location_id,
            origin_request_id=request_id,
            start_at=start_at,
            resources=_choice(fixture),
            idempotency_key=f"i14-book-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )

    cancelled_request = await cancel_request(
        PostgresRequestCommands(session_factory),
        CancelRequestCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            request_id=request_id,
            reason="request no longer needed",
            expected_revision=1,
            idempotency_key=f"i14-cancel-{uuid4().hex}",
            allow_party_override=True,
        ),
    )
    assert cancelled_request.status.value == "cancelled"

    assert admin_conn.execute(
        """
        SELECT status, origin_request_id, revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone() == ("confirmed", request_id, reservation.revision)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i19_failed_multi_requirement_hold_leaves_no_partial_capacity(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    second_capability_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Second mandatory capability')
        RETURNING id
        """,
        (fixture.organization_id, f"second-cap-{uuid4().hex}"),
    )
    second_requirement_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 2, 1)
        RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id, second_capability_id),
    )
    second_resource_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'Unavailable second resource', 'exclusive', 1)
        RETURNING id
        """,
        (fixture.organization_id, fixture.location_id, f"second-resource-{uuid4().hex}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (fixture.organization_id, second_resource_id, second_capability_id),
    )

    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    with pytest.raises(AppointmentUnavailable):
        await acquire_capacity_hold(
            PostgresBookingCommitmentCommands(session_factory),
            AcquireCapacityHoldCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                offering_version_id=fixture.offering_version_id,
                subject_party_id=fixture.subject_party_id,
                location_id=fixture.location_id,
                start_at=start_at,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                resources=(
                    ResourceChoice(fixture.requirement_id, fixture.resource_id),
                    ResourceChoice(second_requirement_id, second_resource_id),
                ),
                idempotency_key=f"i19-hold-{uuid4().hex}",
                allow_subject_override=True,
            ),
        )

    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_holds
        WHERE organization_id = %s
          AND subject_party_id = %s
          AND during = tstzrange(%s, %s, '[)')
        """,
        (
            fixture.organization_id,
            fixture.subject_party_id,
            start_at,
            start_at + timedelta(minutes=30),
        ),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND resource_id IN (%s, %s)
          AND during && tstzrange(%s, %s, '[)')
        """,
        (
            fixture.organization_id,
            fixture.resource_id,
            second_resource_id,
            start_at,
            start_at + timedelta(minutes=30),
        ),
    ).fetchone() == (0,)
