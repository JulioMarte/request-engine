from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox

_TZ = ZoneInfo("America/Santo_Domingo")


@dataclass(frozen=True, slots=True)
class F5ContextualSupply:
    assignment_id: UUID
    context_terms_id: UUID


def contextualize_recovery_supply(
    conn: PgConnection,
    sandbox: TenantSandbox,
) -> F5ContextualSupply:
    weekday = _current_weekday(conn)
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


def restrict_contextual_capacity(
    conn: PgConnection,
    sandbox: TenantSandbox,
    supply: F5ContextualSupply,
    slots: list[dict[str, Any]],
    *,
    count: int,
) -> None:
    start = datetime.fromisoformat(cast(str, slots[0]["start_at"])).astimezone(_TZ)
    end = datetime.fromisoformat(cast(str, slots[count - 1]["end_at"])).astimezone(_TZ)
    conn.execute(
        "DELETE FROM request_engine.resource_location_availability "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s AND weekday=%s",
        (sandbox.organization_id, supply.assignment_id, start.weekday()),
    )
    conn.execute(
        "INSERT INTO request_engine.resource_location_availability "
        "(organization_id,resource_location_assignment_id,weekday,local_start,local_end) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            sandbox.organization_id,
            supply.assignment_id,
            start.weekday(),
            start.timetz().replace(tzinfo=None),
            end.timetz().replace(tzinfo=None),
        ),
    )


def _current_weekday(conn: PgConnection) -> int:
    row = conn.execute(
        "SELECT extract(isodow FROM clock_timestamp() "
        "AT TIME ZONE 'America/Santo_Domingo')::int - 1"
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
