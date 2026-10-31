"""Unit proofs for the MCP JSON-RPC/Streamable HTTP adapter surface (ADR 0018).

Business authority is proved against PostgreSQL in tests/e2e/test_mcp_gateway_http.py;
these tests cover message parsing and transport refusals that happen before any
inner owner operation can run.
"""

import json
from uuid import uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.mcp_gateway import (
    JsonRpcFailure,
    JsonRpcNotification,
    JsonRpcRequest,
    negotiate_protocol_version,
    parse_message,
)
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.security.context import ActorContext

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_parse_valid_request_and_notification() -> None:
    parsed = parse_message(b'{"jsonrpc":"2.0","id":7,"method":"tools/list"}')
    assert parsed == JsonRpcRequest(7, "tools/list", {})
    notification = parse_message(b'{"jsonrpc":"2.0","method":"notifications/initialized"}')
    assert notification == JsonRpcNotification("notifications/initialized")
    assert parse_message(b'{"jsonrpc":"2.0","id":1,"result":{}}') is None


@pytest.mark.parametrize(
    ("raw", "code", "request_id"),
    [
        (b"{not json", -32700, None),
        (b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]', -32600, None),
        (b'"ping"', -32600, None),
        (b'{"jsonrpc":"1.0","id":1,"method":"ping"}', -32600, 1),
        (b'{"jsonrpc":"2.0","id":true,"method":"ping"}', -32600, None),
        (b'{"jsonrpc":"2.0","id":null,"method":"ping"}', -32600, None),
        (b'{"jsonrpc":"2.0","id":"a","method":5}', -32600, "a"),
        (b'{"jsonrpc":"2.0","id":"a","method":"ping","params":[1]}', -32600, "a"),
    ],
)
def test_invalid_messages_map_to_json_rpc_errors(raw: bytes, code: int, request_id: object) -> None:
    parsed = parse_message(raw)
    assert isinstance(parsed, JsonRpcFailure)
    assert parsed.code == code
    assert parsed.id == request_id


def test_protocol_version_negotiation_echoes_supported_else_latest() -> None:
    assert negotiate_protocol_version("2025-03-26") == "2025-03-26"
    assert negotiate_protocol_version("2025-06-18") == "2025-06-18"
    assert negotiate_protocol_version("1999-01-01") == "2025-06-18"
    assert negotiate_protocol_version(None) == "2025-06-18"


class _StaticResolver:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor
        self.calls = 0

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        self.calls += 1
        return self.actor


def _client(resolver: _StaticResolver) -> AsyncClient:
    engine = create_postgres_engine("postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    app = create_app(
        session_factory=create_session_factory(engine),
        actor_resolver=resolver,
        appointment_option_signing_key=b"mcp-gateway-unit-signing-key-0001",
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://re.example.test")


def _resolver(*capabilities: str) -> _StaticResolver:
    return _StaticResolver(
        ActorContext(
            organization_id=uuid4(),
            principal_id=uuid4(),
            capabilities=frozenset(capabilities),
        )
    )


def _rpc(method: str, params: dict[str, object] | None = None) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


@pytest.mark.asyncio
@pytest.mark.security
async def test_transport_refusals_happen_before_any_actor_resolution() -> None:
    resolver = _resolver("parties.lookup")
    path = f"/mcp/organizations/{uuid4()}"
    async with _client(resolver) as client:
        get = await client.get(path)
        assert get.status_code == 405
        assert get.headers["allow"] == "POST"

        missing_bearer = await client.post(path, json=_rpc("tools/list"))
        assert missing_bearer.status_code == 401
        assert missing_bearer.headers["www-authenticate"] == "Bearer"

        cross_origin = await client.post(
            path,
            json=_rpc("tools/list"),
            headers={"Authorization": "Bearer t", "Origin": "https://evil.example"},
        )
        assert cross_origin.status_code == 403

        bad_version = await client.post(
            path,
            json=_rpc("tools/list"),
            headers={"Authorization": "Bearer t", "MCP-Protocol-Version": "1999-01-01"},
        )
        assert bad_version.status_code == 400

        batch = await client.post(path, json=[_rpc("ping")], headers={"Authorization": "Bearer t"})
        assert batch.status_code == 400
        assert batch.json()["error"]["code"] == -32600
    assert resolver.calls == 0


@pytest.mark.asyncio
async def test_initialize_ping_notification_and_unknown_method() -> None:
    headers = {"Authorization": "Bearer t", "Origin": "https://re.example.test"}
    path = f"/mcp/organizations/{uuid4()}"
    async with _client(_resolver()) as client:
        initialized = await client.post(
            path,
            json=_rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}}),
            headers=headers,
        )
        assert initialized.status_code == 200
        result = initialized.json()["result"]
        assert result["protocolVersion"] == "2025-03-26"
        assert result["serverInfo"]["name"] == "request-engine"
        assert result["capabilities"] == {"tools": {"listChanged": False}}
        assert "idempotency_key" in result["instructions"]
        assert "proposal" in result["instructions"]
        assert "mcp-session-id" not in initialized.headers

        note = await client.post(
            path,
            content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            headers=headers,
        )
        assert (note.status_code, note.content) == (202, b"")

        ping = await client.post(path, json=_rpc("ping"), headers=headers)
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}

        unknown = await client.post(path, json=_rpc("resources/list"), headers=headers)
        assert unknown.json()["error"]["code"] == -32601


@pytest.mark.asyncio
@pytest.mark.security
async def test_tools_list_projects_only_operator_tools_the_actor_may_invoke() -> None:
    # parties.lookup is granted; parties.register is not; catalog.manage is granted
    # but its operations carry no tool projection, so they are never tools.
    resolver = _resolver("parties.lookup", "catalog.manage")
    headers = {"Authorization": "Bearer t"}
    async with _client(resolver) as client:
        listed = await client.post(
            f"/mcp/organizations/{uuid4()}", json=_rpc("tools/list"), headers=headers
        )
        assert listed.status_code == 200
        assert [tool["name"] for tool in listed.json()["result"]["tools"]] == ["parties_lookup"]

        hidden = await client.post(
            f"/mcp/organizations/{uuid4()}",
            json=_rpc(
                "tools/call",
                {"name": "parties_register", "arguments": {"display_name": "X"}},
            ),
            headers=headers,
        )
        assert hidden.json()["error"] == {
            "code": -32602,
            "message": "Unknown tool: parties_register",
        }
