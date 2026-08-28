from __future__ import annotations

from typing import cast

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox


def escalation_rows(conn: PgConnection, sandbox: TenantSandbox) -> list[tuple[object, ...]]:
    rows = conn.execute(
        """
        SELECT e.source_revision, e.escalation_level, e.operator_escalation_required,
               e.escalation_reason, e.customer_impact_required,
               e.impact_recipient_party_ids
        FROM request_engine.operational_recovery_escalations e
        JOIN request_engine.operational_recovery_incidents i
          ON i.organization_id = e.organization_id AND i.id = e.incident_id
        WHERE e.organization_id=%s AND i.service_queue_id=%s
        ORDER BY e.source_revision, e.id
        """,
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchall()
    return [tuple(row) for row in rows]


def unresolved_incident_state(conn: PgConnection, sandbox: TenantSandbox) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT status, escalation_level FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s AND service_queue_id=%s ORDER BY id",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return cast(tuple[object, ...], tuple(row))
