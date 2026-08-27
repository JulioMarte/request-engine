from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from httpx import AsyncClient, Response

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth


async def create_proposal(client: AsyncClient, sandbox: TenantSandbox) -> dict[str, Any]:
    response = await client.post(
        f"/v1/operational-recovery/service-queues/{sandbox.queue_id}/proposals",
        json={"search_days": 7},
        headers=auth(sandbox, idempotency_key=f"f5-proposal-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


async def execute_proposal(
    client: AsyncClient,
    sandbox: TenantSandbox,
    proposal: dict[str, Any],
    reservation_id: UUID,
    *,
    idempotency_key: str,
    notify: bool = True,
) -> Response:
    return await client.post(
        f"/v1/operational-recovery/proposals/{proposal['id']}/execute",
        json={
            "reservation_id": str(reservation_id),
            "expected_source_fingerprint": proposal["source_fingerprint"],
            "expected_proposal_fingerprint": proposal["proposal_fingerprint"],
            "notify": notify,
        },
        headers=auth(sandbox, idempotency_key=idempotency_key),
    )


def recovery_counts(conn: PgConnection, organization_id: UUID) -> tuple[int, int, int]:
    row = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM request_engine.operational_recovery_executions
             WHERE organization_id=%s),
          (SELECT count(*) FROM request_engine.communication_tasks
             WHERE organization_id=%s),
          (SELECT count(*) FROM request_engine.outbox_messages
             WHERE organization_id=%s)
        """,
        (organization_id, organization_id, organization_id),
    ).fetchone()
    assert row is not None
    return cast(tuple[int, int, int], row)


def reservation_state(conn: PgConnection, reservation_id: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT revision,status,lower(during),upper(during) "
        "FROM request_engine.reservations WHERE id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def execution_row(
    conn: PgConnection,
    organization_id: UUID,
    proposal_id: UUID,
    reservation_id: UUID,
) -> tuple[object, ...]:
    rows = conn.execute(
        "SELECT id,status,executed_by_principal_id,original_reservation_revision,"
        "resulting_reservation_revision,communication_task_id,failure_code "
        "FROM request_engine.operational_recovery_executions "
        "WHERE organization_id=%s AND proposal_id=%s AND reservation_id=%s",
        (organization_id, proposal_id, reservation_id),
    ).fetchall()
    assert len(rows) == 1
    return tuple(rows[0])


def communication_lineage(
    conn: PgConnection,
    organization_id: UUID,
    execution_id: UUID,
) -> list[tuple[object, ...]]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT id,dedupe_key,source_kind,source_id FROM request_engine.communication_tasks "
            "WHERE organization_id=%s AND source_kind='OperationalRecoveryExecution' "
            "AND source_id=%s ORDER BY id",
            (organization_id, execution_id),
        ).fetchall()
    ]


def outbox_for_task(
    conn: PgConnection,
    organization_id: UUID,
    task_id: UUID,
) -> list[tuple[object, ...]]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT id,event_type,aggregate_kind,aggregate_id FROM request_engine.outbox_messages "
            "WHERE organization_id=%s AND aggregate_kind='CommunicationTask' "
            "AND aggregate_id=%s ORDER BY id",
            (organization_id, task_id),
        ).fetchall()
    ]
