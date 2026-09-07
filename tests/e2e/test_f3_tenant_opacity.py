from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .evidence import durable_snapshot
from .operational_support import PgConnection
from .tenant_sandbox import (
    TenantSandbox,
    auth,
    client_with_actors,
    seed_tenant_sandbox,
)


def _seed_live_session(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.queue_entries "
        "(organization_id,service_queue_id,subject_party_id,status,"
        "arrived_at,admitted_at,called_at) "
        "VALUES (%s,%s,%s,'called','2030-01-07T13:59Z','2030-01-07T13:59Z',"
        "'2030-01-07T14:00Z') RETURNING id",
        (sandbox.organization_id, sandbox.queue_id, sandbox.party_id),
    ).fetchone()
    assert row is not None
    entry_id = cast(UUID, row[0])
    with conn.transaction():
        conn.execute(
            "UPDATE request_engine.queue_entries SET status='serving',"
            "service_started_at='2030-01-07T14:01Z',revision=revision+1 WHERE id=%s",
            (entry_id,),
        )
        session = conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,started_at) "
            "VALUES (%s,%s,%s,%s,'2030-01-07T14:01Z') RETURNING id",
            (
                sandbox.organization_id,
                entry_id,
                sandbox.resource_id,
                sandbox.location_id,
            ),
        ).fetchone()
    assert session is not None
    return cast(UUID, session[0])


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
@pytest.mark.security
@pytest.mark.adversarial
async def test_foreign_service_session_is_indistinguishable_from_random_id(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    actor_tenant = seed_tenant_sandbox(e2e_admin_conn, "f3-opacity-actor")
    foreign_tenant = seed_tenant_sandbox(e2e_admin_conn, "f3-opacity-foreign")
    foreign_session = _seed_live_session(e2e_admin_conn, foreign_tenant)
    actor = ActorContext(
        organization_id=actor_tenant.organization_id,
        principal_id=actor_tenant.principal_id,
        capabilities=frozenset({"service_session.read"}),
    )
    before = durable_snapshot(e2e_admin_conn)
    async with client_with_actors(e2e_session_factory, {actor_tenant.token: actor}) as client:
        foreign = await client.get(
            f"/v1/service-sessions/{foreign_session}", headers=auth(actor_tenant)
        )
        random = await client.get(f"/v1/service-sessions/{uuid4()}", headers=auth(actor_tenant))
    assert foreign.status_code == random.status_code == 404
    assert foreign.json() == random.json()
    assert str(foreign_session) not in foreign.text
    assert durable_snapshot(e2e_admin_conn) == before
