from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

pytestmark = [pytest.mark.unit]
ORG = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class _Api:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.method = "get"
        self.failure: Exception | None = None
        self.response = ControlResponse(
            200,
            {
                "items": [
                    {
                        "organization_id": ORG,
                        "display_name": "North & South",
                        "principal_id": OTHER,
                        "membership_id": OTHER,
                    }
                ],
                "next_after": ORG,
                "requires_owner_validation": True,
            },
            {},
        )

    async def openapi(self) -> dict[str, Any]:
        return {
            "paths": {
                "/v1/me/organizations": {
                    self.method: {"operationId": "self_organization_list"},
                }
            }
        }

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "verified-token"}, {})
        if self.failure is not None:
            raise self.failure
        return self.response

    async def aclose(self) -> None:
        pass


@pytest.fixture
def console(tmp_path: Path) -> tuple[FastAPI, _Api, _Api]:
    control, runtime = _Api(), _Api()
    settings = AdminConsoleSettings(
        session_store_directory=tmp_path / "sessions",
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("test-session-secret-with-at-least-32-characters"),
        cookie_secure=False,
    )
    return (
        create_admin_console_app(settings, client=control, runtime_client=runtime),
        control,
        runtime,
    )


@pytest.mark.asyncio
async def test_self_context_page_uses_runtime_without_browser_tenant_or_identity(
    console: tuple[FastAPI, _Api, _Api],
) -> None:
    app, control, runtime = console
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "user", "password": "password"})
        page = await client.get(
            f"/my-organizations?after={OTHER}&limit=2&subject_id=foreign",
            headers={"X-RE-Organization-ID": OTHER},
        )
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "North &amp; South" in page.text
    assert f'href="/tenants/{ORG}/staff"' in page.text
    assert f"after={ORG}&amp;limit=2" in page.text
    assert "Membership does not automatically grant" in page.text
    assert runtime.calls == [
        (
            "GET",
            "/v1/me/organizations",
            {
                "bearer": "verified-token",
                "params": {"limit": "2", "after": OTHER},
            },
        )
    ]
    assert all(path != "/v1/me/organizations" for _, path, _ in control.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,status",
    [
        ("anonymous", 303),
        ("unauthorized", 401),
        ("forbidden", 403),
        ("unavailable", 503),
        ("network", 503),
        ("malformed", 503),
        ("drift", 503),
    ],
)
async def test_self_context_failures_never_render_membership_links(
    console: tuple[FastAPI, _Api, _Api],
    case: str,
    status: int,
) -> None:
    app, _, runtime = console
    if case in {"unauthorized", "forbidden", "unavailable"}:
        runtime.response = ControlResponse(status, {"error": {}}, {})
    elif case == "network":
        runtime.failure = httpx.ConnectError("offline")
    elif case == "malformed":
        runtime.response = ControlResponse(200, {"items": [{"organization_id": "bad"}]}, {})
    elif case == "drift":
        runtime.method = "post"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        if case != "anonymous":
            await client.post("/login", data={"login_handle": "user", "password": "password"})
        page = await client.get("/my-organizations")
    assert page.status_code == status
    assert f'href="/tenants/{ORG}/staff"' not in page.text
    assert "No active memberships" not in page.text
    if case in {"anonymous", "drift"}:
        assert runtime.calls == []


@pytest.mark.asyncio
async def test_empty_self_context_page_explains_membership_without_claiming_admin_access(
    console: tuple[FastAPI, _Api, _Api],
) -> None:
    app, _, runtime = console
    runtime.response = ControlResponse(
        200,
        {
            "items": [],
            "next_after": None,
            "requires_owner_validation": True,
        },
        {},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://console"
    ) as client:
        await client.post("/login", data={"login_handle": "user", "password": "password"})
        page = await client.get("/my-organizations")
    assert page.status_code == 200
    assert "No active memberships" in page.text
    assert "Platform ownership alone does not create a tenant membership" in page.text
