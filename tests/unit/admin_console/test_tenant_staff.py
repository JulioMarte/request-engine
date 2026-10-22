import os
import re
from html import unescape
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.modules.tenancy.api.staff_membership_reads import StaffAuthorityPlanBody
from request_engine.modules.tenancy.api.staff_membership_routes import (
    NativeStaffInviteBody,
    StaffAuthorityReplaceBody,
    StaffMembershipTransitionBody,
    StaffProfileUpdateBody,
)

ORG = "11111111-1111-4111-8111-111111111111"
MEMBER = "22222222-2222-4222-8222-222222222222"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name, expected", [("Updated display name", "Updated display name"), ("", None)]
)
async def test_profile_edit_prefills_revision_and_forwards_name_or_explicit_clear(
    name: str, expected: str | None
) -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf_match
        assert 'name="expected_profile_revision"' in page.text
        assert 'value="3"' in page.text
        assert 'value="Jordan Example"' in page.text
        response = await client.post(
            f"/tenants/{ORG}/staff/{MEMBER}/profile",
            data={
                "csrf_token": csrf_match.group(1),
                "_intent_id": "profile-intent",
                "display_name": name,
                "expected_profile_revision": "3",
                "provenance_reference": "admin:correct-name",
            },
        )
    assert response.status_code == 303
    assert response.headers["location"] == f"/tenants/{ORG}/staff/{MEMBER}"
    call = runtime.requests[-1]
    assert call[:2] == ("PATCH", f"/v1/staff/members/{MEMBER}/profile")
    assert call[2]["json_body"] == {
        "display_name": expected,
        "expected_profile_revision": 3,
        "provenance_reference": "admin:correct-name",
    }
    assert call[2]["extra_headers"] == {
        "idempotency-key": "profile-intent",
        "X-RE-Organization-ID": ORG,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 404, 422, 503])
async def test_history_is_read_only_redacted_and_forwards_trusted_session(status: int) -> None:
    class HistoryApi(FakeApi):
        async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
            if path.endswith("/history"):
                self.requests.append((method, path, kwargs))
                return ControlResponse(
                    status,
                    {
                        "items": [
                            {
                                "event_id": MEMBER,
                                "occurred_at": "2026-10-02T12:00:00Z",
                                "command_name": "staff.profile.update",
                                "actor_principal_id": ORG,
                                "revision_kind": "profile",
                                "revision_before": 0,
                                "revision_after": 1,
                                "payload": "private-secret-not-for-rendering",
                            }
                        ],
                        "next_cursor": MEMBER,
                        "error": {"detail": "private-error-not-for-rendering"},
                    },
                    {},
                )
            return await super().request(method, path, **kwargs)

    control, runtime = FakeApi(), HistoryApi(runtime=True)
    settings = AdminConsoleSettings(
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    path = f"/tenants/{ORG}/staff/{MEMBER}/history"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        assert (await client.get(path)).status_code == 303
        assert not runtime.requests
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"{path}?after={ORG}&limit=2")
    assert page.status_code == status
    assert "private-secret" not in page.text
    assert "private-error" not in page.text
    content = page.text.split("<h1>Historial de cambios</h1>", 1)[1].split("</main>", 1)[0]
    assert "<form" not in content
    assert "Cambios más recientes" in page.text
    assert ("Nombre cambiado" in page.text) is (status == 200)
    assert ("Cambios anteriores" in page.text) is (status == 200)
    assert len(runtime.requests) == 1
    method, upstream_path, kwargs = runtime.requests[0]
    assert (method, upstream_path) == ("GET", f"/v1/staff/members/{MEMBER}/history")
    assert kwargs["params"] == {"after": ORG, "limit": "2"}
    assert kwargs["bearer"] == "token"
    assert kwargs["extra_headers"] == {"X-RE-Organization-ID": ORG}
    assert all("X-RE-Organization-ID" not in headers for headers in control.headers)


class FakeApi:
    def __init__(self, *, runtime: bool = False) -> None:
        self.runtime = runtime
        self.headers: list[dict[str, str]] = []
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.headers.append(kwargs.get("extra_headers") or {})
        self.requests.append((method, path, kwargs))
        if not self.runtime and path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "token"}, {})
        if path == "/v1/staff/overview":
            return ControlResponse(
                200,
                {
                    "total": 1,
                    "active": 1,
                    "invited": 0,
                    "suspended": 0,
                    "revoked": 0,
                    "effective_capabilities": ["staff.read", "staff.manage_authority"],
                    "delegable_ceiling": ["staff.read"],
                },
                {},
            )
        if path == "/v1/staff/members":
            return ControlResponse(
                200,
                {
                    "items": [
                        {
                            "membership_id": MEMBER,
                            "principal_id": ORG,
                            "status": "active",
                            "membership_revision": 1,
                            "authority_revision": 1,
                            "profile_revision": 0,
                            "principal_active": True,
                            "authority_anchor_party_id": None,
                            "standing_grants": [],
                        }
                    ],
                    "next_cursor": None,
                },
                {},
            )
        if path == f"/v1/staff/members/{MEMBER}":
            return ControlResponse(
                200,
                {
                    "membership_id": MEMBER,
                    "principal_id": ORG,
                    "status": "active",
                    "membership_revision": 1,
                    "authority_revision": 1,
                    "standing_grants": [],
                    "display_name": "Jordan Example",
                    "profile_revision": 3,
                    "principal_active": True,
                    "authority_anchor_party_id": None,
                },
                {},
            )
        if path == f"/v1/staff/members/{MEMBER}/profile" and method == "PATCH":
            return ControlResponse(200, {"profile_revision": 4}, {})
        return ControlResponse(404, {"error": {"code": "not_found"}}, {})

    async def openapi(self) -> dict[str, Any]:
        if not self.runtime:
            return {"paths": {}}
        paths: dict[str, Any] = {}
        for path, method, operation_id, capability in (
            ("/v1/staff/overview", "get", "staff_overview_get", "staff.read"),
            ("/v1/staff/members", "get", "staff_list", "staff.read"),
            ("/v1/staff/members/native", "post", "staff_invite", "staff.invite"),
            ("/v1/staff/members/{membership_id}", "get", "staff_get", "staff.read"),
            (
                "/v1/staff/members/{membership_id}/history",
                "get",
                "staff_history_list",
                "staff.read",
            ),
            (
                "/v1/staff/members/{membership_id}/authority:plan",
                "post",
                "staff_authority_plan",
                "staff.plan_authority",
            ),
            (
                "/v1/staff/members/{membership_id}/authority",
                "put",
                "staff_manage_authority",
                "staff.manage_authority",
            ),
            (
                "/v1/staff/members/{membership_id}/status",
                "put",
                "staff_manage_membership",
                "staff.manage_membership",
            ),
            (
                "/v1/staff/members/{membership_id}/profile",
                "patch",
                "staff_profile_update",
                "staff.manage_membership",
            ),
        ):
            paths.setdefault(path, {})[method] = {
                "operationId": operation_id,
                "x-request-engine-capability": capability,
                "x-request-engine-kind": "query" if method == "get" else "command",
                "x-request-engine-idempotency": "required"
                if method in {"post", "put", "patch"} and operation_id != "staff_authority_plan"
                else "none",
                "x-request-engine-owner": "tenancy",
                "x-request-engine-exposure": "admin",
                "parameters": [
                    {
                        "name": "membership_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ]
                if "{membership_id}" in path
                else [],
            }
        bodies = {
            "staff_invite": NativeStaffInviteBody,
            "staff_authority_plan": StaffAuthorityPlanBody,
            "staff_manage_authority": StaffAuthorityReplaceBody,
            "staff_manage_membership": StaffMembershipTransitionBody,
            "staff_profile_update": StaffProfileUpdateBody,
        }
        for methods in paths.values():
            for operation in methods.values():
                model = bodies.get(operation["operationId"])
                if model is not None:
                    operation["requestBody"] = {
                        "required": True,
                        "content": {"application/json": {"schema": model.model_json_schema()}},
                    }
        return {"paths": paths}

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_staff_workspace_forwards_tenant_selector_only_to_runtime() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff")
    assert page.status_code == 200
    assert "Personas y permisos" in page.text
    assert MEMBER in page.text
    assert runtime.headers[-1]["X-RE-Organization-ID"] == ORG
    assert all("X-RE-Organization-ID" not in headers for headers in control.headers)
    assert re.search(r"Agregar una identidad que ya existe", page.text)
    assert (
        '<details class="card" style="min-width: 0">'
        "<summary>Agregar una identidad que ya existe (avanzado)" in page.text
    )
    assert '<div class="staff-directory">' in page.text
    assert "Para sumar a alguien de la forma normal, use Invitar por correo." in page.text
    assert "Puede hacer" in page.text
    assert "Puede dar" in page.text
    assert "staff.manage_authority" in page.text


@pytest.mark.asyncio
async def test_staff_workspace_forwards_cursor_and_renders_next_page() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    original_request = runtime.request

    async def paged_request(method: str, path: str, **kwargs: Any) -> ControlResponse:
        response = await original_request(method, path, **kwargs)
        if path == "/v1/staff/members" and response.status_code == 200:
            return ControlResponse(
                200,
                {**response.payload, "next_cursor": MEMBER},
                response.headers,
            )
        return response

    runtime.request = paged_request  # type: ignore[method-assign]
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff?after={MEMBER}&limit=1")

    assert page.status_code == 200
    assert f"after={MEMBER}" in page.text
    assert "limit=1" in page.text
    assert "trail=" in page.text
    list_requests = [entry for entry in runtime.requests if entry[1] == "/v1/staff/members"]
    assert list_requests[-1][2]["params"] == {"after": MEMBER, "limit": "1"}


@pytest.mark.asyncio
async def test_name_search_is_forwarded_and_encoded_in_both_page_links() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    original = runtime.request

    async def paged(method: str, path: str, **kwargs: Any) -> ControlResponse:
        response = await original(method, path, **kwargs)
        if path == "/v1/staff/members":
            return ControlResponse(200, {**response.payload, "next_cursor": MEMBER}, {})
        return response

    runtime.request = paged  # type: ignore[method-assign]
    settings = AdminConsoleSettings(
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(
            f"/tenants/{ORG}/staff",
            params={
                "search": "  María & Chen  ",
                "status": "active",
                "after": MEMBER,
                "trail": "root",
                "limit": 1,
            },
        )
        invalid = await client.get(f"/tenants/{ORG}/staff", params={"search": "a" * 101})
    assert page.status_code == 200
    assert "search=Mar%C3%ADa%20%26%20Chen" in unescape(page.text)
    assert page.text.count("search=Mar%C3%ADa%20%26%20Chen") == 2
    assert runtime.requests[-1][2]["params"] == {
        "limit": "1",
        "after": MEMBER,
        "status": "active",
        "search": "María & Chen",
    }
    assert 'value="María &amp; Chen"' in page.text
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_staff_workspace_rejects_invalid_pagination_before_runtime() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        bad_cursor = await client.get(f"/tenants/{ORG}/staff?after=not-a-uuid")
        bad_limit = await client.get(f"/tenants/{ORG}/staff?limit=101")

    assert bad_cursor.status_code == 422
    assert bad_limit.status_code == 422
    assert not [entry for entry in runtime.requests if entry[1] == "/v1/staff/members"]


@pytest.mark.asyncio
async def test_staff_member_route_rejects_invite_action() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        session_cookie = client.cookies.get(settings.session_cookie_name)
        assert session_cookie is not None
        # Read the rendered page to obtain the CSRF value rather than forging it.
        page = await client.get(f"/tenants/{ORG}/staff")
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert match is not None
        response = await client.post(
            f"/tenants/{ORG}/staff/{MEMBER}/invite",
            data={"csrf_token": match.group(1)},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_staff_detail_warns_that_native_session_revocation_is_global() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")

    assert response.status_code == 200
    assert "cierra todas sus sesiones" in response.text
    assert "otros negocios a los que pertenece" in response.text


@pytest.mark.asyncio
async def test_staff_detail_without_runtime_fails_closed() -> None:
    control = FakeApi()
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")

    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "message"),
    [
        (401, "sesión ya no está autorizada"),
        (403, "no tiene permiso"),
        (404, "No se encontró"),
        (503, "no está disponible ahora"),
    ],
)
async def test_staff_workspace_failed_read_hides_mutations(
    upstream_status: int, message: str
) -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    original_request = runtime.request

    async def failed_read(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == "/v1/staff/members":
            return ControlResponse(upstream_status, {"error": {"code": "read_failed"}}, {})
        return await original_request(method, path, **kwargs)

    runtime.request = failed_read  # type: ignore[method-assign]
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff")

    assert response.status_code == upstream_status
    assert message in response.text
    assert "Agregar una identidad que ya existe" not in response.text
    assert 'id="staff-invite"' not in response.text


@pytest.mark.asyncio
async def test_staff_detail_not_found_renders_no_mutation_forms() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    original_request = runtime.request

    async def missing_detail(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == f"/v1/staff/members/{MEMBER}":
            return ControlResponse(404, {"error": {"code": "not_found"}}, {})
        return await original_request(method, path, **kwargs)

    runtime.request = missing_detail  # type: ignore[method-assign]
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")

    assert response.status_code == 404
    assert "No se encontró" in response.text
    assert 'id="staff-plan"' not in response.text
    assert 'id="staff-status"' not in response.text


@pytest.mark.asyncio
async def test_staff_authority_apply_exists_only_after_successful_review() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    original_request = runtime.request
    bodies: list[object] = []

    async def planned_request(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == f"/v1/staff/members/{MEMBER}/authority:plan":
            bodies.append(kwargs.get("json_body"))
            return ControlResponse(
                200,
                {
                    "membership_id": MEMBER,
                    "authority_revision": 1,
                    "current": [],
                    "desired": ["staff.read"],
                    "added": ["staff.read"],
                    "removed": [],
                    "assignable": True,
                    "blocked_capabilities": [],
                    "can_apply": True,
                    "blockers": [],
                },
                {},
            )
        if path == f"/v1/staff/members/{MEMBER}/authority":
            bodies.append(kwargs.get("json_body"))
            return ControlResponse(200, {"authority_revision": 2}, {})
        return await original_request(method, path, **kwargs)

    runtime.request = planned_request  # type: ignore[method-assign]
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        detail = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")
        assert "Aplicar el borrador revisado" not in detail.text
        assert 'name="selected_capabilities" value="staff.read"' in detail.text
        assert 'name="desired_capabilities"' not in detail.text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
        assert csrf is not None
        preview = await client.post(
            f"/tenants/{ORG}/staff/{MEMBER}/plan",
            data={
                "csrf_token": csrf.group(1),
                "_intent_id": "review-intent",
                "_permission_picker": "1",
                "selected_capabilities": "staff.read",
                "expected_authority_revision": "1",
                "provenance_reference": "review:test",
            },
        )
        reviewed = {
            name: unescape(value)
            for name, value in re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', preview.text)
        }
        applied = await client.post(f"/tenants/{ORG}/staff/{MEMBER}/authority", data=reviewed)

    assert preview.status_code == 200
    assert applied.status_code == 303
    assert applied.headers["location"] == f"/tenants/{ORG}/staff/{MEMBER}"
    assert bodies == [
        {"expected_authority_revision": 1, "desired_capabilities": ["staff.read"]},
        {
            "expected_authority_revision": 1,
            "desired_capabilities": ["staff.read"],
            "provenance_reference": "review:test",
        },
    ]
    assert "Aplicar el borrador revisado" in preview.text
    assert 'value="[&#34;staff.read&#34;]"' in preview.text
    assert 'value="1"' in preview.text
    assert 'value="review:test"' in preview.text


@pytest.mark.asyncio
async def test_blocked_staff_authority_preview_never_offers_apply() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    original_request = runtime.request

    async def blocked_request(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == f"/v1/staff/members/{MEMBER}/authority:plan":
            return ControlResponse(
                200,
                {
                    "membership_id": MEMBER,
                    "authority_revision": 1,
                    "current": ["staff.manage_authority"],
                    "desired": [],
                    "added": [],
                    "removed": ["staff.manage_authority"],
                    "assignable": True,
                    "blocked_capabilities": [],
                    "can_apply": False,
                    "blockers": ["last_controller"],
                },
                {},
            )
        return await original_request(method, path, **kwargs)

    runtime.request = blocked_request  # type: ignore[method-assign]
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        detail = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
        assert csrf is not None
        preview = await client.post(
            f"/tenants/{ORG}/staff/{MEMBER}/plan",
            data={
                "csrf_token": csrf.group(1),
                "_intent_id": "review-intent",
                "desired_capabilities": "[]",
                "expected_authority_revision": "1",
                "provenance_reference": "review:blocked",
            },
        )

    assert preview.status_code == 200
    assert "last_controller" in preview.text
    assert "Aplicar el borrador revisado" not in preview.text


@pytest.mark.asyncio
async def test_staff_workspace_renders_previous_page_from_validated_trail() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff?after={MEMBER}&limit=1&trail=root")

    assert page.status_code == 200
    assert "← Página anterior" in page.text
    assert f'href="/tenants/{ORG}/staff?limit=1"' in page.text


@pytest.mark.asyncio
async def test_staff_workspace_rejects_forged_pagination_trail() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff?after={MEMBER}&trail=not-a-cursor")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_staff_workspace_catalog_failure_is_503_not_500() -> None:
    class BrokenCatalog(FakeApi):
        async def openapi(self) -> dict[str, Any]:
            raise RuntimeError("catalog unavailable")

    control, runtime = FakeApi(), BrokenCatalog(runtime=True)
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff")

    assert response.status_code == 503
    assert "acciones del equipo no están disponibles" in response.text


@pytest.mark.asyncio
async def test_staff_status_filter_is_api_backed_and_survives_both_page_links() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    original_request = runtime.request

    async def paged_request(method: str, path: str, **kwargs: Any) -> ControlResponse:
        response = await original_request(method, path, **kwargs)
        if path == "/v1/staff/members":
            return ControlResponse(200, {**response.payload, "next_cursor": MEMBER}, {})
        return response

    runtime.request = paged_request  # type: ignore[method-assign]
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=control, runtime_client=runtime)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(
            f"/tenants/{ORG}/staff?status=active&after={MEMBER}&limit=1&trail=root"
        )
        cleared = await client.get(f"/tenants/{ORG}/staff?status=&limit=1")
        invalid = await client.get(f"/tenants/{ORG}/staff?status=disabled")

    assert response.status_code == 200
    assert '<option value="active" selected>Activo</option>' in response.text
    assert f'href="/tenants/{ORG}/staff?limit=1&amp;status=active"' in response.text
    assert f"trail=root,{MEMBER}&amp;status=active" in response.text
    assert "Los totales de arriba cubren toda la organización" in response.text
    # Changing the filter starts at page one: the GET form contains no cursor/trail.
    filter_form = re.search(r'<form method="get".*?</form>', response.text, re.DOTALL)
    assert filter_form is not None
    assert 'name="after"' not in filter_form.group()
    assert 'name="trail"' not in filter_form.group()
    list_requests = [entry for entry in runtime.requests if entry[1] == "/v1/staff/members"]
    assert list_requests[0][2]["params"] == {"limit": "1", "after": MEMBER, "status": "active"}
    assert cleared.status_code == 200
    assert list_requests[1][2]["params"] == {"limit": "1"}
    assert invalid.status_code == 422
    assert len(list_requests) == 2


def staff_client(runtime: FakeApi) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("unit-test-session-secret-40-characters"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=FakeApi(), runtime_client=runtime)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("membership_id", ORG),
        ("principal_id", "not-an-id"),
        ("membership_revision", 0),
        ("authority_revision", None),
        ("authority_revision", True),
        ("profile_revision", -1),
        ("profile_revision", "3"),
    ],
)
async def test_staff_detail_incomplete_identity_or_revision_never_offers_commands(
    field: str, value: object
) -> None:
    runtime = FakeApi(runtime=True)
    original = runtime.request

    async def malformed(method: str, path: str, **kwargs: Any) -> ControlResponse:
        response = await original(method, path, **kwargs)
        if path == f"/v1/staff/members/{MEMBER}":
            return ControlResponse(200, {**response.payload, field: value}, {})
        return response

    runtime.request = malformed  # type: ignore[method-assign]
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")
    assert page.status_code == 502
    assert 'id="staff-profile"' not in page.text
    assert 'id="staff-status"' not in page.text
    assert 'id="staff-plan"' not in page.text
    # The malformed read must not trigger another read that fabricates a usable form.
    assert len(runtime.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["membership_id", "principal_id", "next_cursor"])
async def test_staff_list_rejects_invalid_link_targets(field: str) -> None:
    runtime = FakeApi(runtime=True)
    original = runtime.request

    async def malformed(method: str, path: str, **kwargs: Any) -> ControlResponse:
        response = await original(method, path, **kwargs)
        if path == "/v1/staff/members":
            payload = {**response.payload}
            if field == "next_cursor":
                payload[field] = "not-an-id"
            else:
                payload["items"] = [{**payload["items"][0], field: "not-an-id"}]
            return ControlResponse(200, payload, {})
        return response

    runtime.request = malformed  # type: ignore[method-assign]
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff")
    assert page.status_code == 502
    assert "not-an-id" not in page.text
    assert 'id="staff-invite"' not in page.text


@pytest.mark.asyncio
async def test_staff_detail_real_render_has_parseable_forms_and_current_revisions() -> None:
    from html.parser import HTMLParser

    class Forms(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.current: str | None = None
            self.forms: dict[str, dict[str, str | None]] = {}

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes = dict(attrs)
            if tag == "form":
                self.current = attributes.get("id")
                if self.current:
                    self.forms[self.current] = {"action": attributes.get("action")}
            elif tag == "input" and self.current and attributes.get("name"):
                self.forms[self.current][str(attributes["name"])] = attributes.get("value")

        def handle_endtag(self, tag: str) -> None:
            if tag == "form":
                self.current = None

    async with staff_client(FakeApi(runtime=True)) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")
    assert page.status_code == 200
    parser = Forms()
    parser.feed(page.text)
    for name, revision_name, revision in (
        ("profile", "expected_profile_revision", "3"),
        ("plan", "expected_authority_revision", "1"),
        ("status", "expected_revision", "1"),
    ):
        form = parser.forms[f"staff-{name}"]
        assert form["action"] == f"/tenants/{ORG}/staff/{MEMBER}/{name}"
        assert form[revision_name] == revision
        assert form["csrf_token"]
    assert "Aplicar el borrador revisado" not in page.text


@pytest.mark.asyncio
async def test_staff_business_configuration_navigation_uses_validated_tenant_only() -> None:
    runtime = FakeApi(runtime=True)
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(
            f"/tenants/{ORG}/staff?organization_id={MEMBER}&authority_party_id={MEMBER}",
            headers={"X-RE-Organization-ID": MEMBER},
        )
    assert page.status_code == 200
    assert f'href="/tenants/{ORG}/configuration"' in page.text
    assert f'href="/tenants/{MEMBER}/configuration"' not in page.text
    assert "Configuración del negocio" in page.text
    for _, _, kwargs in runtime.requests:
        assert kwargs["extra_headers"] == {"X-RE-Organization-ID": ORG}
        assert "authority_party_id" not in (kwargs.get("params") or {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": None, "next_cursor": None},
        {"items": "not-a-list", "next_cursor": None},
        {"items": [None], "next_cursor": None},
        {"items": [{"membership_id": MEMBER}], "next_cursor": None},
        {"items": []},
    ],
)
async def test_staff_success_status_with_invalid_page_is_not_empty_success(
    payload: dict[str, object],
) -> None:
    runtime = FakeApi(runtime=True)
    original = runtime.request

    async def malformed(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == "/v1/staff/members":
            runtime.requests.append((method, path, kwargs))
            return ControlResponse(200, payload, {})
        return await original(method, path, **kwargs)

    runtime.request = malformed  # type: ignore[method-assign]
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff")
    assert page.status_code == 502
    assert 'id="staff-invite"' not in page.text
    assert "No hay miembros visibles en el equipo" not in page.text
    assert "Invitar por correo" not in page.text
    assert all(method == "GET" for method, _, _ in runtime.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace", ["", f"/{MEMBER}"])
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total", None),
        ("active", True),
        ("invited", "0"),
        ("suspended", -1),
        ("effective_capabilities", None),
        ("delegable_ceiling", "staff.read"),
        ("delegable_ceiling", [None]),
    ],
)
async def test_staff_malformed_overview_never_constructs_authority_forms(
    workspace: str, field: str, value: object
) -> None:
    runtime = FakeApi(runtime=True)
    original = runtime.request

    async def malformed(method: str, path: str, **kwargs: Any) -> ControlResponse:
        response = await original(method, path, **kwargs)
        if path == "/v1/staff/overview":
            return ControlResponse(200, {**response.payload, field: value}, {})
        return response

    runtime.request = malformed  # type: ignore[method-assign]
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff{workspace}")
    assert page.status_code == 502
    assert 'id="staff-invite"' not in page.text
    assert 'id="staff-plan"' not in page.text
    assert 'id="staff-status"' not in page.text
    assert 'id="staff-profile"' not in page.text
    assert all(method == "GET" for method, _, _ in runtime.requests)


@pytest.mark.asyncio
async def test_staff_valid_empty_owner_page_still_renders_truthful_empty_state() -> None:
    runtime = FakeApi(runtime=True)
    original = runtime.request

    async def empty(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == "/v1/staff/members":
            return ControlResponse(200, {"items": [], "next_cursor": None}, {})
        return await original(method, path, **kwargs)

    runtime.request = empty  # type: ignore[method-assign]
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff")
    assert page.status_code == 200
    assert "No hay miembros visibles en el equipo" in page.text
    assert 'id="staff-invite"' in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": None, "next_cursor": None},
        {"items": "invalid", "next_cursor": None},
        {"items": [None], "next_cursor": None},
        {"items": [{"event_id": MEMBER}], "next_cursor": None},
        {"items": []},
        {"items": [], "next_cursor": "invalid"},
    ],
)
async def test_staff_history_invalid_collection_never_claims_empty_provenance(
    payload: dict[str, Any],
) -> None:
    runtime = FakeApi(runtime=True)
    original = runtime.request

    async def malformed(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path.endswith("/history"):
            runtime.requests.append((method, path, kwargs))
            return ControlResponse(200, payload, {})
        return await original(method, path, **kwargs)

    runtime.request = malformed  # type: ignore[method-assign]
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff/{MEMBER}/history")
    assert page.status_code == 502
    assert "Respuesta inesperada del historial" in page.text
    assert "No hay cambios visibles" not in page.text
    assert "Cambios anteriores" not in page.text
    assert all(method == "GET" for method, _, _ in runtime.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "valid_empty",
        "invalid_revision",
        "invalid_time",
        "too_many",
        "invalid_command",
        "invalid_revision_kind",
    ],
)
async def test_staff_history_valid_empty_and_factual_entry_validation(case: str) -> None:
    runtime = FakeApi(runtime=True)
    original = runtime.request
    entry: dict[str, Any] = {
        "event_id": MEMBER,
        "actor_principal_id": ORG,
        "occurred_at": "2026-10-02T12:00:00Z",
        "command_name": "staff.profile.update",
        "revision_kind": "profile",
        "revision_before": 0,
        "revision_after": 1,
    }
    if case == "invalid_command":
        entry["command_name"] = "payments.fake_event"
    elif case == "invalid_revision_kind":
        entry["revision_kind"] = "unknown_revision"
    elif case == "invalid_revision":
        entry["revision_after"] = True
    elif case == "invalid_time":
        entry["occurred_at"] = "not-a-time"
    payload = {"items": [] if case == "valid_empty" else [entry], "next_cursor": None}
    if case == "too_many":
        payload["items"] = [entry, entry]

    async def response(method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path.endswith("/history"):
            runtime.requests.append((method, path, kwargs))
            return ControlResponse(200, payload, {})
        return await original(method, path, **kwargs)

    runtime.request = response  # type: ignore[method-assign]
    async with staff_client(runtime) as client:
        await client.post("/login", data={"login_handle": "manager", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff/{MEMBER}/history?limit=1")
    assert page.status_code == (200 if case == "valid_empty" else 502)
    assert ("No hay cambios visibles" in page.text) is (case == "valid_empty")
    assert all(method == "GET" for method, _, _ in runtime.requests)
