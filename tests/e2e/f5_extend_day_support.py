from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


def source_revision(proposal: dict[str, Any]) -> int:
    checkpoint = cast(dict[str, Any], proposal["source_checkpoint"])
    return cast(int, checkpoint["recovery_source_revision"])


def owner_revisions(conn: PgConnection, sandbox: TenantSandbox) -> tuple[int, int]:
    row = conn.execute(
        "SELECT l.operational_revision,r.availability_revision "
        "FROM request_engine.locations l "
        "JOIN request_engine.resources r ON r.organization_id=l.organization_id "
        "WHERE l.organization_id=%s AND l.id=%s AND r.id=%s",
        (sandbox.organization_id, sandbox.location_id, sandbox.resource_id),
    ).fetchone()
    assert row is not None
    return cast(tuple[int, int], tuple(row))


def extend_action(
    conn: PgConnection,
    sandbox: TenantSandbox,
    incident_id: UUID,
) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT id,status,owner_steps FROM request_engine.operational_recovery_actions "
        "WHERE organization_id=%s AND incident_id=%s AND action_kind='extend_day'",
        (sandbox.organization_id, incident_id),
    ).fetchone()
    assert row is not None
    return tuple(row)


def location_recovery_exception_count(conn: PgConnection, sandbox: TenantSandbox) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.location_hours_exceptions "
        "WHERE organization_id=%s AND location_id=%s AND active",
        (sandbox.organization_id, sandbox.location_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def assignment_recovery_exception_count(
    conn: PgConnection, sandbox: TenantSandbox, assignment_id: object
) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.resource_location_schedule_exceptions "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s AND active",
        (sandbox.organization_id, assignment_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
