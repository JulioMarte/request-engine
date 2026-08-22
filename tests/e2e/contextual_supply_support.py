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
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (sandbox.organization_id, sandbox.location_id),
    )
    row = conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        )
        RETURNING id
        """,
        (sandbox.organization_id, sandbox.resource_id, sandbox.location_id),
    ).fetchone()
    assert row is not None
    assignment_id = row[0]
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
