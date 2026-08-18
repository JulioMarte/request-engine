from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class BookingBoundaryFixture:
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


def create_booking_boundary_fixture(conn: PgConnection) -> BookingBoundaryFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"i47-{suffix}", f"I47 {suffix}"),
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
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Patient {suffix}"),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'I47 office', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"i47-office-{suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'I47 consultation')
        RETURNING id
        """,
        (organization_id, f"i47-consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, '{"slot_step_minutes":15}'::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'I47 physician')
        RETURNING id
        """,
        (organization_id, f"i47-physician-{suffix}"),
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
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'I47 doctor', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"i47-doctor-{suffix}"),
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
    return BookingBoundaryFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )
