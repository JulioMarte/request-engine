from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import UUID

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


@dataclass(frozen=True, slots=True)
class F5ContextualSupply:
    assignment_id: UUID
    context_terms_id: UUID


def contextualize_recovery_supply(
    conn: PgConnection,
    sandbox: TenantSandbox,
) -> F5ContextualSupply:
    weekday_row = conn.execute(
        "SELECT extract(isodow FROM clock_timestamp() "
        "AT TIME ZONE 'America/Santo_Domingo')::int - 1"
    ).fetchone()
    assert weekday_row is not None
    weekday = cast(int, weekday_row[0])
    conn.execute(
        "INSERT INTO request_engine.location_operational_hours "
        "(organization_id,location_id,weekday,local_start,local_end) "
        "VALUES (%s,%s,%s,'00:00','23:59')",
        (sandbox.organization_id, sandbox.location_id, weekday),
    )
    assignment = conn.execute(
        "INSERT INTO request_engine.resource_location_assignments "
        "(organization_id,resource_id,location_id,effective_during) "
        "VALUES (%s,%s,%s,tstzrange('2026-01-01T00:00:00Z',NULL,'[)')) RETURNING id",
        (sandbox.organization_id, sandbox.resource_id, sandbox.location_id),
    ).fetchone()
    assert assignment is not None
    assignment_id = cast(UUID, assignment[0])
    conn.execute(
        "INSERT INTO request_engine.resource_location_availability "
        "(organization_id,resource_location_assignment_id,weekday,local_start,local_end) "
        "VALUES (%s,%s,%s,'00:00','23:59')",
        (sandbox.organization_id, assignment_id, weekday),
    )
    terms = conn.execute(
        "INSERT INTO request_engine.booking_context_terms "
        "(organization_id,resource_location_assignment_id,offering_version_id,effective_during,"
        "amount,currency,planned_duration_minutes) "
        "VALUES (%s,%s,%s,tstzrange('2026-01-01T00:00:00Z',NULL,'[)'),%s,'DOP',5) RETURNING id",
        (sandbox.organization_id, assignment_id, sandbox.offering_version_id, Decimal("4000")),
    ).fetchone()
    assert terms is not None
    return F5ContextualSupply(assignment_id, cast(UUID, terms[0]))
