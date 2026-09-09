from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from psycopg import Connection

from request_engine.entrypoints.worker.outbox_runtime import (
    OutboxEvent,
    ReservationLifecycleOutboxHandler,
)
from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.commitment_commands import (
    PostgresBookingCommitmentCommands,
)
from request_engine.modules.booking.adapters.db.lifecycle_reader import (
    PostgresReservationLifecycleReader,
)
from request_engine.modules.booking.adapters.db.lifecycle_scheduling import (
    PostgresReservationLifecycleScheduling,
)
from request_engine.modules.booking.adapters.db.slot_offer_capacity import (
    PostgresSlotOfferCapacity,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
    reschedule_reservation,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.communications.adapters.db.reservation_lifecycle_intent import (
    PostgresReservationLifecycleNotificationIntent,
)
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.released_slot_recovery import (
    PostgresReleasedSlotRecovery,
)
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _handler(
    session_factory: SessionFactory,
    *,
    worker_principal_id: UUID,
) -> ReservationLifecycleOutboxHandler:
    return ReservationLifecycleOutboxHandler(
        worker_principal_id=worker_principal_id,
        reader=PostgresReservationLifecycleReader(session_factory),
        scheduling=PostgresReservationLifecycleScheduling(session_factory),
        notifications=PostgresReservationLifecycleNotificationIntent(session_factory),
        recovery=PostgresReleasedSlotRecovery(
            session_factory,
            capacity=PostgresSlotOfferCapacity(),
            notification=PostgresSlotOfferNotificationIntent(),
        ),
    )


def _outbox_event(row: tuple[object, ...], organization_id: UUID) -> OutboxEvent:
    return OutboxEvent(
        id=cast(UUID, row[0]),
        organization_id=organization_id,
        event_type="reservation.rescheduled.v1",
        schema_version=cast(int, row[1]),
        aggregate_kind=cast(str, row[2]),
        aggregate_id=cast(UUID, row[3]),
        payload=cast(dict[str, object], row[4]),
    )


def _future_start() -> datetime:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    aligned = now + timedelta(minutes=(-now.minute) % 15)
    return aligned + timedelta(days=3)


def _location(
    conn: PgConnection,
    *,
    organization_id: UUID,
    label: str,
    weekday: int,
) -> UUID:
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"{label}-{uuid4().hex}", label),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, %s, '00:00', '23:59')
        """,
        (organization_id, location_id, weekday),
    )
    return location_id


def _resource_at(
    conn: PgConnection,
    *,
    organization_id: UUID,
    capability_id: UUID,
    location_id: UUID,
    label: str,
    weekday: int,
) -> tuple[UUID, UUID]:
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"{label}-{uuid4().hex}", label),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    assignment_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        )
        RETURNING id
        """,
        (organization_id, resource_id, location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, %s, '00:00', '23:59')
        """,
        (organization_id, assignment_id, weekday),
    )
    return resource_id, assignment_id


async def _slot_at(
    session_factory: SessionFactory,
    *,
    organization_id: UUID,
    offering_version_id: UUID,
    location_id: UUID,
    resource_id: UUID,
    start_at: datetime,
) -> AppointmentSlot:
    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        FindAppointmentSlotsQuery(
            organization_id=organization_id,
            offering_version_id=offering_version_id,
            location_id=location_id,
            resource_id=resource_id,
            window_start=start_at,
            window_end=start_at + timedelta(hours=1),
            limit=20,
        ),
    )
    slot = next((candidate for candidate in slots if candidate.start_at == start_at), None)
    if slot is None:
        raise AssertionError("expected contextual reschedule option was not available")
    return slot


def _reschedule_command(
    *,
    organization_id: UUID,
    principal_id: UUID,
    reservation_id: UUID,
    expected_revision: int,
    location_id: UUID,
    slot: AppointmentSlot,
    key_prefix: str,
) -> RescheduleReservationCommand:
    assert slot.planned_duration_minutes is not None
    assert slot.amount is not None
    assert slot.currency is not None
    assert slot.location_operational_revision is not None
    assert slot.configuration_fingerprint is not None
    return RescheduleReservationCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        reservation_id=reservation_id,
        expected_revision=expected_revision,
        location_id=location_id,
        start_at=slot.start_at,
        resources=slot.resources,
        idempotency_key=f"{key_prefix}-{uuid4().hex}",
        allow_subject_override=True,
        expected_planned_duration_minutes=slot.planned_duration_minutes,
        expected_amount=slot.amount,
        expected_currency=slot.currency,
        expected_location_operational_revision=slot.location_operational_revision,
        expected_configuration_fingerprint=slot.configuration_fingerprint,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_delayed_reschedule_events_recover_their_own_historical_slots(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    start_a = _future_start()
    start_b = start_a + timedelta(days=7)
    start_c = start_b + timedelta(days=7)
    weekday = start_a.astimezone(ZoneInfo("America/Santo_Domingo")).weekday()
    suffix = uuid4().hex

    organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"release-provenance-{suffix}", f"Release provenance {suffix}"),
    )
    principal_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    location_a = _location(
        admin_conn,
        organization_id=organization_id,
        label="Location A",
        weekday=weekday,
    )
    location_b = _location(
        admin_conn,
        organization_id=organization_id,
        label="Location B",
        weekday=weekday,
    )
    location_c = _location(
        admin_conn,
        organization_id=organization_id,
        label="Location C",
        weekday=weekday,
    )

    offering_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    policy = '{"slot_step_minutes":15,"slot_recovery":{"enabled":true,"minimum_lead_minutes":1}}'
    offering_version_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, policy),
    )
    terms_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP')
        RETURNING id
        """,
        (organization_id, offering_version_id),
    )
    capability_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Doctor')
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
    )
    requirement_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_a, assignment_a = _resource_at(
        admin_conn,
        organization_id=organization_id,
        capability_id=capability_id,
        location_id=location_a,
        label="Doctor A",
        weekday=weekday,
    )
    resource_b, _ = _resource_at(
        admin_conn,
        organization_id=organization_id,
        capability_id=capability_id,
        location_id=location_b,
        label="Doctor B",
        weekday=weekday,
    )
    resource_c, _ = _resource_at(
        admin_conn,
        organization_id=organization_id,
        capability_id=capability_id,
        location_id=location_c,
        label="Doctor C",
        weekday=weekday,
    )

    end_a = start_a + timedelta(minutes=30)
    with admin_conn.transaction():
        reservation_id = _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.reservations (
                organization_id, offering_version_id, subject_party_id,
                location_id, during, booking_policy_snapshot
            ) VALUES (%s, %s, %s, %s, tstzrange(%s, %s, '[)'), %s::jsonb)
            RETURNING id
            """,
            (
                organization_id,
                offering_version_id,
                subject_id,
                location_a,
                start_a,
                end_a,
                policy,
            ),
        )
        admin_conn.execute(
            """
            INSERT INTO request_engine.capacity_claims (
                organization_id, resource_id, requirement_id, reservation_id,
                resource_location_assignment_id, during, quantity
            ) VALUES (%s, %s, %s, %s, %s, tstzrange(%s, %s, '[)'), 1)
            """,
            (
                organization_id,
                resource_a,
                requirement_id,
                reservation_id,
                assignment_a,
                start_a,
                end_a,
            ),
        )
        admin_conn.execute(
            """
            INSERT INTO request_engine.reservation_commercial_commitments (
                reservation_id, organization_id, offering_version_booking_terms_id,
                amount, currency, planned_duration_minutes, configuration_fingerprint
            ) VALUES (%s, %s, %s, 3500, 'DOP', 30, %s)
            """,
            (reservation_id, organization_id, terms_id, "fixture:release-provenance"),
        )

    slot_b = await _slot_at(
        session_factory,
        organization_id=organization_id,
        offering_version_id=offering_version_id,
        location_id=location_b,
        resource_id=resource_b,
        start_at=start_b,
    )
    slot_c = await _slot_at(
        session_factory,
        organization_id=organization_id,
        offering_version_id=offering_version_id,
        location_id=location_c,
        resource_id=resource_c,
        start_at=start_c,
    )

    commands = PostgresBookingCommitmentCommands(session_factory)
    first = await reschedule_reservation(
        commands,
        _reschedule_command(
            organization_id=organization_id,
            principal_id=principal_id,
            reservation_id=reservation_id,
            expected_revision=1,
            location_id=location_b,
            slot=slot_b,
            key_prefix="reschedule-a-b",
        ),
    )
    assert first.revision == 2
    second = await reschedule_reservation(
        commands,
        _reschedule_command(
            organization_id=organization_id,
            principal_id=principal_id,
            reservation_id=reservation_id,
            expected_revision=2,
            location_id=location_c,
            slot=slot_c,
            key_prefix="reschedule-b-c",
        ),
    )
    assert second.revision == 3

    rows = admin_conn.execute(
        """
        SELECT id, schema_version, aggregate_kind, aggregate_id, payload
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'reservation.rescheduled.v1'
          AND aggregate_id = %s
        ORDER BY created_at, id
        """,
        (organization_id, reservation_id),
    ).fetchall()
    assert len(rows) == 2
    event_ab = _outbox_event(tuple(rows[0]), organization_id)
    event_bc = _outbox_event(tuple(rows[1]), organization_id)

    assert event_ab.payload["old_location_id"] == str(location_a)
    assert event_ab.payload["old_start_at"] == start_a.isoformat()
    assert event_ab.payload["start_at"] == start_b.isoformat()
    assert event_bc.payload["old_location_id"] == str(location_b)
    assert event_bc.payload["old_start_at"] == start_b.isoformat()
    assert event_bc.payload["start_at"] == start_c.isoformat()

    handler = _handler(session_factory, worker_principal_id=principal_id)
    await handler.handle(event_ab, uuid4())
    await handler.handle(event_bc, uuid4())

    recovered = admin_conn.execute(
        """
        SELECT source_event_id, location_id,
               lower(during) AS start_at, upper(during) AS end_at
        FROM request_engine.slot_opportunities
        WHERE organization_id = %s
          AND source_event_id = ANY(%s::uuid[])
        ORDER BY source_event_id
        """,
        (organization_id, [str(event_ab.id), str(event_bc.id)]),
    ).fetchall()
    by_event = {cast(UUID, row[0]): row for row in recovered}
    assert set(by_event) == {event_ab.id, event_bc.id}

    recovered_a = by_event[event_ab.id]
    assert recovered_a[1] == location_a
    assert recovered_a[2] == start_a
    assert recovered_a[3] == end_a

    recovered_b = by_event[event_bc.id]
    assert recovered_b[1] == location_b
    assert recovered_b[2] == start_b
    assert recovered_b[3] == start_b + timedelta(minutes=30)

    current = admin_conn.execute(
        """
        SELECT location_id, lower(during), revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, reservation_id),
    ).fetchone()
    assert current == (location_c, start_c, 3)
