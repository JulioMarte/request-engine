from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.application.commands.cancel_request import (
    CancelRequestCommand,
    cancel_request,
)
from request_engine.platform.db.session import SessionFactory

from .contextual_booking_support import (
    contextual_book_command,
    contextual_slot_at,
    create_contextual_tenant,
)

PgConnection = Connection[Any]


def _uuid_row(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> UUID:
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
    fixture = create_contextual_tenant(admin_conn, "origin-request")
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
    slot = await contextual_slot_at(
        fixture,
        session_factory,
        resource_id=fixture.resources[0].resource_id,
        start_at=start_at,
    )
    reservation = await book_appointment(
        CapacitySafeReservationCommands(session_factory),
        contextual_book_command(
            fixture,
            slot,
            origin_request_id=request_id,
            key_prefix="origin-book",
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
