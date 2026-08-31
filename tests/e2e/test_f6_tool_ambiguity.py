from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

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


async def test_f6_lists_human_queue_candidates_and_text_fails_closed_on_ambiguity(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-queue-ambiguity")
    e2e_admin_conn.execute(
        "UPDATE request_engine.service_queues SET display_name='Cardiology' WHERE id=%s",
        (sandbox.queue_id,),
    )
    second_id = uuid4()
    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.service_queues (
            id, organization_id, location_id, offering_id, queue_key, display_name
        ) VALUES (%s, %s, %s, %s, %s, 'Laboratory')
        """,
        (
            second_id,
            sandbox.organization_id,
            sandbox.location_id,
            sandbox.offering_id,
            f"lab-{uuid4().hex}",
        ),
    )
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        queues = await read_tool(client, sandbox, "/queues")
        assert {item["display_name"] for item in queues} == {"Cardiology", "Laboratory"}
        assert {item["service_queue_id"] for item in queues} == {
            str(sandbox.queue_id),
            str(second_id),
        }
        response = await client.post(
            "/v1/operational-copilot/interpret",
            json={"text": "show me which Reservations are at risk"},
            headers=auth(sandbox, idempotency_key=f"f6-ambiguous-{uuid4().hex}"),
        )
        assert response.status_code == 422, response.text
        assert "ambiguous queue" in _error_message(response).lower()


async def test_f6_recovery_text_refuses_without_open_incident(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-no-incident")
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        incident = await client.get(
            f"/v1/operational-copilot/tools/queues/{sandbox.queue_id}/recovery-incident",
            headers=auth(sandbox),
        )
        assert incident.status_code == 404
        response = await client.post(
            "/v1/operational-copilot/execute",
            json={"text": "stop accepting walk-ins for the rest of the day"},
            headers=auth(sandbox, idempotency_key=f"f6-no-incident-{uuid4().hex}"),
        )
        assert response.status_code == 422, response.text
        assert "no open recovery incident" in _error_message(response).lower()
