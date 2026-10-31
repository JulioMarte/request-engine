"""Password confirmation projects the current owner session, never a replacement login."""

import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings


class ReauthenticationApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.response = ControlResponse(
            200,
            {
                "authenticated_at": "2026-10-14T10:00:00Z",
                "reauth_expires_at": "2026-10-14T10:05:00Z",
            },
            {},
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(201, {"access_token": "same-owner-session"}, {})
        return self.response

    async def openapi(self) -> dict[str, Any]:
        return {"paths": {}}

    async def aclose(self) -> None:
        pass


@pytest_asyncio.fixture
async def confirmation_client() -> AsyncIterator[
    tuple[httpx.AsyncClient, ReauthenticationApi, str]
]:
    api = ReauthenticationApi()
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control",
        session_secret=SecretStr("password-confirmation-test-key-at-least-32-bytes"),
        cookie_secure=False,
    )
    app = create_admin_console_app(settings, client=api)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "initial-password"})
        page = await client.get("/operations")
        token = re.search(r'data-csrf="([^"]+)"', page.text)
        assert token is not None
        api.calls.clear()
        yield client, api, token.group(1)


@pytest.mark.asyncio
async def test_password_confirmation_keeps_current_bearer_and_browser_cookie(
    confirmation_client: tuple[httpx.AsyncClient, ReauthenticationApi, str],
) -> None:
    client, api, csrf = confirmation_client
    cookies = dict(client.cookies)
    response = await client.post(
        "/step-up/password", headers={"X-CSRF-Token": csrf}, json={"password": "current-password"}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert dict(client.cookies) == cookies
    assert "set-cookie" not in response.headers
    assert len(api.calls) == 1
    assert api.calls[0][:2] == ("POST", "/auth/native/sessions:reauth")
    assert api.calls[0][2]["bearer"] == "same-owner-session"
    assert api.calls[0][2]["json_body"] == {"password": "current-password"}
    assert "current-password" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("csrf", [None, "wrong"])
@pytest.mark.parametrize("path", ["/step-up/password", "/account/security/recovery-complete"])
async def test_password_confirmation_requires_current_session_csrf_before_forwarding(
    confirmation_client: tuple[httpx.AsyncClient, ReauthenticationApi, str],
    csrf: str | None,
    path: str,
) -> None:
    client, api, _ = confirmation_client
    response = await client.post(
        path,
        headers={"X-CSRF-Token": csrf} if csrf is not None else {},
        json={"password": "current-password"},
    )
    assert response.status_code == 403
    assert api.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("upstream_status", [401, 422])
async def test_password_confirmation_preserves_owner_rejection_without_a_new_session(
    confirmation_client: tuple[httpx.AsyncClient, ReauthenticationApi, str], upstream_status: int
) -> None:
    client, api, csrf = confirmation_client
    api.response = ControlResponse(upstream_status, {"error": {"code": "credential_invalid"}}, {})
    cookies = dict(client.cookies)
    response = await client.post(
        "/step-up/password", headers={"X-CSRF-Token": csrf}, json={"password": "wrong-password"}
    )
    assert response.status_code == upstream_status
    assert response.json()["error"]["code"] == "credential_invalid"
    assert dict(client.cookies) == cookies
    assert api.calls[0][1] == "/auth/native/sessions:reauth"


@pytest.mark.asyncio
async def test_password_confirmation_malformed_success_cannot_trigger_a_retry(
    confirmation_client: tuple[httpx.AsyncClient, ReauthenticationApi, str],
) -> None:
    client, api, csrf = confirmation_client
    api.response = ControlResponse(200, {}, {})
    response = await client.post(
        "/step-up/password", headers={"X-CSRF-Token": csrf}, json={"password": "current-password"}
    )
    assert response.status_code == 502
    assert "ok" not in response.json()


@pytest.mark.asyncio
async def test_recovery_completion_keeps_recovery_session_and_requires_another_sign_in(
    confirmation_client: tuple[httpx.AsyncClient, ReauthenticationApi, str],
) -> None:
    client, api, csrf = confirmation_client
    api.response = ControlResponse(
        200, {"recovery_state": "normal", "completed_at": "2026-10-14T10:00:00Z"}, {}
    )
    cookies = dict(client.cookies)
    response = await client.post(
        "/account/security/recovery-complete",
        headers={"X-CSRF-Token": csrf},
        json={"password": "new-current-password"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "requires_sign_in": True}
    assert dict(client.cookies) == cookies
    assert "set-cookie" not in response.headers
    assert api.calls[0][:2] == ("POST", "/auth/native/sessions/current/recovery:complete")
    assert api.calls[0][2]["bearer"] == "same-owner-session"
    assert api.calls[0][2]["json_body"] == {"password": "new-current-password"}
    assert "new-current-password" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/step-up/password", "/account/security/recovery-complete"])
@pytest.mark.parametrize(
    "body", [{"password": ""}, {"password": 17}, {"password": "pw", "principal_id": "foreign"}]
)
async def test_password_confirmation_does_not_forward_invalid_or_authority_shaped_body(
    confirmation_client: tuple[httpx.AsyncClient, ReauthenticationApi, str],
    path: str,
    body: dict[str, Any],
) -> None:
    client, api, csrf = confirmation_client
    response = await client.post(path, headers={"X-CSRF-Token": csrf}, json=body)
    assert response.status_code == 422
    assert api.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/step-up/password", "/account/security/recovery-complete"])
async def test_password_confirmation_denies_native_form_submission_before_owner(
    confirmation_client: tuple[httpx.AsyncClient, ReauthenticationApi, str], path: str
) -> None:
    client, api, csrf = confirmation_client
    response = await client.post(
        path, headers={"X-CSRF-Token": csrf}, data={"password": "current-password"}
    )
    assert response.status_code == 422
    assert api.calls == []
