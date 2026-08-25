from __future__ import annotations

from uuid import UUID

from request_engine.platform.security.context import ActorContext

from .tenant_sandbox import TenantSandbox, actor_for
from . import operational_support as support


_ACCEPTANCE_CAPABILITIES = frozenset(
    {
        "queue.check_in",
        "queue.staff_read",
        "service_session.start",
        "service_session.pause",
        "service_session.resume",
        "service_session.complete",
        "workload.create",
    }
)


def acceptance_actor(sandbox: TenantSandbox) -> ActorContext:
    base = actor_for(sandbox)
    return ActorContext(
        organization_id=base.organization_id,
        principal_id=base.principal_id,
        capabilities=base.capabilities | _ACCEPTANCE_CAPABILITIES,
    )


def seed_walk_in_subject(conn: support.PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.parties "
        "(organization_id,party_kind,display_name) VALUES (%s,'person','Walk-in') RETURNING id",
        (sandbox.organization_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def reservation_snapshot(conn: support.PgConnection, reservation_id: UUID) -> object:
    row = conn.execute(
        "SELECT to_jsonb(r) FROM request_engine.reservations r WHERE id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def capacity_claim_snapshot(
    conn: support.PgConnection,
    reservation_id: UUID,
) -> list[object]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT to_jsonb(c) FROM request_engine.capacity_claims c "
            "WHERE reservation_id=%s ORDER BY id",
            (reservation_id,),
        ).fetchall()
    ]


def assert_completed_journey(
    conn: support.PgConnection,
    *,
    entry_id: UUID,
    session_id: UUID,
    expected_workload_id: UUID,
    actual_workload_id: UUID,
) -> None:
    queue_state = conn.execute(
        "SELECT status,expected_workload_classification_id,service_started_at,completed_at "
        "FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert queue_state is not None
    assert queue_state[:2] == ("completed", expected_workload_id)
    session = conn.execute(
        "SELECT status,actual_workload_classification_id,started_at,completed_at "
        "FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    assert session is not None
    assert session[:2] == ("completed", actual_workload_id)
    assert queue_state[2:] == session[2:]
    assert actual_workload_id != expected_workload_id
    interruption = conn.execute(
        "SELECT kind,started_at,ended_at "
        "FROM request_engine.service_session_interruptions WHERE service_session_id=%s",
        (session_id,),
    ).fetchone()
    assert interruption is not None
    assert interruption[0] == "administrative"
    assert session[2] <= interruption[1] <= interruption[2] <= session[3]
