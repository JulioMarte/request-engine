"""Owner permission upgrade page: plain request over controller policy adoption.

The upstream serves the REAL runtime OpenAPI document, so the console resolves
the owner operations by operationId. Eligibility, consent and approval are the
owner's: proven by the PostgreSQL adoption E2E tests.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.app import create_native_app

pytestmark = [pytest.mark.unit]
ORG = "11111111-1111-4111-8111-111111111111"
REQUEST = "99999999-9999-4999-8999-999999999999"
PAGE = f"/tenants/{ORG}/permissions-update"


@cache
def _runtime_openapi() -> dict[str, Any]:
    app = create_native_app(
        session_factory=cast(Any, object()),
        native_identity_authority_id=UUID(ORG),
        appointment_option_signing_key=b"owner-permissions-console-key-32b",
    )
    return app.openapi()


def _ok(payload: object, status: int = 200) -> ControlResponse:
    return ControlResponse(status, payload, {})


def _readiness(control: str) -> ControlResponse:
    return _ok({"tenant_control": {"status": control, "blockers": []}})


class _Upstream:
    def __init__(self, routes: dict[tuple[str, str], ControlResponse]) -> None:
        self.routes = {
            ("GET", "/v1/me/authority"): _ok(
                {"principal_id": ORG, "authority_revision": 72, "representations": []}
            ),
            **routes,
        }
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def openapi(self) -> dict[str, Any]:
        return _runtime_openapi()

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        self.calls.append((method, path, kwargs))
        if path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": "verified-token"}, {})
        return self.routes.get((method, path), ControlResponse(404, {}, {}))

    async def aclose(self) -> None:
        pass

    def posted(self, path: str) -> list[dict[str, Any]]:
        return [kw for m, p, kw in self.calls if (m, p) == ("POST", path)]


def _console(tmp_path: Path, runtime: _Upstream) -> FastAPI:
    settings = AdminConsoleSettings(
        session_store_directory=tmp_path / "sessions",
        control_api_base_url="http://control",
        runtime_api_base_url="http://runtime",
        session_secret=SecretStr("test-session-secret-with-at-least-32-characters"),
        cookie_secure=False,
    )
    return create_admin_console_app(settings, client=_Upstream({}), runtime_client=runtime)


@asynccontextmanager
async def _signed_in(runtime: _Upstream, tmp_path: Path) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_console(tmp_path, runtime)),
        base_url="http://console",
        headers={"Origin": "http://console"},
    ) as client:
        await client.post("/login", data={"login_handle": "owner", "password": "password"})
        yield client


def _csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


@pytest.mark.asyncio
async def test_outdated_owner_requests_upgrade_without_typing_internal_numbers(
    tmp_path: Path,
) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/onboarding/readiness"): _readiness("blocked"),
            ("POST", "/v1/controller-policy-adoptions"): _ok(
                {"request_id": REQUEST, "status": "pending"}, status=201
            ),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        page = await client.get(PAGE)
        assert page.status_code == 200, page.text
        assert "New owner permissions are available" in page.text
        # The owner's own revision is read for them, never typed.
        assert 'type="hidden" name="expected_authority_revision" value="72"' in page.text
        assert "Expected Authority Revision" not in page.text
        response = await client.post(
            PAGE,
            data={
                "csrf_token": _csrf(page.text),
                "_intent_id": "adopt-intent-0001",
                "expected_authority_revision": "72",
                "reason": "Use the latest owner permissions for this business.",
            },
        )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"{PAGE}?requested={REQUEST}"
    (call,) = runtime.posted("/v1/controller-policy-adoptions")
    assert call["json_body"] == {
        "expected_authority_revision": 72,
        "reason": "Use the latest owner permissions for this business.",
    }
    assert call["extra_headers"]["idempotency-key"] == "adopt-intent-0001"
    assert call["extra_headers"]["X-RE-Organization-ID"] == ORG


@pytest.mark.asyncio
async def test_pending_request_tells_owner_to_wait_for_approval(tmp_path: Path) -> None:
    runtime = _Upstream(
        {
            ("GET", "/v1/onboarding/readiness"): _readiness("blocked"),
            ("GET", f"/v1/controller-policy-adoptions/{REQUEST}"): _ok(
                {"request_id": REQUEST, "status": "pending"}
            ),
        }
    )
    async with _signed_in(runtime, tmp_path) as client:
        page = await client.get(f"{PAGE}?requested={REQUEST}")
    assert page.status_code == 200, page.text
    assert "Upgrade requested" in page.text
    assert "Request the upgrade" not in page.text


@pytest.mark.asyncio
async def test_current_owner_is_told_nothing_is_needed(tmp_path: Path) -> None:
    runtime = _Upstream({("GET", "/v1/onboarding/readiness"): _readiness("ready")})
    async with _signed_in(runtime, tmp_path) as client:
        page = await client.get(PAGE)
    assert page.status_code == 200, page.text
    assert "You have the latest owner permissions" in page.text
    assert runtime.posted("/v1/controller-policy-adoptions") == []
