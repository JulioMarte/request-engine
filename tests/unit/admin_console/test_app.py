import re
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')

_OPENAPI: dict[str, Any] = {
    "components": {
        "schemas": {
            "CreateThing": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
            }
        }
    },
    "paths": {
        "/v1/platform/things": {
            "post": {
                "operationId": "thing_create",
                "summary": "Create thing",
                "tags": ["Platform things"],
                "x-request-engine-capability": "thing.write",
                "x-request-engine-kind": "command",
                "x-request-engine-idempotency": "required",
                "x-request-engine-exposure": "operator",
                "x-request-engine-owner": "catalog",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/CreateThing"}}
                    }
                },
            }
        }
    },
}


class FakeControl:
    """Structural stand-in for ControlPlaneClient in HTTP-level tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        setup_bearer: str | None = None,
        json_body: object | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ControlResponse:
        self.calls.append(f"{method} {path}")
        if method == "POST" and path == "/auth/native/sessions":
            return ControlResponse(
                200,
                {"access_token": "test-token", "token_type": "Bearer", "expires_at": "2999-01-01"},
                {},
            )
        if method == "DELETE" and path == "/auth/native/sessions/current":
            return ControlResponse(204, None, {})
        if method == "GET" and path == "/v1/platform/readiness":
            return ControlResponse(200, {"status": "ready"}, {})
        if method == "GET" and path == "/health/live":
            return ControlResponse(200, {"status": "live"}, {})
        if method == "POST" and path == "/v1/setup/sessions":
            return ControlResponse(
                201,
                {"setup_session_id": "sid", "token": "setup-token", "expires_at": "2999-01-01"},
                {},
            )
        if method == "GET" and path == "/v1/setup":
            return ControlResponse(200, {"setup_required": True}, {})
        if method == "POST" and path == "/v1/platform/things":
            return ControlResponse(201, {"id": "created"}, {})
        return ControlResponse(
            404,
            {"error": {"code": "not_found", "message": "unknown", "retryable": False}},
            {},
        )

    async def openapi(self) -> dict[str, Any]:
        return _OPENAPI

    async def aclose(self) -> None:
        return None


def _settings() -> AdminConsoleSettings:
    return AdminConsoleSettings(
        control_api_base_url="http://control:8001",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        follow_redirects=False,
    )


@pytest.mark.asyncio
async def test_login_page_renders_with_security_headers() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_dashboard_requires_session() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_password_login_sets_cookie_and_opens_dashboard() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        login = await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        assert login.status_code == 303
        assert login.headers["location"] == "/"
        assert "re_admin_console" in client.cookies
        dashboard = await client.get("/")
        assert dashboard.status_code == 200
        assert "Dashboard" in dashboard.text


@pytest.mark.asyncio
async def test_login_rejected_when_control_denies() -> None:
    class Denying(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if method == "POST" and path == "/auth/native/sessions":
                return ControlResponse(401, {"error": {"code": "invalid", "message": "nope"}}, {})
            return await super().request(method, path, **kwargs)

    app = create_admin_console_app(_settings(), client=Denying())
    async with _client(app) as client:
        response = await client.post("/login", data={"login_handle": "owner", "password": "bad"})
    assert response.status_code == 401
    assert "nope" in response.text


@pytest.mark.asyncio
async def test_setup_session_sets_setup_cookie() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.post("/setup/session")
    assert response.status_code == 303
    assert "re_admin_setup" in response.cookies


@pytest.mark.asyncio
async def test_health_endpoints() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        assert (await client.get("/health/live")).status_code == 200
        assert (await client.get("/health/ready")).status_code == 200


@pytest.mark.asyncio
async def test_operator_docs_are_disabled() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404


@pytest.mark.asyncio
async def test_operations_catalog_renders_and_executes() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        listing = await client.get("/operations")
        assert listing.status_code == 200
        assert "thing_create" in listing.text
        detail = await client.get("/operations/thing_create")
        assert detail.status_code == 200
        match = _CSRF_RE.search(detail.text)
        assert match is not None
        executed = await client.post(
            "/operations/thing_create",
            data={"csrf_token": match.group(1), "name": "widget", "count": "2"},
        )
        assert executed.status_code == 200
        assert "created" in executed.text


@pytest.mark.asyncio
async def test_operations_reject_bad_csrf() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        denied = await client.post(
            "/operations/thing_create",
            data={"csrf_token": "wrong", "name": "widget"},
        )
        assert denied.status_code == 200
        assert "csrf_failed" in denied.text


@pytest.mark.asyncio
async def test_setup_wizard_renders() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.get("/setup")
        assert response.status_code == 200
        assert "First-run setup" in response.text


@pytest.mark.asyncio
async def test_login_page_separates_passkey_from_password() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.get("/login")
    assert response.status_code == 200
    assert "Continue with passkey" in response.text
    assert "No password or username needed" in response.text
    assert 'id="passkey_handle"' not in response.text


@pytest.mark.asyncio
async def test_request_id_header_present() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.get("/login")
    assert response.headers.get("x-request-id")


@pytest.mark.asyncio
async def test_diagnostics_requires_session_then_renders() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        assert (await client.get("/diagnostics")).status_code == 303
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get("/diagnostics")
        assert page.status_code == 200
        assert "Diagnostics" in page.text
        payload = await client.get("/diagnostics/errors.json")
        assert payload.status_code == 200
        assert payload.json()["metrics"]["control_calls"] >= 1


@pytest.mark.asyncio
async def test_unhandled_error_renders_error_page_and_is_tracked() -> None:
    class BrokenCatalog(FakeControl):
        async def openapi(self) -> dict[str, Any]:
            raise RuntimeError("openapi boom")

    app = create_admin_console_app(_settings(), client=BrokenCatalog())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/operations/thing_create")
        assert response.status_code == 500
        assert "Something went wrong" in response.text
        assert response.headers.get("x-request-id")
        tracked = await client.get("/diagnostics/errors.json")
        assert tracked.status_code == 200
        errors = tracked.json()["errors"]
        assert any(event["kind"] == "unhandled_exception" for event in errors)


@pytest.mark.asyncio
async def test_setup_page_degrades_when_control_unreachable() -> None:
    class Unreachable(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            raise httpx.ConnectError("mock down")

    app = create_admin_console_app(_settings(), client=Unreachable())
    async with _client(app) as client:
        response = await client.get("/setup")
    assert response.status_code == 200
    assert "First-run setup" in response.text
    assert "control plane unreachable" in response.text


@pytest.mark.asyncio
async def test_dashboard_does_not_execute_remote_deployment_plan() -> None:
    control = FakeControl()
    app = create_admin_console_app(_settings(), client=control)
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/")

    assert response.status_code == 200
    assert "GET /v1/platform/deployment-recovery:plan" not in control.calls


@pytest.mark.asyncio
async def test_dashboard_degrades_on_non_object_control_error_body() -> None:
    class PlainTextFailure(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if method == "GET" and path == "/v1/platform/observability":
                return ControlResponse(500, "Internal Server Error", {})
            return await super().request(method, path, **kwargs)

    app = create_admin_console_app(_settings(), client=PlainTextFailure())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/")

    assert response.status_code == 200
    assert "control plane returned HTTP 500" in response.text
    assert "Something went wrong" not in response.text


@pytest.mark.asyncio
async def test_dashboard_degrades_when_control_unreachable() -> None:
    class PartlyUnreachable(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if path == "/health/live" or path == "/auth/native/sessions":
                return await super().request(method, path, **kwargs)
            raise httpx.ConnectError("mock down")

        async def openapi(self) -> dict[str, Any]:
            raise httpx.ConnectError("mock down")

    app = create_admin_console_app(_settings(), client=PartlyUnreachable())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/")
    assert response.status_code == 200
    assert "control plane unreachable" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["drifted", "missing"])
async def test_dashboard_flags_reported_recovery_readiness_failure(state: str) -> None:
    class DeploymentState(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if path == "/v1/platform/observability":
                return ControlResponse(200, {"alerts": []}, {})
            if path == "/v1/platform/readiness":
                return ControlResponse(200, {"restore_drill": state}, {})
            return await super().request(method, path, **kwargs)

    app = create_admin_console_app(_settings(), client=DeploymentState())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/")
    assert response.status_code == 200
    assert "Some operational checks need attention" in response.text
    assert "Restore drill" in response.text
    assert f"Current reported state: {state}" in response.text


@pytest.mark.asyncio
async def test_dashboard_does_not_show_internal_coverage_or_empty_activity() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/")
    assert "Admin coverage" not in response.text
    assert "Recent operational activity" not in response.text
    assert "Sign out" in response.text


@pytest.mark.asyncio
async def test_dashboard_does_not_claim_health_from_incomplete_success_payload() -> None:
    class IncompleteReadiness(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if path == "/v1/platform/readiness":
                return ControlResponse(200, {}, {})
            if path == "/v1/platform/observability":
                return ControlResponse(200, {"alerts": []}, {})
            if path == "/v1/platform/deployment-recovery:plan":
                return ControlResponse(200, {"state": "in_sync"}, {})
            return await super().request(method, path, **kwargs)

    app = create_admin_console_app(_settings(), client=IncompleteReadiness())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/")
    assert "Operational status is incomplete" in response.text
    assert "Core operational checks are healthy" not in response.text


@pytest.mark.asyncio
async def test_logout_clears_browser_session_when_upstream_revocation_fails() -> None:
    class BrokenLogout(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if method == "DELETE" and path == "/auth/native/sessions/current":
                raise httpx.ConnectError("control unavailable during logout")
            return await super().request(method, path, **kwargs)

    app = create_admin_console_app(_settings(), client=BrokenLogout())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        assert "re_admin_console" in client.cookies
        response = await client.post("/logout")

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "re_admin_console" not in client.cookies
