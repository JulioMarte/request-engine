import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import LiteralString
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from request_engine.platform.db.session import SessionFactory

from .f6_copilot_support import copilot_actor, execute_tool, read_tool
from .f6_roadmap_support import seed_publishable_discovery_world
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


def _publish_body(sandbox: TenantSandbox) -> dict[str, object]:
    return {
        "offering_id": str(sandbox.offering_id),
        "location_id": str(sandbox.location_id),
        "resource_id": str(sandbox.resource_id),
        "effective_start": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "provider_visibility": "public",
    }


def _single_status(
    conn: PgConnection, sql: LiteralString, params: tuple[object, ...], status: str
) -> None:
    row = conn.execute(sql, params).fetchone()
    assert row is not None and row[0] == 1 and row[1] == status


async def _concurrent_posts(
    client: AsyncClient, sandbox: TenantSandbox, path: str, body: Mapping[str, object]
) -> tuple[Response, Response]:
    headers = auth(sandbox, idempotency_key=f"f6-conc-{uuid4().hex}")
    url = f"/v1/operational-copilot/tools{path}"
    first, second = await asyncio.gather(
        client.post(url, json=body, headers=headers),
        client.post(url, json=body, headers=headers),
    )
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json()["result_id"] == second.json()["result_id"]
    return first, second


async def test_f6_concurrent_discovery_publish_replays_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-concurrent-discovery-publish")
    seed_publishable_discovery_world(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await _concurrent_posts(client, sandbox, "/discovery/publications", _publish_body(sandbox))
    _single_status(
        e2e_admin_conn,
        "SELECT count(*), min(status) FROM request_engine.discovery_publications "
        "WHERE organization_id=%s AND offering_id=%s",
        (sandbox.organization_id, sandbox.offering_id),
        "active",
    )


async def test_f6_concurrent_discovery_revoke_replays_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-concurrent-discovery-revoke")
    seed_publishable_discovery_world(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        published = await execute_tool(
            client,
            sandbox,
            "/discovery/publications",
            _publish_body(sandbox),
            f"f6-conc-publish-{uuid4().hex}",
        )
        publication = await read_tool(
            client, sandbox, f"/discovery/publications/{published['result_id']}"
        )
        assert publication["status"] == "active"
        body = {
            "publication_id": published["result_id"],
            "expected_revision": publication["revision"],
        }
        await _concurrent_posts(client, sandbox, "/discovery/revocations", body)
    _single_status(
        e2e_admin_conn,
        "SELECT count(*), min(status) FROM request_engine.discovery_publications "
        "WHERE organization_id=%s AND offering_id=%s",
        (sandbox.organization_id, sandbox.offering_id),
        "revoked",
    )
