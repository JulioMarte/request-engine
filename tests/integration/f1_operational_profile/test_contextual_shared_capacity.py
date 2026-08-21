from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.platform.db.session import SessionFactory

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _shared_root(conn: PgConnection) -> UUID:
    global_identity = conn.execute(
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("f1-test.control-plane", "shared contextual professional"),
    ).fetchone()
    assert global_identity is not None
    root = conn.execute(
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (
            cast(UUID, global_identity[0]),
            "f1-test.control-plane",
            "serialize contextual professional capacity",
        ),
    ).fetchone()
    assert root is not None
    return cast(UUID, root[0])


def _bind(conn: PgConnection, scenario: F1ContextualScenario, root_id: UUID) -> None:
    row = conn.execute(
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            scenario.organization_id,
            scenario.resource_id,
            root_id,
            "f1-test.control-plane",
            "verified contextual Resource binding",
        ),
    ).fetchone()
    assert row is not None


def _query(scenario: F1ContextualScenario) -> FindAppointmentSlotsQuery:
    return FindAppointmentSlotsQuery(
        organization_id=scenario.organization_id,
        offering_version_id=scenario.offering_version_id,
        location_id=scenario.location_id,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
        limit=10,
    )


def _command(scenario: F1ContextualScenario, slot: AppointmentSlot) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        offering_version_id=scenario.offering_version_id,
        subject_party_id=scenario.subject_party_id,
        location_id=scenario.location_id,
        start_at=slot.start_at,
        resources=slot.resources,
        idempotency_key=f"contextual-shared-{uuid4().hex}",
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
async def test_contextual_booking_respects_cross_tenant_shared_capacity(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a = create_contextual_cardiology_scenario(admin_conn, key_suffix=f"a-{uuid4().hex}")
    tenant_b = create_contextual_cardiology_scenario(admin_conn, key_suffix=f"b-{uuid4().hex}")
    root_id = _shared_root(admin_conn)
    _bind(admin_conn, tenant_a, root_id)
    _bind(admin_conn, tenant_b, root_id)

    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = CapacitySafeReservationCommands(session_factory)

    slot_a = (await find_appointment_slots(availability, _query(tenant_a)))[0]
    slot_b = (await find_appointment_slots(availability, _query(tenant_b)))[0]
    assert slot_a.start_at == slot_b.start_at

    reservation = await book_appointment(commands, _command(tenant_a, slot_a))

    linked = admin_conn.execute(
        """
        SELECT link.shared_capacity_identity_id, c.resource_location_assignment_id
        FROM request_engine.capacity_claims c
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = c.id
        WHERE c.organization_id = %s
          AND c.reservation_id = %s
          AND c.status = 'active'
        """,
        (tenant_a.organization_id, reservation.id),
    ).fetchone()
    assert linked == (root_id, tenant_a.assignment_id)

    with pytest.raises(AppointmentUnavailable):
        await book_appointment(commands, _command(tenant_b, slot_b))

    foreign_reservations = admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
        (tenant_b.organization_id,),
    ).fetchone()
    assert foreign_reservations == (0,)
