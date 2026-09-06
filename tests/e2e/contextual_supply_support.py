from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from . import operational_support as support
from .tenant_sandbox import TenantSandbox


@dataclass(frozen=True, slots=True)
class ContextualSupply:
    assignment_id: UUID
    context_terms_id: UUID


def contextualize_sandbox(
    conn: support.PgConnection,
    sandbox: TenantSandbox,
) -> ContextualSupply:
    """Add contextual commercial terms to an already contextual TenantSandbox.

    TenantSandbox owns the baseline Resource-at-Location assignment and recurring
    availability.  This helper specializes that supply for the contextual booking
    scenarios instead of creating a second, overlapping assignment authority.
    """
    assignment = conn.execute(
        """
        SELECT id
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s
          AND resource_id = %s
          AND location_id = %s
          AND status = 'active'
          AND effective_during @> '2030-01-07T13:00:00+00'::timestamptz
        ORDER BY lower(effective_during) DESC
        LIMIT 1
        """,
        (sandbox.organization_id, sandbox.resource_id, sandbox.location_id),
    ).fetchone()
    assert assignment is not None, "TenantSandbox must provide contextual Resource supply"
    assignment_id = assignment[0]

    conn.execute(
        """
        DELETE FROM request_engine.location_operational_hours
        WHERE organization_id = %s
          AND location_id = %s
          AND weekday = 0
        """,
        (sandbox.organization_id, sandbox.location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (sandbox.organization_id, sandbox.location_id),
    )
    conn.execute(
        """
        DELETE FROM request_engine.resource_location_availability
        WHERE organization_id = %s
          AND resource_location_assignment_id = %s
          AND weekday = 0
        """,
        (sandbox.organization_id, assignment_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (sandbox.organization_id, assignment_id),
    )
    row = conn.execute(
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
        (sandbox.organization_id, assignment_id, sandbox.offering_version_id),
    ).fetchone()
    assert row is not None
    return ContextualSupply(assignment_id=assignment_id, context_terms_id=row[0])
