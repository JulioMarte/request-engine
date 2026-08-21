from __future__ import annotations

from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class F1OperationalScenario:
    organization_id: UUID
    party_id: UUID
    location_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    capability_id: UUID
    resource_id: UUID
    assignment_id: UUID
    base_terms_id: UUID


def _uuid(conn: PgConnection, statement: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def seed_bookable_f1_scenario(
    conn: PgConnection,
    label: str,
    *,
    amount: int = 3500,
    currency: str = "DOP",
    duration_minutes: int = 30,
) -> F1OperationalScenario:
    """Seed one isolated, operationally bookable F1 scenario for integration tests."""
    suffix = f"{label}-{uuid4().hex}"
    organization_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.organizations (
            organization_key, display_name, default_timezone, default_currency
        ) VALUES (%s, %s, 'America/Santo_Domingo', %s)
        RETURNING id
        """,
        (suffix, f"Organization {suffix}", currency),
    )
    party_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Test subject {suffix}"),
    )
    location_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"location-{suffix}", f"Clinic {suffix}"),
    )
    offering_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"offering-{suffix}", f"Cardiology consult {suffix}"),
    )
    offering_version_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable
        ) VALUES (%s, %s, 1, %s, true)
        RETURNING id
        """,
        (organization_id, offering_id, duration_minutes),
    )
    capability_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"capability-{suffix}", f"Cardiology {suffix}"),
    )
    requirement_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"resource-{suffix}", f"Doctor {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    assignment_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2030-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        )
        RETURNING id
        """,
        (organization_id, resource_id, location_id),
    )

    for weekday in range(5):
        conn.execute(
            """
            INSERT INTO request_engine.location_operational_hours (
                organization_id, location_id, weekday, local_start, local_end
            ) VALUES (%s, %s, %s, '08:00', '17:00')
            """,
            (organization_id, location_id, weekday),
        )
        conn.execute(
            """
            INSERT INTO request_engine.resource_location_availability (
                organization_id, resource_location_assignment_id,
                weekday, local_start, local_end
            ) VALUES (%s, %s, %s, '09:00', '16:00')
            """,
            (organization_id, assignment_id, weekday),
        )

    base_terms_id = _uuid(
        conn,
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id,
            amount, currency, planned_duration_minutes
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (organization_id, offering_version_id, amount, currency, duration_minutes),
    )

    return F1OperationalScenario(
        organization_id=organization_id,
        party_id=party_id,
        location_id=location_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        capability_id=capability_id,
        resource_id=resource_id,
        assignment_id=assignment_id,
        base_terms_id=base_terms_id,
    )
