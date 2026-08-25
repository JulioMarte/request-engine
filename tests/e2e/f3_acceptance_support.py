from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from httpx import AsyncClient

from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, actor_for, auth


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


def acceptance_actor(sandbox: TenantSandbox) -> ActorContext:
    base = actor_for(sandbox)
    return ActorContext(
        organization_id=base.organization_id,
        principal_id=base.principal_id,
        capabilities=base.capabilities | F3_ACCEPTANCE_CAPABILITIES,
    )


def seed_walk_in_subject(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.parties "
        "(organization_id,party_kind,display_name) VALUES (%s,'person',%s) RETURNING id",
        (sandbox.organization_id, f"Walk-in {uuid4().hex[:8]}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def reservation_snapshot(conn: PgConnection, reservation_id: UUID) -> Any:
    row = conn.execute(
        "SELECT to_jsonb(r) FROM request_engine.reservations r WHERE id=%s",
        (reservation_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def capacity_claim_snapshot(conn: PgConnection, reservation_id: UUID) -> list[Any]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT to_jsonb(c) FROM request_engine.capacity_claims c "
            "WHERE reservation_id=%s ORDER BY id",
            (reservation_id,),
        ).fetchall()
    ]


async def create_workload(
    client: AsyncClient,
    sandbox: TenantSandbox,
    workload_key: str,
    display_name: str,
) -> UUID:
    response = await client.post(
        "/v1/live-workloads",
        json={"workload_key": workload_key, "display_name": display_name},
        headers=auth(sandbox, idempotency_key=f"workload-{uuid4().hex}"),
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])
