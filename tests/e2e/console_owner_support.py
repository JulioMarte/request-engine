"""A real fresh clinic owner signed in to the operator console over the real runtime.

The owner is a real native identity of an organization root provisioned with a
named tenant controller policy, so every grant and Party representation the
console relies on is the one a real fresh owner holds. Browser-shaped requests
hit the real console ASGI app (session, CSRF, origin check); the console calls
the real native tenant runtime backed by PostgreSQL 18 and the least-privilege
app role. Only the control-plane sign-in exchange is a fixture: it returns that
owner's real runtime bearer.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

from .native_provisioning_support import PgConnection, login, principal_revision, uuid_row

_SIGNING_KEY = b"console-clinic-setup-journey-signing-key-32"


class RuntimePort:
    """Console runtime port over the real tenant runtime ASGI app."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

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
        del setup_bearer
        headers = {"accept": "application/json", **(extra_headers or {})}
        if bearer is not None:
            headers["authorization"] = f"Bearer {bearer}"
        response = await self._client.request(
            method, path, json=json_body, params=params, headers=headers
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text
        return ControlResponse(
            response.status_code, payload, {k.lower(): v for k, v in response.headers.items()}
        )

    async def openapi(self) -> dict[str, Any]:
        response = await self._client.get("/openapi.json")
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def aclose(self) -> None:
        pass


class SignInFixture:
    """Control plane stand-in for the sign-in exchange only."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def request(self, method: str, path: str, **_: Any) -> ControlResponse:
        if method == "POST" and path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": self._token}, {})
        return ControlResponse(404, {"error": {"code": "not_found"}}, {})

    async def openapi(self) -> dict[str, Any]:
        return {"paths": {}}

    async def aclose(self) -> None:
        pass


def provision_fresh_clinic(
    conn: PgConnection, authority_id: UUID, native_identity_id: UUID, *, policy: str
) -> tuple[UUID, UUID]:
    provisioner_id = uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"clinic-setup-provisioner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner_id, f"clinic-setup-provisioner:{uuid4().hex}"),
    )
    organization_id, party_id = uuid4(), uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision',%s,false)",
        (str(principal_revision(conn, provisioner_id)),),
    )
    with conn.transaction():
        conn.execute("SET ROLE request_platform_control")
        try:
            conn.execute("SELECT request_platform.select_initial_controller_policy(%s)", (policy,))
            conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    organization_id,
                    f"clinic-setup-{organization_id.hex}",
                    "Centro Médico Duarte",
                    party_id,
                    uuid4(),
                    authority_id,
                    native_identity_id,
                    f"clinic-setup-root:{uuid4().hex}",
                ),
            )
        finally:
            conn.execute("RESET ROLE")
    for setting in ("authenticated_principal_id", "authority_revision"):
        conn.execute(f"RESET request_engine.{setting}")
    return organization_id, party_id


@dataclass(frozen=True)
class OwnerConsole:
    browser: httpx.AsyncClient
    runtime: httpx.AsyncClient
    token: str
    organization_id: UUID
    party_id: UUID


@asynccontextmanager
async def owner_console(
    tmp_path: Path, conn: PgConnection, session_factory: SessionFactory, *, policy: str
) -> AsyncGenerator[OwnerConsole]:
    authority_id = uuid_row(
        conn,
        "INSERT INTO request_engine.identity_authorities(kind,issuer_or_environment) "
        "VALUES ('native',%s) RETURNING id",
        (f"clinic-setup-{uuid4().hex}",),
    )
    handle, password = f"owner-{uuid4().hex}@example.test", f"clinic-owner-{uuid4().hex}"
    identity = await build_native_auth_runtime(session_factory).service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=password
    )
    organization_id, party_id = provision_fresh_clinic(
        conn, authority_id, identity.native_identity_id, policy=policy
    )
    runtime_app = create_native_app(
        session_factory=session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app), base_url="http://runtime"
    ) as runtime:
        token = await login(runtime, login_handle=handle, password=password)
        console = create_admin_console_app(
            AdminConsoleSettings(
                session_store_directory=tmp_path / "sessions",
                control_api_base_url="http://control",
                runtime_api_base_url="http://runtime",
                session_secret=SecretStr("e2e-clinic-setup-session-secret-32-plus-chars"),
                cookie_secure=False,
            ),
            client=SignInFixture(token),
            runtime_client=RuntimePort(runtime),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=console),
            base_url="http://console",
            headers={"Origin": "http://console"},
        ) as browser:
            signed = await browser.post("/login", data={"login_handle": "owner", "password": "x"})
            assert signed.status_code == 303, signed.text
            yield OwnerConsole(browser, runtime, token, organization_id, party_id)


def csrf(text: str) -> str:
    match = re.search(r'data-csrf="([^"]+)"', text)
    assert match is not None
    return match.group(1)
