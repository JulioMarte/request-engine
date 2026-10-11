"""Owner HTTP schema and trusted read context; no PostgreSQL proof is claimed here."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.requests.api.admin_router import create_administration_router
from request_engine.modules.requests.api.errors import request_error_handler
from request_engine.modules.requests.api.router import create_router
from request_engine.modules.requests.application.errors import RequestError
from request_engine.modules.requests.application.queries.admin_reads import RequestInboxItem
from request_engine.platform.http.authentication_schema import install_authentication_schema
from request_engine.platform.security.context import ActorContext

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _app() -> tuple[FastAPI, Mock, ActorContext]:
    app = FastAPI()
    add_global_error_handlers(app)
    app.add_exception_handler(RequestError, request_error_handler)
    current = ActorContext(
        uuid4(), uuid4(), frozenset({"requests.read_definitions", "requests.read_inbox"})
    )
    resolver = Mock(resolve_actor=AsyncMock(return_value=current))
    reader = Mock(
        list_definitions=AsyncMock(return_value=()),
        get_definition=AsyncMock(return_value=None),
        list_inbox=AsyncMock(return_value=()),
    )
    app.include_router(create_administration_router(Mock(), reader, resolver))
    install_authentication_schema(
        app, scheme_name="SubjectBearer", description="Composed subject", tenant_context=True
    )
    return app, reader, current


def test_owner_openapi_errors_are_truthful_for_each_administration_operation() -> None:
    app, _, _ = _app()
    operations = {
        operation["operationId"]: operation
        for path in app.openapi()["paths"].values()
        for operation in path.values()
    }
    expected = {
        "request_definition_create": {"409", "422"},
        "request_definition_version_publish": {"404", "409", "422"},
        "request_definition_set_active": {"404", "409", "422"},
        "request_definitions_list": {"422"},
        "request_definition_read": {"404", "422"},
        "requests_list_inbox": {"422"},
    }
    for name, errors in expected.items():
        operation = operations[name]
        assert set(operation["responses"]) & {"404", "409", "422"} == errors
        for code in errors | {"401", "403"}:
            assert operation["responses"][code]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorEnvelope"
            }
        assert operation["security"] == [{"SubjectBearer": []}]
        tenant = next(p for p in operation["parameters"] if p["name"] == "X-RE-Organization-ID")
        assert tenant["in"] == "header" and tenant["required"]


def test_public_lifecycle_errors_use_owner_envelopes_without_exposing_internal_commands() -> None:
    app, _, _ = _app()
    router = create_router(
        create_handler=Mock(),
        record_result_handler=Mock(),
        complete_handler=Mock(),
        cancel_handler=Mock(),
        fail_handler=Mock(),
        reader=Mock(),
        definition_resolver=Mock(),
        actor_resolver=Mock(),
        include_internal=True,
    )
    app.include_router(router)
    schema = app.openapi()
    for path, method, codes in (
        ("/v1/requests/definitions/{request_key}/submit", "post", {"404", "409", "422"}),
        ("/v1/requests/{request_id}", "get", {"404", "422"}),
        ("/v1/requests/{request_id}/cancel", "post", {"404", "409", "422"}),
    ):
        responses = schema["paths"][path][method]["responses"]
        assert set(responses) & {"404", "409", "422"} == codes
        for code in codes:
            assert responses[code]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorEnvelope"
            }
    for command in ("result", "complete", "fail"):
        path = f"/v1/requests/{{request_id}}/{command}"
        assert path not in schema["paths"]
        route = next(
            route for route in router.routes if isinstance(route, APIRoute) and route.path == path
        )
        assert {404, 409, 422}.issubset(route.responses)
        assert all(
            route.responses[code]["model"].__name__ == "ErrorEnvelope" for code in (404, 409, 422)
        )


@pytest.mark.asyncio
async def test_inbox_exposes_exact_schema_link_and_reads_use_trusted_principal() -> None:
    app, reader, current = _app()
    item = RequestInboxItem(
        uuid4(), uuid4(), uuid4(), "contact", 1, None, None, "open", 1, datetime.now(UTC)
    )
    reader.list_inbox.return_value = (item,)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/requests")
        assert response.status_code == 200, response.text
        value = response.json()["items"][0]
        assert value["definition_id"] == str(item.definition_id)
        assert value["request_key"] == "contact" and value["definition_version"] == 1
        assert value["definition_version_id"] == str(item.definition_version_id)
        assert "payload" not in value and "result_payload" not in value
        reader.list_inbox.assert_awaited_once_with(
            current.organization_id,
            principal_id=current.principal_id,
            limit=51,
            status=None,
            after_id=None,
            after_created_at=None,
        )
        await client.get("/v1/request-definitions")
        reader.list_definitions.assert_awaited_once_with(
            current.organization_id, principal_id=current.principal_id, limit=51, after_id=None
        )
        missing = await client.get(f"/v1/request-definitions/{item.definition_id}?version=1")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "request_definition_not_found"
        reader.get_definition.assert_awaited_once_with(
            current.organization_id, item.definition_id, 1, principal_id=current.principal_id
        )
        invalid = await client.get("/v1/requests?limit=0")
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "validation_failed"
