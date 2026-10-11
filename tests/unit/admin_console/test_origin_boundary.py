"""Browser-origin CSRF boundary: reject before forwarding or changing a session."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings


class RecordingApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        del kwargs
        self.calls.append((method, path))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "owner-api-session"}, {})
        if path == "/v1/setup/sessions":
            return ControlResponse(201, {"token": "setup-api-session"}, {})
        if path == "/v1/setup/recovery-codes":
            return ControlResponse(200, {"codes": ["one-time-code"]}, {})
        return ControlResponse(200, {}, {})

    async def openapi(self) -> dict[str, Any]:
        return {}

    async def aclose(self) -> None:
        pass


def _client(
    directory: Path, api: RecordingApi, base_url: str = "http://console"
) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        control_api_base_url="http://control",
        session_secret=SecretStr("origin-test-secret-at-least-32-bytes"),
        session_store_directory=directory,
        cookie_secure=False,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_admin_console_app(settings, client=api)),
        base_url=base_url,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/login",
        "/login/webauthn/options",
        "/login/webauthn/complete",
        "/logout",
        "/step-up/options",
        "/step-up/complete",
        "/setup/recovery-codes",
    ],
)
@pytest.mark.parametrize(
    "origin",
    [None, "null", "http://attacker", "https://console", "http://console:8080", "http://console/"],
)
async def test_unsafe_origin_never_forwards_or_sets_cookie(
    tmp_path: Path, path: str, origin: str | None
) -> None:
    api = RecordingApi()
    async with _client(tmp_path, api) as client:
        await client.post(
            "/login",
            headers={"Origin": "http://console"},
            data={"login_handle": "legitimate", "password": "pw"},
        )
        await client.post("/setup/session", headers={"Origin": "http://console"})
        cookies_before = dict(client.cookies)
        api.calls.clear()
        response = await client.post(
            path,
            headers={"Origin": origin} if origin is not None else {},
            data={"login_handle": "attacker", "password": "pw"},
        )
        assert response.status_code == 403
        assert "set-cookie" not in response.headers
        assert dict(client.cookies) == cookies_before
        assert api.calls == []
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "headers",
    [
        [("Origin", "http://console"), ("Origin", "http://attacker")],
        [("Origin", "http://user@console")],
        [("Origin", "http://console?x=1")],
        [("Origin", "http://console#fragment")],
        [("Origin", "http://console:invalid")],
        [("Origin", "http://console:0")],
        [("Origin", "http://console\\@attacker")],
        [("Origin", "http://console http://attacker")],
        [("Origin", "https://console"), ("X-Forwarded-Proto", "https")],
        [("Origin", "http://attacker"), ("X-Forwarded-Host", "attacker")],
    ],
)
async def test_malformed_origin_or_untrusted_forwarded_headers_cannot_bypass_boundary(
    tmp_path: Path, method: str, headers: list[tuple[str, str]]
) -> None:
    api = RecordingApi()
    async with _client(tmp_path, api) as client:
        response = await client.request(method, "/login", headers=headers)
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert api.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "origin"),
    [("http://console", "http://console:80"), ("https://console:443", "https://console")],
)
async def test_same_origin_normalizes_default_ports_and_preserves_canonical_flow(
    tmp_path: Path, base_url: str, origin: str
) -> None:
    api = RecordingApi()
    async with _client(tmp_path, api, base_url) as client:
        headers = {"Origin": origin}
        login = await client.post(
            "/login", headers=headers, data={"login_handle": "legitimate", "password": "pw"}
        )
        assert login.status_code == 303
        assert "set-cookie" in login.headers
        assert (await client.post("/step-up/options", headers=headers)).status_code == 200
        assert (
            await client.post("/step-up/complete", headers=headers, json={"credential": {}})
        ).status_code == 200
        assert (await client.post("/setup/session", headers=headers)).status_code == 303
        assert (await client.post("/setup/recovery-codes", headers=headers)).status_code == 200
        assert (await client.post("/logout", headers=headers)).status_code == 303
        assert (await client.get("/")).status_code == 303
    assert api.calls == [
        ("POST", "/auth/native/sessions"),
        ("POST", "/auth/native/sessions/current/webauthn/step-up-options"),
        ("POST", "/auth/native/sessions/current/webauthn/step-up"),
        ("POST", "/v1/setup/sessions"),
        ("POST", "/v1/setup/recovery-codes"),
        ("GET", "/v1/setup"),
        ("DELETE", "/auth/native/sessions/current"),
    ]
