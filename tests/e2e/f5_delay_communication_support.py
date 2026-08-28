from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from httpx import AsyncClient

from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import seed_walk_in_subject
from .f5_recovery_world import RecoveryWorld
from .f5_scheduled_assessment_support import current_source_revision, lease_reassessment
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth


async def add_delay_walk_in(
    client: AsyncClient,
    conn: PgConnection,
    sandbox: TenantSandbox,
    world: RecoveryWorld,
) -> None:
    response = await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={
            "subject_party_id": str(seed_walk_in_subject(conn, sandbox)),
            "expected_workload_classification_id": str(world.walk_in_workload_id),
        },
        headers=auth(sandbox, idempotency_key=f"f5-delay-walk-in-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text


async def open_delay_incident(
    conn: PgConnection,
    session_factory: SessionFactory,
    sandbox: TenantSandbox,
) -> tuple[UUID, int]:
    revision = current_source_revision(conn, sandbox)
    lease = lease_reassessment(conn, sandbox, revision)
    handler = build_recovery_assessment_handler(session_factory)
    result = await handler.handle(lease)
    assert result.applied is True
    assert result.incident is not None
    return result.incident.id, revision


def delay_incident_row(conn: PgConnection, sandbox: TenantSandbox) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT impact_kind,status,source_revision "
        "FROM request_engine.operational_recovery_incidents "
        "WHERE organization_id=%s AND service_queue_id=%s AND status <> 'resolved'",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is not None
    return tuple(row)


def impact_action_row(
    conn: PgConnection,
    organization_id: UUID,
    action_id: UUID,
) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT action_kind,status,expected_source_revision,principal_id,failure_code "
        "FROM request_engine.operational_recovery_actions "
        "WHERE organization_id=%s AND id=%s",
        (organization_id, action_id),
    ).fetchone()
    assert row is not None
    return tuple(row)


def impact_task_row(
    conn: PgConnection,
    organization_id: UUID,
    dedupe_key: str,
) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT id,recipient_party_id,purpose,source_kind,source_id,status,dedupe_key "
        "FROM request_engine.communication_tasks "
        "WHERE organization_id=%s AND dedupe_key=%s",
        (organization_id, dedupe_key),
    ).fetchone()
    assert row is not None
    return tuple(row)


def recovery_fact_counts(conn: PgConnection, organization_id: UUID) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM request_engine.communication_tasks
             WHERE organization_id=%s),
          (SELECT count(*) FROM request_engine.operational_recovery_executions
             WHERE organization_id=%s)
        """,
        (organization_id, organization_id),
    ).fetchone()
    assert row is not None
    return cast(tuple[int, int], tuple(row))
