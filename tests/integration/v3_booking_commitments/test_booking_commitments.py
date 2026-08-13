import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
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
from request_engine.modules.booking.application.commands.confirm_capacity_hold import (
    ConfirmCapacityHoldCommand,
    confirm_capacity_hold,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
    reschedule_reservation,
)
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    CapacityHoldExpired,
)
from request_engine.modules.booking.contracts.appointments import (
    ReservationStatus,
    ResourceChoice,
)
from request_engine.modules.booking.contracts.holds import CapacityHoldStatus
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class BookingFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    location_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_party(conn: PgConnection, organization_id: UUID, name: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, name),
    )


def _create_fixture(conn: PgConnection) -> BookingFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"commitments-{suffix}", f"Commitment Practice {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_party_id = _create_party(conn, organization_id, f"Patient {suffix}")
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main office', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Medical consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id,
            offering_id,
            version,
            duration_minutes,
            bookable,
            booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 15})),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'General physician')
        RETURNING id
        """,
        (organization_id, f"physician-{suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id,
            location_id,
            resource_key,
            display_name,
            capacity_model,
            capacity_units
        ) VALUES (%s, %s, %s, 'Dr. Resource', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"doctor-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone
        ) VALUES (%s, %s, 0, '09:00', '12:00', 'America/Santo_Domingo')
        """,
        (organization_id, resource_id),
    )
    return BookingFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _choice(fixture: BookingFixture) -> tuple[ResourceChoice, ...]:
    return (ResourceChoice(fixture.requirement_id, fixture.resource_id),)


def _book_command(
    fixture: BookingFixture,
    *,
    subject_party_id: UUID,
    start_at: datetime,
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=subject_party_id,
        location_id=fixture.location_id,
        start_at=start_at,
        resources=_choice(fixture),
        idempotency_key=f"book-{uuid4().hex}",
        allow_subject_override=True,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_hold_blocks_competitor_and_confirmation_promotes_same_claims(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    commitments = PostgresBookingCommitmentCommands(session_factory)
    reservations = PostgresReservationCommands(session_factory)
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)

    hold_command = AcquireCapacityHoldCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        location_id=fixture.location_id,
        start_at=start_at,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        resources=_choice(fixture),
        idempotency_key=f"hold-{uuid4().hex}",
    )
    hold = await acquire_capacity_hold(commitments, hold_command)
    replay = await acquire_capacity_hold(commitments, hold_command)
    assert replay == hold
    assert hold.status is CapacityHoldStatus.ACTIVE

    original_claims = admin_conn.execute(
        """
        SELECT id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND hold_id = %s
          AND reservation_id IS NULL
          AND status = 'active'
        ORDER BY id
        """,
        (fixture.organization_id, hold.id),
    ).fetchall()
    original_claim_ids = [cast(UUID, row[0]) for row in original_claims]
    assert len(original_claim_ids) == 1

    competitor = _create_party(admin_conn, fixture.organization_id, "Competing patient")
    with pytest.raises(AppointmentUnavailable):
        await book_appointment(
            reservations,
            _book_command(fixture, subject_party_id=competitor, start_at=start_at),
        )

    confirm_command = ConfirmCapacityHoldCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        hold_id=hold.id,
        idempotency_key=f"confirm-{uuid4().hex}",
    )
    reservation = await confirm_capacity_hold(commitments, confirm_command)
    confirm_replay = await confirm_capacity_hold(commitments, confirm_command)
    assert confirm_replay == reservation
    assert reservation.status is ReservationStatus.CONFIRMED

    promoted = admin_conn.execute(
        """
        SELECT id, hold_id, reservation_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        ORDER BY id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert [cast(UUID, row[0]) for row in promoted] == original_claim_ids
    assert all(row[1] == hold.id for row in promoted)
    assert all(row[2] == reservation.id for row in promoted)

    hold_status = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.capacity_holds
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, hold.id),
    ).fetchone()
    assert hold_status == ("consumed",)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_expired_hold_is_rejected_using_database_wall_clock(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    hold_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.capacity_holds (
            organization_id,
            offering_version_id,
            subject_party_id,
            location_id,
            during,
            created_at,
            expires_at
        ) VALUES (
            %s, %s, %s, %s,
            tstzrange('2026-08-17 13:00+00', '2026-08-17 13:30+00', '[)'),
            clock_timestamp() - interval '2 minutes',
            clock_timestamp() - interval '1 minute'
        )
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.offering_version_id,
            fixture.subject_party_id,
            fixture.location_id,
        ),
    )

    with pytest.raises(CapacityHoldExpired):
        await confirm_capacity_hold(
            PostgresBookingCommitmentCommands(session_factory),
            ConfirmCapacityHoldCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                hold_id=hold_id,
                idempotency_key=f"confirm-expired-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_self_overlap_reschedule_replaces_claim_without_self_conflict(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    reservations = PostgresReservationCommands(session_factory)
    commitments = PostgresBookingCommitmentCommands(session_factory)
    original_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    new_start = datetime(2026, 8, 17, 13, 15, tzinfo=UTC)

    reservation = await book_appointment(
        reservations,
        _book_command(
            fixture,
            subject_party_id=fixture.subject_party_id,
            start_at=original_start,
        ),
    )
    old_claim = admin_conn.execute(
        """
        SELECT id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert old_claim is not None
    old_claim_id = cast(UUID, old_claim[0])

    moved = await reschedule_reservation(
        commitments,
        RescheduleReservationCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=reservation.id,
            expected_revision=reservation.revision,
            location_id=fixture.location_id,
            start_at=new_start,
            resources=_choice(fixture),
            idempotency_key=f"reschedule-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    assert moved.id == reservation.id
    assert moved.start_at == new_start
    assert moved.end_at == datetime(2026, 8, 17, 13, 45, tzinfo=UTC)
    assert moved.revision == reservation.revision + 1

    claim_rows = admin_conn.execute(
        """
        SELECT id, status, replaced_by_claim_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
        ORDER BY created_at, id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert len(claim_rows) == 2
    old_row = next(row for row in claim_rows if row[0] == old_claim_id)
    new_row = next(row for row in claim_rows if row[0] != old_claim_id)
    assert old_row[1] == "replaced"
    assert old_row[2] == new_row[0]
    assert new_row[1] == "active"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_failed_reschedule_rolls_back_original_reservation_and_claim(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    reservations = PostgresReservationCommands(session_factory)
    commitments = PostgresBookingCommitmentCommands(session_factory)
    first_subject = fixture.subject_party_id
    second_subject = _create_party(admin_conn, fixture.organization_id, "Second patient")
    first_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    blocked_start = datetime(2026, 8, 17, 13, 30, tzinfo=UTC)

    first = await book_appointment(
        reservations,
        _book_command(fixture, subject_party_id=first_subject, start_at=first_start),
    )
    await book_appointment(
        reservations,
        _book_command(fixture, subject_party_id=second_subject, start_at=blocked_start),
    )

    with pytest.raises(AppointmentUnavailable):
        await reschedule_reservation(
            commitments,
            RescheduleReservationCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                reservation_id=first.id,
                expected_revision=first.revision,
                location_id=fixture.location_id,
                start_at=blocked_start,
                resources=_choice(fixture),
                idempotency_key=f"reschedule-fail-{uuid4().hex}",
                allow_subject_override=True,
            ),
        )

    stored = admin_conn.execute(
        """
        SELECT lower(during), upper(during), revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, first.id),
    ).fetchone()
    assert stored == (
        first_start,
        datetime(2026, 8, 17, 13, 30, tzinfo=UTC),
        first.revision,
    )
    active_claims = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, first.id),
    ).fetchone()
    assert active_claims == (1,)
