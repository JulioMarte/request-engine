"""INV-MCP-PROJECTION-001: the MCP gateway is a projection, not an authority.

An external MCP client connects to POST /mcp/organizations/{organization_id} with an
existing bearer. Tool discovery and execution re-enter the same runtime API, so the
agent's grants, fresh tool/risk policy, mutation budget, idempotency and lifecycle
status decide outcomes exactly as for direct HTTP. Durable effects are verified in
PostgreSQL independently of the MCP responses.
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

from .agent_policy_support import grant_agent_policy_authority, provision_agent_policy
from .native_provisioning_support import (
    PgConnection,
    grant_controller_delegable_operational_authority,
    login,
    principal_revision,
    provision_tenant_root,
    tenant_headers,
    uuid_row,
    workload_authority,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.contract,
]
_SIGNING_KEY = b"mcp-gateway-e2e-appointment-signing-key-v1"
_GRANTED = ("parties.register", "parties.lookup", "business.get_info", "appointments.book")


class _Mcp:
    def __init__(self, client: AsyncClient, organization_id: UUID, token: str) -> None:
        self._client = client
        self.path = f"/mcp/organizations/{organization_id}"
        self.headers = {"Authorization": f"Bearer {token}", "MCP-Protocol-Version": "2025-06-18"}
        self._next_id = 0

    async def rpc(self, method: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        self._next_id += 1
        response = await self._client.post(
            self.path,
            headers=self.headers,
            json={"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}},
        )
        assert response.status_code == 200, response.text
        assert "mcp-session-id" not in response.headers
        body = cast(dict[str, Any], response.json())
        assert body["id"] == self._next_id
        return body

    async def tool_names(self) -> set[str]:
        listed = await self.rpc("tools/list")
        return {tool["name"] for tool in listed["result"]["tools"]}

    async def call(self, name: str, arguments: Mapping[str, object]) -> dict[str, Any]:
        return await self.rpc("tools/call", {"name": name, "arguments": dict(arguments)})


def _party_rows(conn: PgConnection, organization_id: UUID, display_name: str) -> list[Any]:
    return conn.execute(
        """
        SELECT id, created_by_principal_id FROM request_engine.parties
         WHERE organization_id = %s AND display_name = %s
        """,
        (organization_id, display_name),
    ).fetchall()


def _mutations(conn: PgConnection, agent_principal_id: UUID) -> object:
    row = conn.execute(
        "SELECT coalesce(sum(mutation_count), 0) FROM request_engine.agent_budget_windows "
        "WHERE agent_principal_id = %s",
        (agent_principal_id,),
    ).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.asyncio
async def test_mcp_tools_project_current_authority_and_execute_owner_operations(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = uuid_row(
        e2e_admin_conn,
        """
        INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
        VALUES ('native', %s) RETURNING id
        """,
        (f"mcp-gateway-e2e-{uuid4().hex}",),
    )
    root_password = "root-mcp-e2e-password-1"
    root_identity = await build_native_auth_runtime(
        e2e_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"owner-mcp-{uuid4().hex}@example.test",
        password=root_password,
    )
    organization_id, controller_principal_id = provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    workload_authority_id = workload_authority(e2e_admin_conn)
    for capability in _GRANTED:
        grant_controller_delegable_operational_authority(
            e2e_admin_conn,
            organization_id=organization_id,
            controller_principal_id=controller_principal_id,
            capability_key=capability,
        )
    grant_agent_policy_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://re.example.test"
    ) as client:
        root_token = await login(
            client, login_handle=root_identity.login_handle, password=root_password
        )
        controller_headers = tenant_headers(token=root_token, organization_id=organization_id)

        # A business owner's "Chief of Staff" agent, provisioned through the real API.
        provisioned = await client.post(
            "/v1/agents",
            headers=tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"mcp-agent-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(workload_authority_id),
                "display_name": "Chief of Staff",
                "purpose": "assist the owner with patients and appointments",
                "sponsor_principal_id": str(controller_principal_id),
                "operating_mode": "assisted",
                "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "provenance_reference": "mcp-gateway-e2e-provision",
            },
        )
        assert provisioned.status_code == 201, provisioned.text
        agent_principal_id = UUID(provisioned.json()["principal_id"])
        agent_mcp = _Mcp(client, organization_id, provisioned.json()["workload_token"])

        activated = await client.put(
            f"/v1/agents/{agent_principal_id}/status",
            headers={**controller_headers, "Idempotency-Key": f"mcp-act-{uuid4().hex}"},
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "mcp-gateway-e2e-activate",
            },
        )
        assert activated.status_code == 200, activated.text
        assigned = await client.put(
            f"/v1/agents/{agent_principal_id}/authority",
            headers={**controller_headers, "Idempotency-Key": f"mcp-auth-{uuid4().hex}"},
            json={
                "expected_authority_revision": principal_revision(
                    e2e_admin_conn, agent_principal_id
                ),
                "desired_capabilities": list(_GRANTED),
                "provenance_reference": "mcp-gateway-e2e-authority",
            },
        )
        assert assigned.status_code == 200, assigned.text

        # Without a policy the least-privilege default denies discovery itself.
        no_policy = await agent_mcp.rpc("tools/list")
        assert no_policy["error"]["code"] == -32003
        assert no_policy["error"]["data"]["response"]["error"]["code"] == "agent_policy_denied"

        await provision_agent_policy(
            client,
            controller_headers=controller_headers,
            agent_principal_id=agent_principal_id,
            allowed_capabilities=["parties.register", "parties.lookup", "appointments.book"],
            denied_capabilities=["business.get_info"],
            risk_ceiling="low_impact_write",
            max_mutations_per_minute=10,
        )

        initialized = await agent_mcp.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "1"},
            },
        )
        assert initialized["result"]["protocolVersion"] == "2025-06-18"
        assert initialized["result"]["capabilities"] == {"tools": {"listChanged": False}}

        # Granted ∩ allowed − denied, within the risk ceiling: granted business.get_info
        # is denied by policy and appointments.book (external commitment) exceeds it.
        assert await agent_mcp.tool_names() == {"parties_register", "parties_lookup"}

        display_name = f"MCP Patient {uuid4().hex[:8]}"
        key = f"mcp-register-{uuid4().hex}"
        budget_before = _mutations(e2e_admin_conn, agent_principal_id)
        registered = await agent_mcp.call(
            "parties_register", {"display_name": display_name, "idempotency_key": key}
        )
        result = registered["result"]
        assert result["isError"] is False, result
        party_id = UUID(result["structuredContent"]["party_id"])
        assert _party_rows(e2e_admin_conn, organization_id, display_name) == [
            (party_id, agent_principal_id)
        ]
        assert _mutations(e2e_admin_conn, agent_principal_id) != budget_before

        replayed = await agent_mcp.call(
            "parties_register", {"display_name": display_name, "idempotency_key": key}
        )
        assert replayed["result"]["isError"] is False
        assert UUID(replayed["result"]["structuredContent"]["party_id"]) == party_id
        assert len(_party_rows(e2e_admin_conn, organization_id, display_name)) == 1
        budget_after_replay = _mutations(e2e_admin_conn, agent_principal_id)

        # Out-of-policy tools are unknown, with no execution and no budget consumed.
        for hidden_tool, arguments in (
            ("business_get_info", {}),
            (
                "appointments_book",
                {
                    "option_id": f"mcp-option-{uuid4().hex}",
                    "subject_party_id": str(party_id),
                    "idempotency_key": f"mcp-book-{uuid4().hex}",
                },
            ),
        ):
            hidden = await agent_mcp.call(hidden_tool, arguments)
            assert hidden["error"] == {"code": -32602, "message": f"Unknown tool: {hidden_tool}"}
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
            (organization_id,),
        ).fetchone() == (0,)

        # Model arguments cannot inject tenant or principal identity.
        injected_name = f"MCP Injected {uuid4().hex[:8]}"
        injected = await agent_mcp.call(
            "parties_register",
            {
                "display_name": injected_name,
                "idempotency_key": f"mcp-inject-{uuid4().hex}",
                "organization_id": str(uuid4()),
            },
        )
        assert injected["error"]["code"] == -32602
        assert _party_rows(e2e_admin_conn, organization_id, injected_name) == []
        assert _mutations(e2e_admin_conn, agent_principal_id) == budget_after_replay

        # A human session uses the same gateway; its own grants decide its tools.
        owner_mcp = _Mcp(client, organization_id, root_token)
        assert {
            "parties_register",
            "parties_lookup",
            "business_get_info",
            "appointments_book",
        } <= await owner_mcp.tool_names()
        looked_up = await owner_mcp.call("parties_lookup", {"mode": "name", "value": display_name})
        assert looked_up["result"]["isError"] is False
        assert any(
            entry["party_id"] == str(party_id) and entry["display_name"] == display_name
            for entry in _json_text(looked_up)
        )

        # An owner validation failure stays a tool result carrying the API envelope.
        invalid_lookup = await owner_mcp.call(
            "parties_lookup", {"mode": "not-a-mode", "value": display_name}
        )
        assert invalid_lookup["result"]["isError"] is True
        assert "error" in invalid_lookup["result"]["structuredContent"]

        suspended = await client.put(
            f"/v1/agents/{agent_principal_id}/status",
            headers={**controller_headers, "Idempotency-Key": f"mcp-susp-{uuid4().hex}"},
            json={
                "expected_revision": 2,
                "target_status": "suspended",
                "provenance_reference": "mcp-gateway-e2e-suspend",
            },
        )
        assert suspended.status_code == 200, suspended.text
        after_suspend = await agent_mcp.call(
            "parties_lookup", {"mode": "name", "value": display_name}
        )
        assert after_suspend["result"]["isError"] is True
        assert (
            after_suspend["result"]["structuredContent"]["error"]["code"]
            == "identity_binding_suspended"
        )
        suspended_register = await agent_mcp.call(
            "parties_register",
            {"display_name": f"{display_name} 2", "idempotency_key": f"mcp-{uuid4().hex}"},
        )
        assert suspended_register["result"]["isError"] is True
        assert _party_rows(e2e_admin_conn, organization_id, f"{display_name} 2") == []

        # Transport refusals: missing/invalid bearer and cross-origin browsers.
        list_request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        no_bearer = await client.post(agent_mcp.path, json=list_request)
        assert no_bearer.status_code == 401
        assert no_bearer.headers["www-authenticate"] == "Bearer"
        invalid_bearer = await client.post(
            agent_mcp.path,
            json=list_request,
            headers={"Authorization": f"Bearer {uuid4()}.{uuid4().hex}"},
        )
        assert invalid_bearer.status_code == 401
        assert invalid_bearer.headers["www-authenticate"].startswith("Bearer")
        cross_origin = await client.post(
            owner_mcp.path,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "parties_register",
                    "arguments": {
                        "display_name": f"{display_name} xo",
                        "idempotency_key": f"mcp-xo-{uuid4().hex}",
                    },
                },
            },
            headers={**owner_mcp.headers, "Origin": "https://attacker.example"},
        )
        assert cross_origin.status_code == 403
        assert _party_rows(e2e_admin_conn, organization_id, f"{display_name} xo") == []
        same_origin = await client.post(
            owner_mcp.path,
            json=list_request,
            headers={**owner_mcp.headers, "Origin": "https://re.example.test"},
        )
        assert same_origin.status_code == 200


def _json_text(response: dict[str, Any]) -> list[dict[str, Any]]:
    content = response["result"]["content"]
    assert content[0]["type"] == "text"
    return cast(list[dict[str, Any]], json.loads(content[0]["text"]))
