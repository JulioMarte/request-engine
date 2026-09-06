from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from request_engine.platform.db.session import SessionFactory

from .f5_recovery_support import f5_actor
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors

AffectedFact = tuple[UUID, datetime, datetime | None, bool]


async def grant_autonomy_policy(
    session_factory: SessionFactory,
    sandbox: TenantSandbox,
    *,
    max_delay_minutes: int,
    max_auto_actions_per_incident: int,
    enabled: bool = True,
) -> dict[str, Any]:
    async with client_with_actors(session_factory, {sandbox.token: f5_actor(sandbox)}) as client:
        response = await client.post(
            f"/v1/operational-recovery/queues/{sandbox.queue_id}/autonomy-policy",
            json={
                "enabled": enabled,
                "max_delay_minutes": max_delay_minutes,
                "max_auto_actions_per_incident": max_auto_actions_per_incident,
            },
            headers=auth(sandbox, idempotency_key=f"f5-autonomy-{uuid4().hex}"),
        )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def autonomous_action_rows(conn: PgConnection, sandbox: TenantSandbox) -> list[tuple[Any, ...]]:
    rows = conn.execute(
        """
        SELECT a.action_kind, a.status, a.failure_code,
               p.principal_kind, p.external_subject
        FROM request_engine.operational_recovery_actions a
        JOIN request_engine.principals p
          ON p.organization_id = a.organization_id AND p.id = a.principal_id
        WHERE a.organization_id = %s
          AND a.incident_id IN (
              SELECT id FROM request_engine.operational_recovery_incidents
              WHERE organization_id = %s AND service_queue_id = %s)
          AND a.idempotency_key LIKE %s
        ORDER BY a.created_at, a.id
        """,
        (sandbox.organization_id, sandbox.organization_id, sandbox.queue_id, "recovery-auto:%"),
    ).fetchall()
    return [tuple(row) for row in rows]


def autonomous_rescheduled_tasks(
    conn: PgConnection, sandbox: TenantSandbox
) -> list[tuple[Any, ...]]:
    rows = conn.execute(
        """
        SELECT t.purpose, t.template_key, t.dedupe_key, p.external_subject
        FROM request_engine.idempotency_records r
        JOIN request_engine.principals p
          ON p.organization_id = r.organization_id AND p.id = r.principal_id
        JOIN request_engine.communication_tasks t
          ON t.organization_id = r.organization_id
         AND t.id = (r.result_data->'communication_task'->>'id')::uuid
        WHERE r.organization_id = %s
          AND r.capability = 'communications.create_task'
          AND r.idempotency_key LIKE %s
        ORDER BY t.created_at, t.id
        """,
        (sandbox.organization_id, "recovery-rescheduled-auto:%"),
    ).fetchall()
    return [tuple(row) for row in rows]


def proposal_affected(
    conn: PgConnection, organization_id: UUID, proposal_id: UUID
) -> list[AffectedFact]:
    row = conn.execute(
        "SELECT snapshot->'affected' FROM request_engine.operational_recovery_proposals "
        "WHERE organization_id=%s AND id=%s",
        (organization_id, proposal_id),
    ).fetchone()
    assert row is not None and row[0] is not None
    affected: list[dict[str, Any]] = cast(list[dict[str, Any]], row[0])
    return [
        (
            UUID(cast(str, item["reservation_id"])),
            datetime.fromisoformat(cast(str, item["original_start_at"])),
            (
                datetime.fromisoformat(cast(str, item["target"]["start_at"]))
                if item["target"] is not None
                else None
            ),
            item["target"] is not None,
        )
        for item in affected
    ]


def reservation_window(
    conn: PgConnection, sandbox: TenantSandbox, reservation_id: UUID
) -> tuple[datetime, datetime, UUID]:
    row = conn.execute(
        "SELECT lower(during), upper(during), subject_party_id "
        "FROM request_engine.reservations WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, reservation_id),
    ).fetchone()
    assert row is not None
    return (
        cast(datetime, row[0]),
        cast(datetime, row[1]),
        cast(UUID, row[2]),
    )


def open_incident_status(conn: PgConnection, sandbox: TenantSandbox) -> str | None:
    row = conn.execute(
        "SELECT status FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s AND service_queue_id=%s "
        "ORDER BY created_at DESC LIMIT 1",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return cast(str | None, row[0])
