# pyright: reportPrivateUsage=false

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.attendance_commands import PostgresAttendanceCommands
from request_engine.modules.booking.adapters.db.lifecycle_reader import PostgresReservationLifecycleReader
from request_engine.modules.booking.adapters.db.slot_offer_capacity import PostgresSlotOfferCapacity
from request_engine.modules.booking.application.commands.record_attendance import decline_attendance
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.released_slot_recovery import PostgresReleasedSlotRecovery
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.postgres import command_fingerprint

from .test_reservation_lifecycle import _fixture, _future_start

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r08_duplicate_release_consumers_create_one_recovery_chain(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _fixture(
        admin_conn,
        policy={
            "attendance": {"decline_action": "cancel"},
            "slot_recovery": {"enabled": True, "minimum_lead_minutes": 1},
        },
        start_at=_future_start(),
        add_waitlist=True,
    )
    attendance = PostgresAttendanceCommands(app_session_factory)
    await decline_attendance(
        attendance,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=fixture.reservation_id,
        source_key="r08:decline",
        idempotency_key=f"r08-decline-{uuid4().hex}",
        expected_revision=1,
        allow_subject_override=True,
    )

    reader = PostgresReservationLifecycleReader(app_session_factory)
    released = await reader.get_released_slot(
        fixture.organization_id,
        fixture.reservation_id,
        event_type="reservation.cancelled.v1",
    )
    assert released is not None

    recovery = PostgresReleasedSlotRecovery(
        app_session_factory,
        capacity=PostgresSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    source_event_id = uuid4()
    idempotency_key = f"reservation-release:{source_event_id}"
    fingerprint = command_fingerprint(
        "waitlist.create_opportunity",
        {
            "offering_version_id": released.offering_version_id,
            "source_event_id": source_event_id,
            "source_reservation_id": released.reservation_id,
            "location_id": released.location_id,
            "start_at": released.start_at,
            "end_at": released.end_at,
        },
    )
    idempotency_row = admin_conn.execute(
        """
        INSERT INTO request_engine.idempotency_records (
            organization_id, principal_id, capability, idempotency_key, request_fingerprint
        ) VALUES (%s, %s, 'waitlist.create_opportunity', %s, %s)
        RETURNING id
        """,
        (fixture.organization_id, fixture.principal_id, idempotency_key, fingerprint),
    ).fetchone()
    assert idempotency_row is not None
    idempotency_id = idempotency_row[0]

    with admin_conn.transaction():
        locked = admin_conn.execute(
            "SELECT id FROM request_engine.idempotency_records WHERE id = %s FOR UPDATE",
            (idempotency_id,),
        ).fetchone()
        assert locked == (idempotency_id,)

        first_task = asyncio.create_task(
            recovery.recover_released_slot(
                released,
                source_event_id=source_event_id,
                principal_id=fixture.principal_id,
            )
        )
        second_task = asyncio.create_task(
            recovery.recover_released_slot(
                released,
                source_event_id=source_event_id,
                principal_id=fixture.principal_id,
            )
        )
        await asyncio.sleep(0.1)
        assert not first_task.done()
        assert not second_task.done()

    first, second = await asyncio.gather(first_task, second_task)
    assert first is not None and second is not None
    first_opportunity, first_offer = first
    second_opportunity, second_offer = second
    assert first_offer is not None and second_offer is not None
    assert first_opportunity.id == second_opportunity.id
    assert first_offer.id == second_offer.id

    opportunities = admin_conn.execute(
        """
        SELECT id, status
        FROM request_engine.slot_opportunities
        WHERE organization_id = %s AND source_event_id = %s
        """,
        (fixture.organization_id, source_event_id),
    ).fetchall()
    assert opportunities == [(first_opportunity.id, "open")]

    offers = admin_conn.execute(
        """
        SELECT id, capacity_hold_id, status
        FROM request_engine.slot_offers
        WHERE organization_id = %s AND slot_opportunity_id = %s
        """,
        (fixture.organization_id, first_opportunity.id),
    ).fetchall()
    assert len(offers) == 1
    assert offers[0][0] == first_offer.id
    assert offers[0][2] == "offered"
    hold_id = offers[0][1]

    hold_state = admin_conn.execute(
        """
        SELECT status, count(cc.id), count(cc.id) FILTER (WHERE cc.status = 'active')
        FROM request_engine.capacity_holds h
        LEFT JOIN request_engine.capacity_claims cc
          ON cc.organization_id = h.organization_id AND cc.hold_id = h.id
        WHERE h.organization_id = %s AND h.id = %s
        GROUP BY h.status
        """,
        (fixture.organization_id, hold_id),
    ).fetchone()
    assert hold_state == ("active", 1, 1)

    idempotency_state = admin_conn.execute(
        """
        SELECT status, result_data -> 'opportunity' ->> 'id'
        FROM request_engine.idempotency_records
        WHERE id = %s
        """,
        (idempotency_id,),
    ).fetchone()
    assert idempotency_state == ("completed", str(first_opportunity.id))
