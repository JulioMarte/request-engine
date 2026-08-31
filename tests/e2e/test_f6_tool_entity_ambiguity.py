from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_live_execution_assignment
from .f6_ambiguity_support import seed_second_location_assignment
from .f6_copilot_support import copilot_actor, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


def _error_message(response) -> str:
    return str(response.json()["error"]["message"])


async def test_resource_lookup_exposes_each_current_location_and_text_refuses_ambiguity(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-resource-multi-location")
    seed_live_execution_assignment(e2e_admin_conn, sandbox)
    second_location = seed_second_location_assignment(
        e2e_admin_conn, sandbox.organization_id, sandbox.resource_id
    )
    e2e_admin_conn.execute(
        "UPDATE request_engine.resources SET display_name='Dr. Multi' WHERE id=%s",
        (sandbox.resource_id,),
    )
    e2e_admin_conn.execute(
        "UPDATE request_engine.offerings SET display_name='Cardiology' WHERE id=%s",
        (sandbox.offering_id,),
    )
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        resources = await read_tool(client, sandbox, "/resources?reference=Dr.%20Multi")
        assert len(resources) == 2
        assert {item["resource_id"] for item in resources} == {str(sandbox.resource_id)}
        assert {item["location_id"] for item in resources} == {
            str(sandbox.location_id),
            str(second_location),
        }
        assert len({item["assignment_id"] for item in resources}) == 2
        assert {item["display_name"] for item in resources} == {"Dr. Multi"}
        response = await client.post(
            "/v1/operational-copilot/interpret",
            json={"text": "publish Dr. Multi for Cardiology discovery"},
            headers=auth(sandbox, idempotency_key="f6-resource-multi-location"),
        )
    assert response.status_code == 422, response.text
    assert "multiple tenant-scoped resource values matched" in _error_message(response)


async def test_offering_lookup_exposes_duplicate_names_and_text_refuses_ambiguity(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-offering-ambiguity")
    seed_live_execution_assignment(e2e_admin_conn, sandbox)
    e2e_admin_conn.execute(
        "UPDATE request_engine.resources SET display_name='Dr. B' WHERE id=%s",
        (sandbox.resource_id,),
    )
    e2e_admin_conn.execute(
        "UPDATE request_engine.offerings SET display_name='Cardiology' WHERE id=%s",
        (sandbox.offering_id,),
    )
    second_offering = uuid4()
    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.offerings (
            id, organization_id, offering_key, display_name, description
        ) VALUES (%s, %s, %s, 'Cardiology', 'Ambiguity acceptance fixture')
        """,
        (second_offering, sandbox.organization_id, f"cardiology-{uuid4().hex}"),
    )
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        offerings = await read_tool(client, sandbox, "/offerings?reference=Cardiology")
        assert {item["offering_id"] for item in offerings} == {
            str(sandbox.offering_id),
            str(second_offering),
        }
        assert {item["display_name"] for item in offerings} == {"Cardiology"}
        response = await client.post(
            "/v1/operational-copilot/interpret",
            json={"text": "publish Dr. B for Cardiology discovery"},
            headers=auth(sandbox, idempotency_key="f6-offering-ambiguity"),
        )
    assert response.status_code == 422, response.text
    assert "multiple tenant-scoped offering values matched" in _error_message(response)
