from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection, Error

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    cancel_reservation,
)
from request_engine.platform.db.session import SessionFactory

from .booking_revalidation_fixture import contextual_book_command, create_fixture

PgConnection = Connection[Any]


@pytest.mark.integration
@pytest.mark.postgres
def test_i15_authoritative_capacity_intervals_must_be_half_open(
    admin_conn: PgConnection,
) -> None:
    fixture = create_fixture(admin_conn)

    with pytest.raises(Error) as invalid_hold, admin_conn.transaction():
        admin_conn.execute(
            """
            INSERT INTO request_engine.capacity_holds (
                organization_id, offering_version_id, subject_party_id, location_id,
                during, expires_at
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2026-08-17 13:00+00', '2026-08-17 13:30+00', '(]'),
                clock_timestamp() + interval '5 minutes'
            )
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.subject_party_id,
                fixture.location_id,
            ),
        )
    assert invalid_hold.value.sqlstate == "23514"

    with pytest.raises(Error) as invalid_reservation, admin_conn.transaction():
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, location_id, during
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2026-08-17 13:00+00', '2026-08-17 13:30+00', '[]')
            )
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.subject_party_id,
                fixture.location_id,
            ),
        )
    assert invalid_reservation.value.sqlstate == "23514"


@pytest.mark.integration
@pytest.mark.postgres
def test_i16_capacity_claim_must_match_its_authoritative_owner(
    admin_conn: PgConnection,
) -> None:
    fixture = create_fixture(admin_conn)

    with pytest.raises(Error) as mismatched_interval, admin_conn.transaction():
        reservation_id = admin_conn.execute(
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, location_id, during
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2026-08-17 13:00+00', '2026-08-17 13:30+00', '[)')
            )
            RETURNING id
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.subject_party_id,
                fixture.location_id,
            ),
        ).fetchone()
        assert reservation_id is not None
        admin_conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, reservation_id,
                during, quantity
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2026-08-17 13:15+00', '2026-08-17 13:45+00', '[)'), 1
            )
            """,
            (
                fixture.organization_id,
                fixture.resource_id,
                fixture.requirement_id,
                reservation_id[0],
            ),
        )
    assert mismatched_interval.value.sqlstate == "23514"


@pytest.mark.integration
@pytest.mark.postgres
def test_i21_confirmed_reservation_cannot_commit_with_incomplete_claim_set(
    admin_conn: PgConnection,
) -> None:
    fixture = create_fixture(admin_conn)

    with pytest.raises(Error) as incomplete, admin_conn.transaction():
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id, location_id, during
            ) VALUES (
                %s, %s, %s, %s,
                tstzrange('2026-08-17 13:00+00', '2026-08-17 13:30+00', '[)')
            )
            """,
            (
                fixture.organization_id,
                fixture.offering_version_id,
                fixture.subject_party_id,
                fixture.location_id,
            ),
        )
    assert incomplete.value.sqlstate == "23514"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i23_i28_cancel_releases_capacity_atomically_and_db_rejects_terminal_consumption(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_fixture(admin_conn)
    commands = CapacitySafeReservationCommands(session_factory)
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)

    reservation = await book_appointment(
        commands,
        await contextual_book_command(fixture, session_factory, start_at=start_at),
    )
    cancelled = await cancel_reservation(
        commands,
        CancelReservationCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=reservation.id,
            idempotency_key=f"i23-cancel-{uuid4().hex}",
            expected_revision=reservation.revision,
            reason="release invariant proof",
            allow_subject_override=True,
        ),
    )
    assert cancelled.status.value == "cancelled"
    assert admin_conn.execute(
        """
        SELECT status, count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s AND reservation_id = %s
        GROUP BY status
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall() == [("released", 1)]

    second_start = datetime(2026, 8, 17, 13, 30, tzinfo=UTC)
    second = await book_appointment(
        commands,
        await contextual_book_command(fixture, session_factory, start_at=second_start),
    )
    with pytest.raises(Error) as terminal_with_live_claim, admin_conn.transaction():
        admin_conn.execute(
            """
            UPDATE request_engine.reservations
            SET status = 'cancelled', cancelled_at = clock_timestamp(), revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, second.id),
        )
    assert terminal_with_live_claim.value.sqlstate == "23514"

    assert admin_conn.execute(
        """
        SELECT r.status, c.status
        FROM request_engine.reservations r
        JOIN request_engine.capacity_claims c
          ON c.organization_id = r.organization_id
         AND c.reservation_id = r.id
        WHERE r.organization_id = %s AND r.id = %s
        """,
        (fixture.organization_id, second.id),
    ).fetchone() == ("confirmed", "active")
