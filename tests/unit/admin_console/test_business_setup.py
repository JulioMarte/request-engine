"""First-business journey uses real canonical schemas and authoritative labels."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app

_ACCOUNT = str(UUID(int=123))
_BUSINESS = str(UUID(int=456))
_PARTY = str(UUID(int=789))


class BusinessPort:
    def __init__(self, *, accounts: Any = None, created: Any = None) -> None:
        self.accounts = (
            accounts
            if accounts is not None
            else {
                "items": [
                    {
                        "native_identity_id": _ACCOUNT,
                        "login_handle": "ana@example.test",
                        "status": "active",
                    }
                ],
                "next_cursor": None,
            }
        )
        self.created = (
            created
            if created is not None
            else {
                "organization_id": _BUSINESS,
                "organization_party_id": _PARTY,
                "controller_principal_id": str(UUID(int=12)),
                "controller_binding_id": str(UUID(int=13)),
            }
        )
        self.writes: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        pass

    async def openapi(self) -> dict[str, Any]:
        inert = cast(Any, object())
        return create_platform_control_app(
            auth_session_factory=inert,
            platform_read_session_factory=inert,
            platform_write_session_factory=inert,
            native_authority_id=UUID(int=1),
            webauthn_decoy_key=b"business-setup-test-key-32-bytes-long",
        ).openapi()

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "owner-token"}, {})
        if method == "GET" and path == "/v1/platform/native-identities":
            assert kwargs["bearer"] == "owner-token"
            return ControlResponse(200, self.accounts, {})
        if method == "POST" and path == "/v1/platform/organizations":
            self.writes.append(kwargs)
            return ControlResponse(201, self.created, {})
        return ControlResponse(404, {"error": {"code": "not_found"}}, {})


def client_for(port: BusinessPort) -> httpx.AsyncClient:
    settings = AdminConsoleSettings(
        session_store_directory=Path(
            os.environ["REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY"]
        ),
        control_api_base_url="http://control:8001",
        session_secret=SecretStr("first-business-test-session-secret-40-chars"),
        cookie_secure=False,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_admin_console_app(settings, client=port)),
        base_url="http://console",
        headers={"Origin": "http://console"},
    )


async def open_form(client: httpx.AsyncClient) -> httpx.Response:
    await client.post("/login", data={"login_handle": "owner", "password": "password"})
    return await client.get("/resources/business-setup")


@pytest.mark.asyncio
async def test_named_selection_creates_business_and_links_actual_party() -> None:
    port = BusinessPort()
    async with client_for(port) as client:
        page = await open_form(client)
        assert page.status_code == 200
        assert f'<option value="{_ACCOUNT}"' in page.text
        assert "ana@example.test" in page.text
        assert not port.writes
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf
        result = await client.post(
            "/resources/business-setup",
            data={
                "csrf_token": csrf[1],
                "_intent_id": "same-creation-intent",
                "organization_key": "central-clinic",
                "display_name": "Central Clinic",
                "controller_native_identity_id": _ACCOUNT,
                "provenance_reference": "Starting business",
            },
        )
    assert result.status_code == 200
    assert f"/tenants/{_BUSINESS}/configuration/setup?authority_party_id={_PARTY}" in result.text
    assert port.writes[0]["json_body"]["controller_native_identity_id"] == _ACCOUNT
    assert port.writes[0]["extra_headers"]["idempotency-key"] == "same-creation-intent"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "accounts",
    [
        {},
        {"items": [], "next_cursor": "bad"},
        {
            "items": [{"native_identity_id": _ACCOUNT, "status": "active"}],
            "next_cursor": None,
        },
    ],
)
async def test_incomplete_account_inventory_blocks_guided_creation(accounts: Any) -> None:
    port = BusinessPort(accounts=accounts)
    async with client_for(port) as client:
        page = await open_form(client)
    assert "Could not load named accounts" in page.text
    assert "disabled>Create business and continue" in page.text
    assert not port.writes


@pytest.mark.asyncio
async def test_invalid_csrf_does_not_create_business() -> None:
    port = BusinessPort()
    async with client_for(port) as client:
        await open_form(client)
        result = await client.post("/resources/business-setup", data={"csrf_token": "wrong"})
    assert "csrf_failed" in result.text
    assert not port.writes


@pytest.mark.asyncio
async def test_incomplete_creation_result_does_not_invent_setup_authority() -> None:
    port = BusinessPort(created={"organization_id": _BUSINESS})
    async with client_for(port) as client:
        page = await open_form(client)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert csrf
        result = await client.post(
            "/resources/business-setup",
            data={
                "csrf_token": csrf[1],
                "organization_key": "central",
                "display_name": "Central",
                "controller_native_identity_id": _ACCOUNT,
                "provenance_reference": "Starting business",
            },
        )
    assert "incomplete_creation_result" in result.text
    assert "Continue with business setup" not in result.text
    assert len(port.writes) == 1
