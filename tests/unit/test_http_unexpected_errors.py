"""Real ASGI error boundary; composition ports are not native-auth/DB evidence."""

from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.discovery_app import create_discovery_app
from request_engine.entrypoints.http.discovery_availability_app import (
    create_discovery_availability_app,
)
from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.platform.security.http import request_correlation_id
from request_engine.platform.security.password_work import PasswordWorkCapacityExceeded

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.contract]


def _composed_app(control: bool) -> FastAPI:
    # Neither probe reaches these composition ports; DB/auth behavior is excluded.
    factory = Mock()
    if control:
        return create_platform_control_app(
            auth_session_factory=factory,
            platform_read_session_factory=factory,
            platform_write_session_factory=factory,
            native_authority_id=uuid4(),
            webauthn_decoy_key=b"a" * 32,
        )
    return create_app(
        session_factory=factory,
        actor_resolver=Mock(),
        appointment_option_signing_key=b"a" * 32,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("database_error", [False, True])
async def test_unknown_failure_is_sanitized_correlated_and_not_blindly_retryable(
    control: bool, database_error: bool
) -> None:
    app = _composed_app(control)
    admitted: list[UUID] = []
    visible_effects: list[str] = []
    confidential = "credential=secret-marker SQL SELECT private_record"

    async def fail(request: Request) -> None:
        admitted.append(request_correlation_id(request))
        # Transport failure cannot prove rollback of an already performed effect.
        visible_effects.append("operation reached")
        if database_error:
            raise OperationalError("SELECT private_record", {}, RuntimeError(confidential))
        raise RuntimeError(confidential)

    app.add_api_route("/error-boundary-probe", fail, methods=["POST"])
    spoofed = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post("/error-boundary-probe", headers={"X-Correlation-ID": spoofed})
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    assert UUID(response.headers["x-correlation-id"]) == admitted[0]
    assert response.headers["x-correlation-id"] != spoofed
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred; the operation outcome may be uncertain",
        "retryable": False,
        "resolution": "operator_intervention",
        "details": {},
    }
    assert "secret-marker" not in response.text
    assert "SELECT" not in response.text
    assert "Traceback" not in response.text
    assert visible_effects == ["operation reached"]


@pytest.mark.asyncio
@pytest.mark.parametrize("control", [False, True])
async def test_fallback_preserves_specific_handlers_http_errors_and_validation(
    control: bool,
) -> None:
    app = _composed_app(control)

    class OwnerConflict(Exception):
        pass

    async def owner_handler(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "owner_conflict", "revision": 17}},
            headers={"X-Owner-Revision": "17"},
        )

    app.add_exception_handler(OwnerConflict, owner_handler)

    async def owner_error() -> None:
        raise OwnerConflict()

    async def http_error() -> None:
        raise HTTPException(status_code=404, detail="Not available")

    async def validation(count: int) -> dict[str, int]:
        return {"count": count}

    app.add_api_route("/owner-error-probe", owner_error, methods=["GET"])
    app.add_api_route("/http-error-probe", http_error, methods=["GET"])
    app.add_api_route("/validation-error-probe", validation, methods=["GET"])
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        owner = await client.get("/owner-error-probe")
        missing = await client.get("/http-error-probe")
        invalid = await client.get("/validation-error-probe", params={"count": "not-an-int"})
    assert owner.status_code == 409
    assert owner.json() == {"error": {"code": "owner_conflict", "revision": 17}}
    assert owner.headers["x-owner-revision"] == "17"
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert missing.json()["error"]["code"] != "internal_error"
    assert invalid.json()["error"]["code"] != "internal_error"
    for response in (owner, missing, invalid):
        assert UUID(response.headers["x-correlation-id"])
        if control:
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("control", [False, True])
def test_fallback_schema_is_explicit_without_overwriting_owner_500(control: bool) -> None:
    app = _composed_app(control)

    class OwnerFailureView(BaseModel):
        diagnostic_reference: str

    async def plain() -> dict[str, str]:
        return {"state": "ok"}

    app.add_api_route("/schema-plain-probe", plain, methods=["GET"])
    app.add_api_route(
        "/schema-owner-probe",
        plain,
        methods=["GET"],
        responses={500: {"model": OwnerFailureView, "description": "Owner configuration failure"}},
    )
    schema = app.openapi()
    fallback = schema["paths"]["/schema-plain-probe"]["get"]["responses"]["500"]
    assert fallback["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
    assert "does not prove rollback" in fallback["description"]
    assert "retryable=false" in fallback["description"]
    assert "X-Correlation-ID" in fallback["headers"]
    owner = schema["paths"]["/schema-owner-probe"]["get"]["responses"]["500"]
    assert owner["description"] == "Owner configuration failure"
    assert owner["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/OwnerFailureView"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("control", [False, True])
async def test_password_work_busy_is_distinct_from_uncertain_server_failure(control: bool) -> None:
    app = _composed_app(control)

    async def busy() -> None:
        raise PasswordWorkCapacityExceeded("No credential processing admitted")

    app.add_api_route("/password-work-probe", busy, methods=["POST"])
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post("/password-work-probe")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "password_work_capacity_exceeded"
    assert response.json()["error"]["retryable"] is True
    assert response.json()["error"]["resolution"] == "retry_same_request"
    assert response.headers["retry-after"] == "1"
    assert response.headers["cache-control"] == "no-store"
    assert UUID(response.headers["x-correlation-id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["discovery", "availability", "operations"])
@pytest.mark.parametrize("busy", [False, True])
async def test_subset_factories_install_same_technical_error_contract(
    surface: str, busy: bool
) -> None:
    factory = Mock()
    if surface == "discovery":
        remote = Mock()
        remote.trust_boundary = "remote"
        app = create_discovery_app(
            candidate_reader=Mock(),
            slot_reader=remote,
            handoff_issuer=Mock(),
            actor_resolver=Mock(),
        )
    elif surface == "availability":
        app = create_discovery_availability_app(
            domain_session_factory=factory, actor_resolver=Mock()
        )
    else:
        app = create_operational_app(session_factory=factory, actor_resolver=Mock())

    async def fail() -> None:
        if busy:
            raise PasswordWorkCapacityExceeded("credential secret must not appear")
        raise RuntimeError("SQL secret must not appear")

    app.add_api_route("/subset-error-probe", fail, methods=["POST"])
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post("/subset-error-probe")
    assert response.status_code == (503 if busy else 500)
    assert response.json()["error"]["code"] == (
        "password_work_capacity_exceeded" if busy else "internal_error"
    )
    assert response.json()["error"]["retryable"] is busy
    assert response.json()["error"]["resolution"] == (
        "retry_same_request" if busy else "operator_intervention"
    )
    assert "secret" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert UUID(response.headers["x-correlation-id"])
    assert app.openapi()["paths"]["/subset-error-probe"]["post"]["responses"]["500"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ErrorEnvelope"}
