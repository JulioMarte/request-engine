import re
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

ORG = "11111111-1111-4111-8111-111111111111"
MEMBER = "22222222-2222-4222-8222-222222222222"


class FakeApi:
    def __init__(self, *, runtime: bool = False) -> None:
        self.runtime = runtime
        self.headers: list[dict[str, str]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.headers.append(kwargs.get("extra_headers") or {})
        if not self.runtime and path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "token"}, {})
        if path == "/v1/staff/overview":
            return ControlResponse(
                200, {"total": 1, "active": 1, "invited": 0, "suspended": 0, "revoked": 0}, {}
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
        return {"paths": paths}

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_staff_workspace_forwards_tenant_selector_only_to_runtime() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
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


@pytest.mark.asyncio
async def test_staff_member_route_rejects_invite_action() -> None:
    control, runtime = FakeApi(), FakeApi(runtime=True)
    settings = AdminConsoleSettings(
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
