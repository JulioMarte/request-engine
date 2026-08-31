import pytest

from request_engine.platform.db.session import SessionFactory

from .discovery_operational_support import grant_manage_discovery
from .discovery_seed_support import create_classification
from .f4_capacity_support import seed_live_execution_assignment
from .f6_copilot_support import copilot_actor, execute
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
]


async def test_f6_executes_roadmap_named_discovery_publication(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-roadmap-natural-discovery")
    seed_live_execution_assignment(e2e_admin_conn, sandbox)
    grant_manage_discovery(e2e_admin_conn, sandbox)
    classification_id, _ = create_classification(e2e_admin_conn)
    e2e_admin_conn.execute(
        "UPDATE request_engine.resources SET display_name='Dr. B' "
        "WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, sandbox.resource_id),
    )
    e2e_admin_conn.execute(
        "UPDATE request_engine.offerings SET display_name='Cardiology' "
        "WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, sandbox.offering_id),
    )
    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.offering_service_classifications (
            organization_id, offering_id, service_classification_id
        ) VALUES (%s, %s, %s)
        """,
        (sandbox.organization_id, sandbox.offering_id, classification_id),
    )
    actors = {sandbox.token: copilot_actor(sandbox)}

    async with client_with_actors(e2e_session_factory, actors) as client:
        key = "f6-roadmap-dr-b-cardiology"
        text = "publish Dr. B for cardiology discovery"
        executed = await execute(client, sandbox, text, key)
        replay = await execute(client, sandbox, text, key)

    assert executed["owner"] == "discovery"
    assert executed["action"] == "publish_discovery_supply"
    assert executed["status"] == "active"
    assert replay["result_id"] == executed["result_id"]
    rows = e2e_admin_conn.execute(
        """
        SELECT id, offering_id, location_id, resource_id, provider_visibility
        FROM request_engine.discovery_publications
        WHERE organization_id=%s AND offering_id=%s AND resource_id=%s
        """,
        (sandbox.organization_id, sandbox.offering_id, sandbox.resource_id),
    ).fetchall()
    assert len(rows) == 1
    assert str(rows[0][0]) == executed["result_id"]
    assert rows[0][1] == sandbox.offering_id
    assert rows[0][2] == sandbox.location_id
    assert rows[0][3] == sandbox.resource_id
    assert rows[0][4] == "public"
