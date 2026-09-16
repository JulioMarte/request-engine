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
