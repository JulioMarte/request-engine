"""OpenAPI reflects actual composed bearer boundaries, not audience authority."""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.entrypoints.http.native_auth import create_native_auth_router
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.modules.tenancy.api.self_organizations import create_self_organization_router
from request_engine.platform.http.authentication_schema import install_authentication_schema
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import NativeSessionAuthenticator

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.contract]


def _app() -> FastAPI:
    app = FastAPI()
    add_global_error_handlers(app)
    authenticator = Mock(spec=NativeSessionAuthenticator)
    authenticator.authenticate = AsyncMock(side_effect=AuthenticationRequired())
    app.include_router(
        create_native_auth_router(
            service=Mock(spec=NativeHumanAuthService),
            authenticator=authenticator,
            identity_authority_id=uuid4(),
        )
    )
    install_authentication_schema(app, scheme_name="SubjectBearer", description="Configured bearer")
    return app


@pytest.mark.asyncio
async def test_native_session_schema_matches_anonymous_transport_rejection() -> None:
    app = _app()
    operation = app.openapi()["paths"]["/auth/native/sessions/current"]["get"]
    assert operation["security"] == [{"NativeSessionBearer": []}]
    assert "401" in operation["responses"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/native/sessions/current")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.headers["cache-control"] == "no-store"


def test_login_password_and_recovery_consumers_remain_explicitly_public() -> None:
    paths = _app().openapi()["paths"]
    for path, method in (
        ("/auth/native/sessions", "post"),
        ("/auth/native/password", "put"),
        ("/auth/native/password:recover", "post"),
        ("/auth/native/identities", "post"),
    ):
        assert paths[path][method]["security"] == []


def test_capability_authentication_projects_configured_provider_neutral_scheme() -> None:
    app = FastAPI()

    async def command() -> dict[str, str]:
        return {"status": "ok"}

    app.add_api_route(
        "/fixture",
        command,
        methods=["POST"],
        operation_id="fixtureCommand",
        openapi_extra={"x-request-engine-capability": "fixture.manage"},
    )
    install_authentication_schema(
        app, scheme_name="SubjectBearer", description="OIDC or workload", tenant_context=True
    )
    schema = app.openapi()
    operation = schema["paths"]["/fixture"]["post"]
    assert operation["security"] == [{"SubjectBearer": []}]
    assert "401" in operation["responses"] and "403" in operation["responses"]
    assert "never authority" in operation["x-request-engine-tenant-context"]
    assert any(
        parameter["name"] == "X-RE-Organization-ID" and parameter["required"]
        for parameter in operation["parameters"]
    )
    assert schema["components"]["securitySchemes"]["SubjectBearer"]["scheme"] == "bearer"


def test_self_organization_discovery_authenticates_subject_without_tenant_selector() -> None:
    app = FastAPI()
    app.include_router(create_self_organization_router(subject_resolver=Mock(), reader=Mock()))
    install_authentication_schema(
        app, scheme_name="SubjectBearer", description="Configured bearer", tenant_context=True
    )
    operation = app.openapi()["paths"]["/v1/me/organizations"]["get"]
    assert operation["security"] == [{"SubjectBearer": []}]
    assert "401" in operation["responses"]
    assert "x-request-engine-tenant-context" not in operation
    assert not any(
        parameter["name"] == "X-RE-Organization-ID" for parameter in operation.get("parameters", [])
    )


def test_pretenant_invitation_ceremonies_require_native_session_without_tenant_header() -> None:
    factory = Mock()
    app = create_app(
        session_factory=factory,
        actor_resolver=Mock(),
        subject_resolver=Mock(),
        appointment_option_signing_key=b"a" * 32,
    )
    schema = app.openapi()
    for action in ("preview", "accept"):
        operation = schema["paths"][f"/v1/staff/invitations/{{invitation_id}}:{action}"]["post"]
        assert operation["security"] == [{"NativeSessionBearer": []}]
        assert "401" in operation["responses"]
        assert not any(
            parameter["name"] == "X-RE-Organization-ID"
            for parameter in operation.get("parameters", [])
        )


@pytest.mark.parametrize("control", [False, True])
def test_composed_surface_declares_authentication_for_every_capability(control: bool) -> None:
    factory = Mock()
    if control:
        app = create_platform_control_app(
            auth_session_factory=factory,
            platform_read_session_factory=factory,
            platform_write_session_factory=factory,
            native_authority_id=uuid4(),
            webauthn_decoy_key=b"a" * 32,
        )
    else:
        app = create_app(
            session_factory=factory, actor_resolver=Mock(), appointment_option_signing_key=b"a" * 32
        )
    operations = [
        cast(dict[str, Any], operation)
        for path in app.openapi()["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict)
        and cast(dict[str, Any], operation).get("x-request-engine-capability")
    ]
    assert operations
    assert all(operation.get("security") for operation in operations)
    assert all(
        "401" in operation["responses"] and "403" in operation["responses"]
        for operation in operations
    )
