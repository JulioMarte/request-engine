from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .discovery_operational_support import grant_manage_discovery
from .discovery_seed_support import create_classification
from .f4_capacity_support import seed_live_execution_assignment
from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.contract]


async def test_f6_structured_discovery_publish_revoke_and_replay(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-structured-discovery")
    seed_live_execution_assignment(e2e_admin_conn, sandbox)
    grant_manage_discovery(e2e_admin_conn, sandbox)
    classification_id, _ = create_classification(e2e_admin_conn)
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
        publish_key = f"f6-publish-{uuid4().hex}"
        publish_body = {
            "offering_id": str(sandbox.offering_id),
            "location_id": str(sandbox.location_id),
            "resource_id": str(sandbox.resource_id),
            "effective_start": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            "provider_visibility": "public",
        }
        published = await execute_tool(
            client, sandbox, "/discovery/publications", publish_body, publish_key
        )
        publish_replay = await execute_tool(
            client, sandbox, "/discovery/publications", publish_body, publish_key
        )
        assert published["action"] == "publish_discovery_supply"
        assert publish_replay["result_id"] == published["result_id"]

        publication = await read_tool(
            client,
            sandbox,
            f"/discovery/publications/{published['result_id']}",
        )
        assert publication["status"] == "active"
        revoke_key = f"f6-revoke-{uuid4().hex}"
        revoke_body = {
            "publication_id": published["result_id"],
            "expected_revision": publication["revision"],
        }
        revoked = await execute_tool(
            client, sandbox, "/discovery/revocations", revoke_body, revoke_key
        )
        replay = await execute_tool(
            client, sandbox, "/discovery/revocations", revoke_body, revoke_key
        )
        assert revoked["action"] == "revoke_discovery_publication"
        assert replay["result_id"] == revoked["result_id"]
        final_state = await read_tool(
            client,
            sandbox,
            f"/discovery/publications/{published['result_id']}",
        )
        assert final_state["status"] == "revoked"

    row = e2e_admin_conn.execute(
        """
        SELECT count(*), min(status) FROM request_engine.discovery_publications
        WHERE organization_id=%s AND id=%s
        """,
        (sandbox.organization_id, published["result_id"]),
    ).fetchone()
    assert row is not None and row[0] == 1 and row[1] == "revoked"
