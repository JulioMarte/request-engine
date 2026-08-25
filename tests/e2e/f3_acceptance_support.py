from typing import Any


F3_ACCEPTANCE_CAPABILITIES = frozenset(
    {
        "queue.check_in",
        "queue.staff_read",
        "service_session.start",
        "service_session.pause",
        "service_session.resume",
        "service_session.complete",
        "workload.list",
        "workload.create",
        "workload.update",
        "workload.deactivate",
    }
)


def acceptance_actor(sandbox: Any) -> Any:
    from .tenant_sandbox import actor_for

    base = actor_for(sandbox)
    return type(base)(
        organization_id=base.organization_id,
        principal_id=base.principal_id,
        capabilities=base.capabilities | F3_ACCEPTANCE_CAPABILITIES,
    )


def seed_walk_in_subject(conn: Any, sandbox: Any) -> Any:
    row = conn.execute(
        "INSERT INTO request_engine.parties "
        "(organization_id,party_kind,display_name) VALUES (%s,'person','Walk-in') RETURNING id",
        (sandbox.organization_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def reservation_snapshot(conn: Any, reservation_id: Any) -> Any:
    row = conn.execute(
        "SELECT to_jsonb(r) FROM request_engine.reservations r WHERE id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def capacity_claim_snapshot(conn: Any, reservation_id: Any) -> list[Any]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT to_jsonb(c) FROM request_engine.capacity_claims c "
            "WHERE reservation_id=%s ORDER BY id",
            (reservation_id,),
        ).fetchall()
    ]
