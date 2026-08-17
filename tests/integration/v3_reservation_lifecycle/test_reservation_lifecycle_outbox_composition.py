from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.worker.outbox_runtime import (
    OutboxEvent,
    ReservationLifecycleOutboxHandler,
)
from request_engine.modules.booking.adapters.db.attendance_commands import (
    PostgresAttendanceCommands,
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
from request_engine.modules.booking.application.commands.record_attendance import (
    decline_attendance,
)
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


def _event(
    *,
    event_id: UUID,
    organization_id: UUID,
    reservation_id: UUID,
    event_type: str,
    schema_version: int = 1,
    payload: dict[str, object] | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        id=event_id,
        organization_id=organization_id,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_kind="Reservation",
        aggregate_id=reservation_id,
        payload=payload or {"reservation_id": str(reservation_id)},
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reservation_outbox_composes_lifecycle_then_slot_recovery_exactly_once(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = support._fixture(
        admin_conn,
        policy={
            "attendance": {
                "confirmation_required": True,
                "attendance_request_before_minutes": 1440,
                "no_show_after_minutes": 15,
                "decline_action": "cancel",
            },
            "communications": {
                "confirmation": True,
                "reminders_before_minutes": [2880, 120],
                "channel_policy": {
                    "channels": ["whatsapp"],
                    "provider_key": "test-provider",
                },
            },
            "slot_recovery": {"enabled": True, "minimum_lead_minutes": 1},
        },
        start_at=support._future_start(),
        add_waitlist=True,
    )
    handler = _handler(session_factory, worker_principal_id=fixture.principal_id)

    created_event_id = uuid4()
    await handler.handle(
        _event(
            event_id=created_event_id,
            organization_id=fixture.organization_id,
            reservation_id=fixture.reservation_id,
            event_type="reservation.created.v1",
        ),
        uuid4(),
    )

    reservation_tasks = admin_conn.execute(
        """
        SELECT purpose, status
        FROM request_engine.communication_tasks
        WHERE organization_id = %s
          AND source_kind = 'Reservation'
          AND source_id = %s
        ORDER BY purpose, dedupe_key
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    assert len(reservation_tasks) == 4
    assert {row[0] for row in reservation_tasks} == {
        "appointment_confirmation",
        "appointment_reminder",
        "attendance_confirmation_request",
    }
    assert all(row[1] == "pending" for row in reservation_tasks)

    pending_before_cancel = admin_conn.execute(
        """
        SELECT owner_module, subject_kind, count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND status = 'pending'
          AND (
              (owner_module = 'booking' AND subject_kind = 'Reservation' AND subject_id = %s)
              OR owner_module = 'communications'
          )
        GROUP BY owner_module, subject_kind
        ORDER BY owner_module, subject_kind
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchall()
    assert pending_before_cancel == [
        ("booking", "Reservation", 1),
        ("communications", "CommunicationTask", 4),
    ]

    commands = PostgresAttendanceCommands(session_factory)
    await decline_attendance(
        commands,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        source_key="test:outbox-composition",
        idempotency_key=f"decline-{uuid4().hex}",
        expected_revision=1,
        allow_subject_override=True,
    )

    cancellation_row = admin_conn.execute(
        """
        SELECT id, schema_version, aggregate_kind, aggregate_id, payload
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'reservation.cancelled.v1'
          AND aggregate_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert cancellation_row is not None
    cancellation_event_id = cast(UUID, cancellation_row[0])
    cancellation = OutboxEvent(
        id=cancellation_event_id,
        organization_id=fixture.organization_id,
        event_type="reservation.cancelled.v1",
        schema_version=cast(int, cancellation_row[1]),
        aggregate_kind=cast(str, cancellation_row[2]),
        aggregate_id=cast(UUID, cancellation_row[3]),
        payload=cast(dict[str, object], cancellation_row[4]),
    )

    await handler.handle(cancellation, uuid4())
    await handler.handle(cancellation, uuid4())

    cancelled_reservation_tasks = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.communication_tasks
        WHERE organization_id = %s
          AND source_kind = 'Reservation'
          AND source_id = %s
          AND status = 'cancelled'
        """,
        (fixture.organization_id, fixture.reservation_id),
    ).fetchone()
    assert cancelled_reservation_tasks == (4,)

    pending_reservation_actions = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND status = 'pending'
          AND (
              (owner_module = 'booking' AND subject_kind = 'Reservation' AND subject_id = %s)
              OR (
                  owner_module = 'communications'
                  AND subject_id IN (
                      SELECT id
                      FROM request_engine.communication_tasks
                      WHERE organization_id = %s
                        AND source_kind = 'Reservation'
                        AND source_id = %s
                  )
              )
          )
        """,
        (
            fixture.organization_id,
            fixture.reservation_id,
            fixture.organization_id,
            fixture.reservation_id,
        ),
    ).fetchone()
    assert pending_reservation_actions == (0,)

    recovered = admin_conn.execute(
        """
        SELECT o.id, o.status, so.id, so.status, h.status, ct.status, sa.status
        FROM request_engine.slot_opportunities o
        JOIN request_engine.slot_offers so
          ON so.organization_id = o.organization_id
         AND so.slot_opportunity_id = o.id
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id
         AND h.id = so.capacity_hold_id
        JOIN request_engine.communication_tasks ct
          ON ct.organization_id = so.organization_id
         AND ct.source_kind = 'SlotOffer'
         AND ct.source_id = so.id
        JOIN request_engine.scheduled_actions sa
          ON sa.organization_id = so.organization_id
         AND sa.subject_kind = 'SlotOffer'
         AND sa.subject_id = so.id
        WHERE o.organization_id = %s
          AND o.source_event_id = %s
        """,
        (fixture.organization_id, cancellation_event_id),
    ).fetchall()
    assert len(recovered) == 1
    assert recovered[0][1:] == (
        "open",
        recovered[0][2],
        "offered",
        "active",
        "pending",
        "pending",
    )

    recovery_counts = admin_conn.execute(
        """
        SELECT
            (SELECT count(*)
             FROM request_engine.slot_opportunities
             WHERE organization_id = %s AND source_event_id = %s),
            (SELECT count(*)
             FROM request_engine.slot_offers so
             JOIN request_engine.slot_opportunities o
               ON o.organization_id = so.organization_id
              AND o.id = so.slot_opportunity_id
             WHERE o.organization_id = %s AND o.source_event_id = %s)
        """,
        (
            fixture.organization_id,
            cancellation_event_id,
            fixture.organization_id,
            cancellation_event_id,
        ),
    ).fetchone()
    assert recovery_counts == (1, 1)
