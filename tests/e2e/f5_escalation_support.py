from __future__ import annotations

from typing import cast

from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.modules.operational_recovery.adapters.worker.scheduled_assessment import (
    RecoveryAssessmentScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory

from .f5_delay_communication_support import add_delay_walk_in
from .f5_recovery_support import f5_actor
from .f5_recovery_world import RecoveryWorld, prepare_recovery_world
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox


async def escalation_world(
    conn: PgConnection,
    session_factory: SessionFactory,
    label: str,
    *,
    capacity_slots: int = 6,
    walk_in: bool = False,
) -> tuple[TenantSandbox, RecoveryWorld, RecoveryAssessmentScheduledHandler]:
    sandbox = seed_tenant_sandbox(conn, label)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(session_factory, actors) as client:
        world = await prepare_recovery_world(
            client,
            conn,
            sandbox,
            capacity_slots=capacity_slots,
        )
        if walk_in:
            await add_delay_walk_in(client, conn, sandbox, world)
    handler = build_recovery_assessment_handler(session_factory)
    return sandbox, world, handler


def advance_source_revision(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        "INSERT INTO request_engine.location_hours_exceptions "
        "(organization_id,location_id,during,exception_kind,reason,active) "
        "VALUES (%s,%s,tstzrange(clock_timestamp()+interval '3 days',"
        "clock_timestamp()+interval '3 days 1 hour','[)'),'available','stale policy',true)",
        (sandbox.organization_id, sandbox.location_id),
    )


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


def automatic_recovery_facts(conn: PgConnection, organization_id: object) -> tuple[int, int, int]:
    """(recovery actions, communication tasks, task outbox rows) created by automation."""

    row = conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.operational_recovery_actions "
        "WHERE organization_id=%s),"
        "(SELECT count(*) FROM request_engine.communication_tasks WHERE organization_id=%s),"
        "(SELECT count(*) FROM request_engine.outbox_messages WHERE organization_id=%s "
        "AND aggregate_kind='CommunicationTask')",
        (organization_id, organization_id, organization_id),
    ).fetchone()
    assert row is not None
    return cast(tuple[int, int, int], tuple(row))


def autonomous_impact_task(
    conn: PgConnection, sandbox: TenantSandbox, incident_id: object, revision: int
) -> tuple[object, ...] | None:
    """Impact task row (id, purpose, template, principal kind/subject) for the
    section 13 identity, attributed through the idempotency record of its creator."""

    row = conn.execute(
        """
        SELECT t.id, t.purpose, t.template_key, p.principal_kind, p.external_subject
        FROM request_engine.communication_tasks t
        JOIN request_engine.idempotency_records r
          ON r.organization_id = t.organization_id
         AND r.capability = 'communications.create_task'
         AND r.idempotency_key = %s
        JOIN request_engine.principals p
          ON p.organization_id = r.organization_id AND p.id = r.principal_id
        WHERE t.organization_id = %s AND t.dedupe_key = %s
        """,
        (
            f"recovery-impact-auto:{incident_id}:{sandbox.party_id}:{revision}:v1",
            sandbox.organization_id,
            f"operational-recovery:{incident_id}:impact:{sandbox.party_id}:{revision}",
        ),
    ).fetchone()
    return None if row is None else cast(tuple[object, ...], tuple(row))
