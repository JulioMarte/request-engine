from datetime import timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.worker.outbox_runtime import (
    OutboxEvent,
    ReservationLifecycleOutboxHandler,
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
from request_engine.modules.booking.contracts.appointments import ResourceChoice
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

from . import test_reservation_lifecycle as lifecycle_support

PgConnection = Connection[Any]
support = cast(Any, lifecycle_support)


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


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_delayed_reschedule_events_recover_their_own_historical_slots(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    start_a = support._future_start()
    fixture = support._fixture(
        admin_conn,
        policy={"slot_recovery": {"enabled": True, "minimum_lead_minutes": 1}},
        start_at=start_a,
        add_waitlist=True,
    )

    # Make the resource location-agnostic so the Reservation can move across
    # locations while retaining one stable capacity requirement.
    admin_conn.execute(
        """
        UPDATE request_engine.resources
        SET location_id = NULL
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.resource_id),
    )
    location_b = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Location B', 'America/Santo_Domingo')
        RETURNING id
        """,
        (fixture.organization_id, f"location-b-{uuid4().hex}"),
    )
    location_c = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Location C', 'America/Santo_Domingo')
        RETURNING id
        """,
        (fixture.organization_id, f"location-c-{uuid4().hex}"),
    )
    requirement_id = _uuid_row(
        admin_conn,
        """
        SELECT id
        FROM request_engine.offering_resource_requirements
        WHERE organization_id = %s AND offering_version_id = %s
        """,
        (fixture.organization_id, fixture.offering_version_id),
    )

    start_b = start_a + timedelta(days=7)
    start_c = start_b + timedelta(days=7)
    commands = PostgresBookingCommitmentCommands(session_factory)
    resource_choice = (
        ResourceChoice(requirement_id=requirement_id, resource_id=fixture.resource_id),
    )
    first = await reschedule_reservation(
        commands,
        RescheduleReservationCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=fixture.reservation_id,
            start_at=start_b,
            resources=resource_choice,
            idempotency_key=f"reschedule-a-b-{uuid4().hex}",
            expected_revision=1,
            location_id=location_b,
            allow_subject_override=True,
        ),
    )
    assert first.revision == 2
    second = await reschedule_reservation(
        commands,
        RescheduleReservationCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=fixture.reservation_id,
            start_at=start_c,
            resources=resource_choice,
            idempotency_key=f"reschedule-b-c-{uuid4().hex}",
            expected_revision=2,
            location_id=location_c,
            allow_subject_override=True,
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
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    assert len(rows) == 2
    event_ab = _outbox_event(rows[0], fixture.organization_id)
    event_bc = _outbox_event(rows[1], fixture.organization_id)

    assert event_ab.payload["old_location_id"] == str(fixture.location_id)
    assert event_ab.payload["old_start_at"] == start_a.isoformat()
    assert event_ab.payload["start_at"] == start_b.isoformat()
    assert event_bc.payload["old_location_id"] == str(location_b)
    assert event_bc.payload["old_start_at"] == start_b.isoformat()
    assert event_bc.payload["start_at"] == start_c.isoformat()

    # Both facts are deliberately processed only after the aggregate has reached C.
    handler = _handler(session_factory, worker_principal_id=fixture.principal_id)
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
        (
            fixture.organization_id,
            [str(event_ab.id), str(event_bc.id)],
        ),
    ).fetchall()
    by_event = {cast(UUID, row[0]): row for row in recovered}
    assert set(by_event) == {event_ab.id, event_bc.id}

    recovered_a = by_event[event_ab.id]
    assert recovered_a[1] == fixture.location_id
    assert recovered_a[2] == start_a
    assert recovered_a[3] == fixture.end_at

    recovered_b = by_event[event_bc.id]
    assert recovered_b[1] == location_b
    assert recovered_b[2] == start_b
    assert recovered_b[3] == start_b + (fixture.end_at - fixture.start_at)

    current = admin_conn.execute(
        """
        SELECT location_id, lower(during), revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert current == (location_c, start_c, 3)
