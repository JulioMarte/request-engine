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
)

ORG = "11111111-1111-4111-8111-111111111111"
MEMBER = "22222222-2222-4222-8222-222222222222"


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
                            "standing_grants": [],
                        }
                    ]
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
                },
                {},
            )
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
        ):
            paths.setdefault(path, {})[method] = {
                "operationId": operation_id,
                "x-request-engine-capability": capability,
                "x-request-engine-kind": "query" if method == "get" else "command",
                "x-request-engine-idempotency": "required"
                if method in {"post", "put"} and operation_id != "staff_authority_plan"
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff")
    assert page.status_code == 200
    assert "People &amp; permissions" in page.text
    assert MEMBER in page.text
    assert runtime.headers[-1]["X-RE-Organization-ID"] == ORG
    assert all("X-RE-Organization-ID" not in headers for headers in control.headers)
    assert re.search(r"Add an existing native identity", page.text)
    assert "Can do" in page.text
    assert "Can grant" in page.text
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")

    assert response.status_code == 200
    assert "sessions globally" in response.text
    assert "other tenant contexts" in response.text


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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")

    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_status", "message"),
    [
        (401, "session is no longer authorized"),
        (403, "do not have permission"),
        (404, "was not found"),
        (503, "temporarily unavailable"),
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff")

    assert response.status_code == upstream_status
    assert message in response.text
    assert "Add an existing native identity" not in response.text
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")

    assert response.status_code == 404
    assert "was not found" in response.text
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        detail = await client.get(f"/tenants/{ORG}/staff/{MEMBER}")
        assert "Apply reviewed draft" not in detail.text
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
    assert "Apply reviewed draft" in preview.text
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
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
    assert "Apply reviewed draft" not in preview.text


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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        page = await client.get(f"/tenants/{ORG}/staff?after={MEMBER}&limit=1&trail=root")

    assert page.status_code == 200
    assert "← Previous page" in page.text
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
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
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "pw"})
        response = await client.get(f"/tenants/{ORG}/staff")

    assert response.status_code == 503
    assert "catalog unavailable" in response.text.lower()
