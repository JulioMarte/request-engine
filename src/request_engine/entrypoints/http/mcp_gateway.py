"""MCP Streamable HTTP adapter for the tenant runtime API (ADR 0018).

The adapter is a transport projection. ``tools/list`` and ``tools/call`` re-enter the
same ASGI application in-process with the caller's own bearer and the organization
selected by the connection path, so authentication, tenant policy, agent policy,
risk ceiling, budgets, idempotency and owner validation run exactly as for direct
HTTP. The adapter grants nothing, stores nothing and never logs credentials.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from request_engine.entrypoints.http.mcp_tools import (
    MCP_TOOL_AUDIENCE,
    TENANT_HEADER,
    ToolArgumentsInvalid,
    ToolBinding,
    build_inner_call,
    project_tool,
)

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
DISCOVERY_REFUSED = -32003
MCP_PATH = "/mcp/organizations/{organization_id}"
_CATALOG_PATH = "/v1/operation-catalog"
_NO_STORE = {"Cache-Control": "no-store"}
SERVER_INSTRUCTIONS = (
    "Request Engine exposes this business's authorized operations as tools: parties "
    "(customers/patients), business information, catalog offerings, appointments, "
    "queues and requests. The tool list is filtered to what your credential may "
    "currently do, and Request Engine enforces authority, policy, risk limits and "
    "budgets again on every call; a refusal is returned as a tool error with a "
    "machine-readable code and resolution. Some changes, such as adding staff, are "
    "submitted as proposals that a human must approve; they are not applied "
    "immediately. Tools that change state require an idempotency_key: use a new "
    "unique key for each intended change and reuse the same key only when retrying "
    "that exact change. Read current state (for example a revision) before changing "
    "it, and never invent identifiers."
)


@dataclass(frozen=True, slots=True)
class JsonRpcRequest:
    id: str | int
    method: str
    params: dict[str, object]


@dataclass(frozen=True, slots=True)
class JsonRpcNotification:
    method: str


@dataclass(frozen=True, slots=True)
class JsonRpcFailure:
    code: int
    message: str
    id: str | int | None = None


JsonRpcMessage = JsonRpcRequest | JsonRpcNotification | JsonRpcFailure


def parse_message(raw: bytes) -> JsonRpcMessage | None:
    """Parse one JSON-RPC 2.0 message; ``None`` means a client response (ignored)."""

    try:
        value: object = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return JsonRpcFailure(PARSE_ERROR, "Parse error")
    if isinstance(value, list):
        return JsonRpcFailure(INVALID_REQUEST, "Batch requests are not supported")
    if not isinstance(value, dict):
        return JsonRpcFailure(INVALID_REQUEST, "Invalid Request")
    message = cast(dict[str, object], value)
    raw_id = message.get("id")
    valid_id = isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool)
    request_id = cast(str | int, raw_id) if valid_id else None
    if message.get("jsonrpc") != "2.0":
        return JsonRpcFailure(INVALID_REQUEST, "Invalid Request", request_id)
    method = message.get("method")
    if method is None and ("result" in message or "error" in message):
        return None
    if not isinstance(method, str) or ("id" in message and not valid_id):
        return JsonRpcFailure(INVALID_REQUEST, "Invalid Request", request_id)
    params = message.get("params", {})
    if not isinstance(params, dict):
        return JsonRpcFailure(INVALID_REQUEST, "Invalid Request", request_id)
    if request_id is None:
        return JsonRpcNotification(method)
    return JsonRpcRequest(request_id, method, cast(dict[str, object], params))


def negotiate_protocol_version(requested: object) -> str:
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def _error_body(
    code: int, message: str, request_id: str | int | None, data: object = None
) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _transport_refusal(status: int, code: str, message: str, **headers: str) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": INVALID_REQUEST, "message": message, "data": {"code": code}},
        },
        status_code=status,
        headers={**_NO_STORE, **headers},
    )


class _RpcError(Exception):
    def __init__(self, code: int, message: str, data: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class McpUnauthenticated(Exception):
    """The forwarded bearer was rejected by the runtime authentication boundary."""


class _ToolDiscoveryRefused(Exception):
    def __init__(self, status: int, envelope: object) -> None:
        super().__init__(status)
        self.status = status
        self.envelope = envelope


class _Connection:
    """One MCP HTTP request bound to the caller's own credential and organization."""

    def __init__(self, request: Request, organization_id: UUID, authorization: str) -> None:
        self._app = cast(FastAPI, request.app)
        self._base_url = f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"
        self._headers = {
            "Authorization": authorization,
            TENANT_HEADER: str(organization_id),
            "Accept": "application/json",
        }

    async def _send(
        self,
        method: str,
        path: str,
        *,
        query: tuple[tuple[str, str], ...] = (),
        body: dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers = dict(self._headers)
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        async def execute() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(transport=transport, base_url=self._base_url) as client:
                return await client.request(
                    method, path, params=list(query), json=body, headers=headers
                )

        # A separate task runs the inner request in a copied context so the inner
        # middleware cannot leak or clear task-local actor state of this request.
        response = await asyncio.create_task(execute())
        if response.status_code == 401:
            raise McpUnauthenticated
        return response

    async def tools(self) -> dict[str, ToolBinding]:
        """Project the caller's *current* authorized catalog into MCP tools."""

        response = await self._send("GET", _CATALOG_PATH)
        if response.status_code != 200:
            raise _ToolDiscoveryRefused(response.status_code, _json_or_text(response))
        openapi = cast(dict[str, object], self._app.openapi())
        bindings: dict[str, ToolBinding] = {}
        for item in cast(list[dict[str, Any]], response.json().get("operations", [])):
            name = item.get("tool_name")
            if not isinstance(name, str) or MCP_TOOL_AUDIENCE not in item.get("tool_audiences", ()):
                continue
            binding = project_tool(openapi, str(item.get("openapi_pointer", "")), name)
            if binding is not None and binding.operation_id == item.get("operation_id"):
                bindings.setdefault(name, binding)
        return bindings

    async def call(self, binding: ToolBinding, arguments: Mapping[str, object]) -> object:
        inner = build_inner_call(binding, arguments)
        response = await self._send(
            inner.method,
            inner.path,
            query=inner.query,
            body=inner.body,
            idempotency_key=inner.idempotency_key,
        )
        return _tool_result(response)


def _json_or_text(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text


def _tool_result(response: httpx.Response) -> dict[str, object]:
    payload = _json_or_text(response)
    text = (
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        if not isinstance(payload, str)
        else payload
    )
    result: dict[str, object] = {
        "content": [{"type": "text", "text": text}],
        "isError": response.status_code >= 400,
        "_meta": {
            "request-engine/http-status": response.status_code,
            "request-engine/correlation-id": response.headers.get("X-Correlation-ID"),
        },
    }
    if isinstance(payload, dict):
        result["structuredContent"] = payload
    return result


def _discovery_refusal_result(refused: _ToolDiscoveryRefused) -> dict[str, object]:
    envelope: object = refused.envelope
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(refused.envelope, separators=(",", ":"), ensure_ascii=False),
            }
        ],
        "isError": True,
        **(
            {"structuredContent": cast(dict[str, object], envelope)}
            if isinstance(envelope, dict)
            else {}
        ),
        "_meta": {"request-engine/http-status": refused.status},
    }


async def _dispatch(connection: _Connection, message: JsonRpcRequest, app: FastAPI) -> object:
    if message.method == "initialize":
        return {
            "protocolVersion": negotiate_protocol_version(message.params.get("protocolVersion")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "request-engine", "title": app.title, "version": app.version},
            "instructions": SERVER_INSTRUCTIONS,
        }
    if message.method == "ping":
        return {}
    if message.method == "tools/list":
        try:
            tools = await connection.tools()
        except _ToolDiscoveryRefused as refused:
            raise _RpcError(
                DISCOVERY_REFUSED,
                "Request Engine refused tool discovery for this credential",
                {"http_status": refused.status, "response": refused.envelope},
            ) from None
        return {"tools": [dict(binding.descriptor) for binding in tools.values()]}
    if message.method == "tools/call":
        name = message.params.get("name")
        arguments = message.params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise _RpcError(INVALID_PARAMS, "Invalid params")
        try:
            binding = (await connection.tools()).get(name)
        except _ToolDiscoveryRefused as refused:
            return _discovery_refusal_result(refused)
        if binding is None:
            # Unknown and unauthorized are indistinguishable by design.
            raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        try:
            return await connection.call(binding, cast(dict[str, object], arguments))
        except ToolArgumentsInvalid as invalid:
            raise _RpcError(INVALID_PARAMS, str(invalid)) from None
    raise _RpcError(METHOD_NOT_FOUND, "Method not found")


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    host = request.headers.get("host")
    parts = urlsplit(origin)
    return bool(host) and parts.scheme in {"http", "https"} and parts.netloc == host


def _bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return value


def create_mcp_router() -> APIRouter:
    router = APIRouter()

    async def mcp_post(organization_id: UUID, request: Request) -> Response:
        if not _origin_allowed(request):
            return _transport_refusal(403, "origin_not_allowed", "Cross-origin request rejected")
        authorization = _bearer(request)
        if authorization is None:
            return _transport_refusal(
                401,
                "authentication_required",
                "Bearer authentication required",
                **{"WWW-Authenticate": "Bearer"},
            )
        version = request.headers.get("mcp-protocol-version")
        if version is not None and version not in SUPPORTED_PROTOCOL_VERSIONS:
            return _transport_refusal(
                400, "unsupported_protocol_version", "Unsupported MCP protocol version"
            )
        message = parse_message(await request.body())
        if message is None or isinstance(message, JsonRpcNotification):
            return Response(status_code=202, headers=_NO_STORE)
        if isinstance(message, JsonRpcFailure):
            return JSONResponse(
                _error_body(message.code, message.message, message.id),
                status_code=400,
                headers=_NO_STORE,
            )
        connection = _Connection(request, organization_id, authorization)
        try:
            outcome = await _dispatch(connection, message, cast(FastAPI, request.app))
        except _RpcError as error:
            return JSONResponse(
                _error_body(error.code, error.message, message.id, error.data),
                headers=_NO_STORE,
            )
        except McpUnauthenticated:
            return _transport_refusal(
                401,
                "authentication_required",
                "The bearer credential was not accepted",
                **{"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        return JSONResponse(
            {"jsonrpc": "2.0", "id": message.id, "result": outcome}, headers=_NO_STORE
        )

    async def mcp_get(organization_id: UUID) -> Response:
        del organization_id
        return Response(status_code=405, headers={"Allow": "POST", **_NO_STORE})

    router.add_api_route(MCP_PATH, mcp_post, methods=["POST"], include_in_schema=False)
    router.add_api_route(MCP_PATH, mcp_get, methods=["GET"], include_in_schema=False)
    return router


__all__ = [
    "LATEST_PROTOCOL_VERSION",
    "SERVER_INSTRUCTIONS",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "JsonRpcFailure",
    "JsonRpcNotification",
    "JsonRpcRequest",
    "create_mcp_router",
    "negotiate_protocol_version",
    "parse_message",
]
