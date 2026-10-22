import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute
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
        if method == "GET" and path == "/health/ready":
            return ControlResponse(200, {"status": "ready"}, {})
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


def test_factory_registers_each_browser_method_and_path_once() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    destinations = Counter(
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    )
    assert all(count == 1 for count in destinations.values()), destinations
    assert destinations[("/owner-invitations/enroll", "GET")] == 1
    assert destinations[("/account/security", "GET")] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("upstream_status", [200, 503])
async def test_dashboard_reports_api_counters_without_fabricated_time_window(
    upstream_status: int,
) -> None:
    class MetricsControl(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if path == "/v1/platform/observability":
                self.calls.append(f"{method} {path}")
                return ControlResponse(
                    upstream_status,
                    {
                        "validation_success_total": 1234567,
                        "validation_failure_total": -1,
                        "provider_test_failures_total": True,
                        "alerts": [],
                    },
                    {},
                )
            return await super().request(method, path, **kwargs)

    api = MetricsControl()
    async with _client(create_admin_console_app(_settings(), client=api)) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get("/")
    assert page.status_code == 200
    assert "desde su último reinicio" in page.text
    assert "No son totales de 24 horas" in page.text
    assert ("1234567" in page.text) is (upstream_status == 200)
    assert "<strong>-1</strong>" not in page.text
    assert "<strong>True</strong>" not in page.text
    assert "<strong>—</strong>" in page.text


def _settings() -> AdminConsoleSettings:
    return AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control:8001",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
        follow_redirects=False,
    )


@pytest.mark.asyncio
async def test_login_page_renders_with_security_headers() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.get("/login")
    assert response.status_code == 200
    assert "Iniciar sesión" in response.text
    assert '<html lang="es">' in response.text
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
        assert "Panel / Resumen" in dashboard.text


@pytest.mark.asyncio
async def test_dashboard_people_shortcut_selects_own_context_without_tenant_calls() -> None:
    upstream = FakeControl()
    app = create_admin_console_app(_settings(), client=upstream)
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        upstream.calls.clear()
        dashboard = await client.get("/")
    assert dashboard.status_code == 200
    assert re.search(
        r'<a href="/my-organizations">(?:(?!</a>).)*?<strong>Personas y permisos</strong>',
        dashboard.text,
        re.DOTALL,
    )
    assert "Elija su negocio, invite personas y revise los accesos" in dashboard.text
    assert all("/v1/staff" not in call for call in upstream.calls)
    assert all(not call.startswith(("POST ", "PUT ", "DELETE ")) for call in upstream.calls)


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
    # The denial is explained in Spanish; the upstream English message never leaks.
    assert "El correo, el usuario o la contraseña no son correctos" in response.text
    assert "nope" not in response.text


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
        assert "Configuración inicial" in response.text


@pytest.mark.asyncio
async def test_setup_can_skip_optional_passkey_and_project_recovery_then_claim() -> None:
    class PasswordSetup(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if method == "POST" and path in {
                "/v1/setup/native-identity",
                "/v1/setup/recovery-codes",
                "/v1/setup:finalize",
            }:
                self.calls.append(f"{method} {path}")
                assert kwargs["setup_bearer"] == "setup-token"
                if path == "/v1/setup/native-identity":
                    return ControlResponse(204, None, {})
                if path == "/v1/setup/recovery-codes":
                    return ControlResponse(201, {"codes": ["synthetic-one-time-recovery"]}, {})
                return ControlResponse(201, {"instance_id": "claimed-instance"}, {})
            return await super().request(method, path, **kwargs)

    control = PasswordSetup()
    async with _client(create_admin_console_app(_settings(), client=control)) as client:
        await client.post("/setup/session")
        identity = await client.get("/setup?step=identity")
        csrf = _CSRF_RE.search(identity.text)
        assert csrf is not None
        submitted = await client.post(
            "/setup/identity",
            data={
                "csrf_token": csrf.group(1),
                "login_handle": "owner",
                "password": "owner-password",
            },
        )
        passkey = await client.get(submitted.headers["location"])
        assert 'href="/setup?step=recovery"' in passkey.text
        assert "Continuar sin llave de acceso" in passkey.text
        recovery = await client.get("/setup?step=recovery")
        assert 'action="/setup/recovery-codes"' in recovery.text
        codes = await client.post("/setup/recovery-codes")
        assert "synthetic-one-time-recovery" in codes.text
        assert 'action="/setup/finalize"' in codes.text
        finished = await client.post(
            "/setup/finalize",
            data={"csrf_token": csrf.group(1), "claim_provenance": "browser-setup"},
        )
        assert finished.status_code == 200
        assert "Instancia reclamada correctamente" in finished.text
        assert not any("webauthn" in path for path in control.calls)
        assert control.calls.index("POST /v1/setup/recovery-codes") < control.calls.index(
            "POST /v1/setup:finalize"
        )


@pytest.mark.asyncio
async def test_setup_password_policy_error_keeps_identity_step_and_safe_feedback() -> None:
    class PasswordRejected(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if method == "POST" and path == "/v1/setup/native-identity":
                self.calls.append(f"{method} {path}")
                return ControlResponse(
                    422,
                    {
                        "error": {
                            "code": "password_policy_violation",
                            "message": (
                                "password must be valid UTF-8 with at least 12 characters "
                                "and at most 1024 bytes"
                            ),
                            "retryable": False,
                        }
                    },
                    {},
                )
            return await super().request(method, path, **kwargs)

    control = PasswordRejected()
    app = create_admin_console_app(_settings(), client=control)
    async with _client(app) as client:
        started = await client.post("/setup/session")
        assert started.status_code == 303
        identity = await client.get(started.headers["location"])
        csrf = _CSRF_RE.search(identity.text)
        assert csrf is not None
        rejected = await client.post(
            "/setup/identity",
            data={
                "csrf_token": csrf.group(1),
                "login_handle": "owner@example.test",
                "password": "tiny-pw",
            },
        )
        assert rejected.status_code == 303
        assert "step=identity" in rejected.headers["location"]
        assert "tiny-pw" not in rejected.headers["location"]
        feedback = await client.get(rejected.headers["location"])
        assert feedback.status_code == 200
        assert "al menos 12 caracteres" in feedback.text
        assert "como máximo 1024 bytes" in feedback.text
        assert "password must be valid UTF-8" not in feedback.text
        assert 'action="/setup/identity"' in feedback.text
        assert 'minlength="12"' in feedback.text
        assert "tiny-pw" not in feedback.text
        assert control.calls.count("POST /v1/setup/native-identity") == 1


@pytest.mark.asyncio
async def test_login_page_separates_passkey_from_password() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        response = await client.get("/login")
    assert response.status_code == 200
    assert "Continuar con una llave de acceso" in response.text
    assert "No necesita contraseña ni usuario" in response.text
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
        assert "Diagnóstico" in page.text
        payload = await client.get("/diagnostics/errors.json")
        assert payload.status_code == 200
        assert payload.json()["metrics"]["control_calls"] >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [False, True])
async def test_unhandled_error_renders_error_page_and_is_tracked(
    debug: bool, capfd: pytest.CaptureFixture[str]
) -> None:
    class BrokenCatalog(FakeControl):
        async def openapi(self) -> dict[str, Any]:
            raise RuntimeError("private-password-canary")

    settings = _settings().model_copy(update={"debug": debug})
    app = create_admin_console_app(settings, client=BrokenCatalog())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/operations/thing_create")
        assert response.status_code == 500
        assert "Ocurrió un error inesperado" in response.text
        assert response.headers.get("x-request-id")
        tracked = await client.get("/diagnostics/errors.json")
        assert tracked.status_code == 200
        errors = tracked.json()["errors"]
        assert any(event["kind"] == "unhandled_exception" for event in errors)
        assert "private-password-canary" not in response.text + tracked.text
    assert "private-password-canary" not in capfd.readouterr().err


@pytest.mark.asyncio
async def test_setup_page_degrades_when_control_unreachable() -> None:
    class Unreachable(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            raise httpx.ConnectError("mock down")

    app = create_admin_console_app(_settings(), client=Unreachable())
    async with _client(app) as client:
        response = await client.get("/setup")
    assert response.status_code == 200
    assert "Configuración inicial" in response.text
    assert "No se pudo conectar con el servidor de control" in response.text


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
    assert "el plano de control respondió HTTP 500" in response.text
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
    assert "no se pudo conectar con el plano de control" in response.text


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
    assert "Algunas verificaciones operativas requieren atención" in response.text
    assert "Prueba de restauración" in response.text
    assert f"Estado reportado actualmente: {state}" in response.text


@pytest.mark.asyncio
async def test_dashboard_does_not_show_internal_coverage_or_empty_activity() -> None:
    app = create_admin_console_app(_settings(), client=FakeControl())
    async with _client(app) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get("/")
    assert "Admin coverage" not in response.text
    assert "Recent operational activity" not in response.text
    assert "Cerrar sesión" in response.text


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
    assert "El estado operativo está incompleto" in response.text
    assert "Las verificaciones operativas principales están bien" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("telemetry", [{}, {"alerts": None}, {"alerts": {}}, {"alerts": [None]}])
async def test_dashboard_missing_or_malformed_alerts_never_claim_health(
    telemetry: dict[str, Any],
) -> None:
    class ReportedChecks(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if path == "/v1/platform/readiness":
                return ControlResponse(
                    200,
                    {
                        "secret_store": "configured",
                        "recovery_delivery_source": "managed",
                        "backup_evidence": "verified",
                        "restore_drill": "verified",
                        "clone_fence": "fenced",
                    },
                    {},
                )
            if path == "/v1/platform/observability":
                return ControlResponse(200, telemetry, {})
            return await super().request(method, path, **kwargs)

    async with _client(create_admin_console_app(_settings(), client=ReportedChecks())) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get("/")
    assert page.status_code == 200
    assert "El estado operativo está incompleto" in page.text
    assert "Las verificaciones están incompletas" in page.text
    assert "Las verificaciones operativas principales están bien" not in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize("fence", ["fenced", "open", []])
async def test_dashboard_interprets_canonical_readiness_and_refreshes_only_reads(
    fence: Any,
) -> None:
    class ActualShape(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            self.calls.append(f"{method} {path}")
            if path == "/v1/platform/readiness":
                return ControlResponse(
                    200,
                    {
                        "secret_store": "configured",
                        "recovery_delivery_source": "managed",
                        "backup_evidence": "verified",
                        "restore_drill": "verified",
                        "clone_fence": fence,
                    },
                    {},
                )
            if path == "/v1/platform/observability":
                return ControlResponse(
                    200,
                    {
                        "alerts": [],
                        "validation_success_total": 0,
                        "validation_failure_total": 0,
                        "provider_test_failures_total": 0,
                        "secret_backend_failures_total": 0,
                    },
                    {},
                )
            return await super().request(method, path, **kwargs)

    api = ActualShape()
    async with _client(create_admin_console_app(_settings(), client=api)) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        api.calls.clear()
        page = await client.get("/")
        assert page.status_code == 200
        healthy = "Las verificaciones operativas principales están bien"
        assert (healthy in page.text) is (fence == "fenced")
        assert 'datetime="' in page.text
        assert "Evidencia de preparación reportada" in page.text
        assert "certificación de producción" in page.text
    assert api.calls == ["GET /v1/platform/readiness", "GET /v1/platform/observability"]


@pytest.mark.asyncio
async def test_dashboard_expired_upstream_session_clears_local_cookie() -> None:
    class RevokedSession(FakeControl):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if path == "/v1/platform/readiness":
                return ControlResponse(401, {"error": {"code": "unauthorized"}}, {})
            return await super().request(method, path, **kwargs)

    async with _client(create_admin_console_app(_settings(), client=RevokedSession())) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get("/")
        assert page.status_code == 303
        assert page.headers["location"] == "/login"
        assert _settings().session_cookie_name not in client.cookies


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
        old_cookie = client.cookies.get("re_admin_console")
        response = await client.post("/logout")
        replay = await client.get("/", headers={"Cookie": f"re_admin_console={old_cookie}"})

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert "re_admin_console" not in client.cookies
    assert replay.status_code == 303
    assert replay.headers["location"] == "/login"
