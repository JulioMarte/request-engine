"""Public HTTP journey for native-session reauthentication freshness (D2 prerequisite).

Real PostgreSQL 18, real ASGI HTTP and the real platform control runtime. Direct
SQL only builds valid preconditions and inspects durable authoritative state.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from psycopg.conninfo import make_conninfo

from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.security,
    pytest.mark.invariant,
]

_REAUTH_PATH = "/auth/native/sessions:reauth"
_REAUTH_WINDOW_SECONDS = 300


def _bootstrap_root(
    admin_conn: PgConnection,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provenance: str,
) -> tuple[UUID, UUID, str, str]:
    monkeypatch.setenv(
        "REQUEST_ENGINE_BOOTSTRAP_DSN",
        make_conninfo(
            host=admin_conn.info.host,
            port=admin_conn.info.port,
            dbname=admin_conn.info.dbname,
            user=admin_conn.info.user,
            password=os.environ.get("PGPASSWORD", "request_engine"),
        ),
    )
    intent = dict(
        line.split(": ", 1)
        for line in issue_intent(ttl_minutes=5, provenance=provenance).splitlines()
    )
    authority_id = UUID(intent["Native authority"])
    login_handle = f"reauth-root-{uuid4().hex}@example.test"
    password = "root native reauth proof password"
    root_id = establish_root(
        login_handle=login_handle,
        password=password,
        raw_token=intent["ONE-TIME BOOTSTRAP TOKEN"],
    )
    return authority_id, root_id, login_handle, password


@pytest.mark.asyncio
async def test_native_session_reauth_http_refreshes_freshness_and_fails_closed(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _root_id, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-native-session-reauth-freshness",
    )
    app = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=authority_id,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": root_handle, "password": root_password},
        )
        assert login.status_code == 201, login.text
        token = str(login.json()["access_token"])
        session_id = UUID(token.split(".", 1)[0])
        before = e2e_admin_conn.execute(
            "SELECT last_authenticated_at FROM request_engine.native_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()
        assert before is not None

        no_bearer = await client.post(_REAUTH_PATH, json={"password": root_password})
        assert no_bearer.status_code == 401

        await asyncio.sleep(0.01)
        reauth = await client.post(
            _REAUTH_PATH,
            headers={"Authorization": f"Bearer {token}"},
            json={"password": root_password},
        )
        assert reauth.status_code == 200, reauth.text
        body = reauth.json()
        authenticated_at = datetime.fromisoformat(body["authenticated_at"])
        reauth_expires_at = datetime.fromisoformat(body["reauth_expires_at"])
        assert authenticated_at > before[0]
        assert (reauth_expires_at - authenticated_at).total_seconds() == _REAUTH_WINDOW_SECONDS

        after = e2e_admin_conn.execute(
            "SELECT last_authenticated_at, last_seen_at IS NOT NULL "
            "FROM request_engine.native_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()
        assert after == (authenticated_at, True)

        wrong = await client.post(
            _REAUTH_PATH,
            headers={"Authorization": f"Bearer {token}"},
            json={"password": "definitely the wrong password"},
        )
        assert wrong.status_code == 401
        assert wrong.json()["error"]["code"] == "credential_invalid"
        unchanged = e2e_admin_conn.execute(
            "SELECT last_authenticated_at FROM request_engine.native_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()
        assert unchanged == (authenticated_at,)

        schema = (await client.get("/openapi.json")).json()
        operation = schema["paths"][_REAUTH_PATH]["post"]
        assert operation["operationId"] == "nativeSessionReauthenticate"


@pytest.mark.asyncio
async def test_password_only_recovery_requires_explicit_current_password_completion(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _root_id, handle, password = _bootstrap_root(
        e2e_admin_conn, monkeypatch, provenance="password-only-recovery-completion"
    )
    app = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=authority_id,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        login = await client.post(
            "/auth/native/sessions", json={"login_handle": handle, "password": password}
        )
        assert login.status_code == 201, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        issued = await client.post("/auth/native/sessions/current/recovery-codes", headers=headers)
        assert issued.status_code == 201, issued.text
        recovered_password = "new password after offline recovery"
        # Exhaust the set through the actual recovery operation. Completion must
        # remain possible when the last available code was needed for recovery.
        for code in issued.json()["codes"]:
            recovered = await client.post(
                "/auth/native/password:recover-with-code",
                json={"recovery_code": code, "new_password": recovered_password},
            )
            assert recovered.status_code == 204, recovered.text
        recovered_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": recovered_password},
        )
        assert recovered_login.status_code == 201, recovered_login.text
        token = recovered_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        before = await client.get("/auth/native/sessions/current", headers=headers)
        assert before.json()["recovery_restricted"] is True
        denied_reauth = await client.post(
            _REAUTH_PATH, headers=headers, json={"password": recovered_password}
        )
        assert denied_reauth.status_code == 403
        assert denied_reauth.json()["error"]["code"] == "recovery_completion_required"
        wrong = await client.post(
            "/auth/native/sessions/current/recovery:complete",
            headers=headers,
            json={"password": "incorrect"},
        )
        assert wrong.status_code == 401
        readiness = await client.get(
            "/auth/native/sessions/current/recovery-readiness", headers=headers
        )
        assert readiness.json()["recovery_state"] == "recovery_restricted"
        assert readiness.json()["remaining_codes"] == 0
        assert readiness.json()["active_webauthn_credentials"] == 0
        completed = await client.post(
            "/auth/native/sessions/current/recovery:complete",
            headers=headers,
            json={"password": recovered_password},
        )
        assert completed.status_code == 200, completed.text
        assert completed.headers["cache-control"] == "no-store"
        assert completed.json()["recovery_state"] == "normal"
        after = await client.get("/auth/native/sessions/current", headers=headers)
        for fact in ("authentication_methods", "authentication_assurance", "recovery_derived"):
            assert after.json()[fact] == before.json()[fact]
        normal_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": recovered_password},
        )
        assert normal_login.status_code == 201
        normal_headers = {"Authorization": f"Bearer {normal_login.json()['access_token']}"}
        replenished = await client.post(
            "/auth/native/sessions/current/recovery-codes", headers=normal_headers
        )
        assert replenished.status_code == 201, replenished.text
