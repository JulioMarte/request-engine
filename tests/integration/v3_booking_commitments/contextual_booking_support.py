from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class ContextualResourceFixture:
    resource_id: UUID
    assignment_id: UUID
    assignment_revision: int
    availability_revision: int


@dataclass(frozen=True, slots=True)
class ContextualTenantFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    location_id: UUID
    requirement_id: UUID
    capability_id: UUID
    resources: tuple[ContextualResourceFixture, ...]


def uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_contextual_tenant(
    conn: PgConnection,
    label: str,
    *,
    resource_count: int = 1,
) -> ContextualTenantFixture:
    if resource_count < 1:
        raise ValueError("resource_count must be positive")

    suffix = f"{label}-{uuid4().hex}"
    organization_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (suffix, suffix),
    )
    principal_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_party_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    location_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}", f"Main {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (organization_id, location_id),
    )
    offering_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}", f"Consult {suffix}"),
    )
    offering_version_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 15})),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP')
        """,
        (organization_id, offering_version_id),
    )
    capability_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}", f"Doctor {suffix}"),
    )
    requirement_id = uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )

    resources: list[ContextualResourceFixture] = []
    for ordinal in range(1, resource_count + 1):
        resource_id = uuid_row(
            conn,
            """
            INSERT INTO request_engine.resources (
                organization_id, resource_key, display_name,
                capacity_model, capacity_units
            ) VALUES (%s, %s, %s, 'exclusive', 1)
            RETURNING id
            """,
            (
                organization_id,
                f"doctor-{ordinal}-{suffix}",
                f"Doctor {ordinal} {suffix}",
            ),
        )
        conn.execute(
            """
            INSERT INTO request_engine.resource_capability_assignments (
                organization_id, resource_id, capability_id
            ) VALUES (%s, %s, %s)
            """,
            (organization_id, resource_id, capability_id),
        )
        assignment_id = uuid_row(
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
            ) VALUES (%s, %s, 0, '09:00', '12:00')
            """,
            (organization_id, assignment_id),
        )
        provenance = conn.execute(
            """
            SELECT a.revision, r.availability_revision
            FROM request_engine.resource_location_assignments a
            JOIN request_engine.resources r
              ON r.organization_id = a.organization_id
             AND r.id = a.resource_id
            WHERE a.organization_id = %s AND a.id = %s
            """,
            (organization_id, assignment_id),
        ).fetchone()
        assert provenance is not None
        resources.append(
            ContextualResourceFixture(
                resource_id=resource_id,
                assignment_id=assignment_id,
                assignment_revision=cast(int, provenance[0]),
                availability_revision=cast(int, provenance[1]),
            )
        )

    return ContextualTenantFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        location_id=location_id,
        requirement_id=requirement_id,
        capability_id=capability_id,
        resources=tuple(resources),
    )


async def contextual_slot_at(
    fixture: ContextualTenantFixture,
    session_factory: SessionFactory,
    *,
    resource_id: UUID,
    start_at: datetime,
) -> AppointmentSlot:
    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        FindAppointmentSlotsQuery(
            organization_id=fixture.organization_id,
            offering_version_id=fixture.offering_version_id,
            location_id=fixture.location_id,
            resource_id=resource_id,
            window_start=start_at,
            window_end=start_at + timedelta(hours=1),
            limit=20,
        ),
    )
    slot = next((candidate for candidate in slots if candidate.start_at == start_at), None)
    if slot is None:
        raise AssertionError("expected contextual appointment option was not available")
    return slot


def contextual_book_command(
    fixture: ContextualTenantFixture,
    slot: AppointmentSlot,
    *,
    subject_party_id: UUID | None = None,
    origin_request_id: UUID | None = None,
    key_prefix: str = "book",
) -> BookAppointmentCommand:
    assert slot.planned_duration_minutes is not None
    assert slot.amount is not None
    assert slot.currency is not None
    assert slot.location_operational_revision is not None
    assert slot.configuration_fingerprint is not None
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=subject_party_id or fixture.subject_party_id,
        location_id=fixture.location_id,
        origin_request_id=origin_request_id,
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


def contextual_reschedule_command(
    fixture: ContextualTenantFixture,
    slot: AppointmentSlot,
    *,
    reservation_id: UUID,
    expected_revision: int,
    key_prefix: str = "reschedule",
) -> RescheduleReservationCommand:
    assert slot.planned_duration_minutes is not None
    assert slot.amount is not None
    assert slot.currency is not None
    assert slot.location_operational_revision is not None
    assert slot.configuration_fingerprint is not None
    return RescheduleReservationCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=reservation_id,
        expected_revision=expected_revision,
        location_id=fixture.location_id,
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
