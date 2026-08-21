from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
)

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class F1ContextualScenario:
    """Reusable realistic F1 test world; never loaded by production code."""

    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    subject_party_id: UUID
    location_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID
    assignment_id: UUID
    context_terms_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_contextual_cardiology_scenario(
    conn: PgConnection,
    *,
    key_suffix: str | None = None,
) -> F1ContextualScenario:
    """Seed one complete F1 cardiology world for PostgreSQL integration tests.

    The scenario contains tenant identity/authority, one Dominican clinic,
    cardiology service terms, one qualified doctor, one effective assignment,
    Monday operational/Resource availability, and one contextual price/duration
    override. Tests mutate individual facts to prove stale-option, scheduling,
    authorization, shared-capacity, and concurrency behavior.
    """

    suffix = key_suffix or uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (
            organization_key, display_name, default_currency, default_timezone
        ) VALUES (%s, %s, 'DOP', 'America/Santo_Domingo')
        RETURNING id
        """,
        (f"f1-{suffix}", f"F1 Practice {suffix}"),
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
    authority_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'organization', %s)
        RETURNING id
        """,
        (organization_id, f"Operations {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            scope_key,
            authority_kind
        ) VALUES
            (%s, %s, %s, %s, 'delegated'),
            (%s, %s, %s, %s, 'delegated'),
            (%s, %s, %s, %s, 'delegated')
        """,
        (
            organization_id,
            principal_id,
            authority_party_id,
            MANAGE_OPERATIONAL_PROFILE_SCOPE,
            organization_id,
            principal_id,
            authority_party_id,
            MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            organization_id,
            principal_id,
            authority_party_id,
            MANAGE_COMMERCIAL_TERMS_SCOPE,
        ),
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
        ) VALUES (%s, %s, 'Main clinic', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"clinic-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (organization_id, location_id),
    )

    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Cardiology consultation')
        RETURNING id
        """,
        (organization_id, f"cardiology-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 30})),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP')
        """,
        (organization_id, offering_version_id),
    )

    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Cardiologist')
        RETURNING id
        """,
        (organization_id, f"cardiologist-{suffix}"),
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
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'Dr Context', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
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
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (organization_id, assignment_id),
    )
    context_terms_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id, resource_location_assignment_id,
            offering_version_id, effective_during,
            amount, currency, planned_duration_minutes
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)'),
            4000, 'DOP', 45
        )
        RETURNING id
        """,
        (organization_id, assignment_id, offering_version_id),
    )

    return F1ContextualScenario(
        organization_id=organization_id,
        principal_id=principal_id,
        authority_party_id=authority_party_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
        assignment_id=assignment_id,
        context_terms_id=context_terms_id,
    )
