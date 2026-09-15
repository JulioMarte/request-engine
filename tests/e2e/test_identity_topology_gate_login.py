"""Native login stays available while a global topology EXCLUSIVE is held."""

import os
from typing import Any
from uuid import UUID

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from psycopg.conninfo import make_conninfo

from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security, pytest.mark.invariant]


@pytest.mark.asyncio
async def test_native_login_is_not_blocked_by_the_identity_topology_gate(
    e2e_admin_conn: Connection[Any],
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conninfo = make_conninfo(
        host=e2e_admin_conn.info.host,
        port=e2e_admin_conn.info.port,
        dbname=e2e_admin_conn.info.dbname,
        user=e2e_admin_conn.info.user,
        password=os.environ.get("PGPASSWORD", "request_engine"),
    )
    monkeypatch.setenv("REQUEST_ENGINE_BOOTSTRAP_DSN", conninfo)
    intent = dict(
        line.split(": ", 1)
        for line in issue_intent(
            ttl_minutes=5,
            provenance="identity-topology-gate-login-proof",
        ).splitlines()
    )
    authority_id = UUID(intent["Native authority"])
    establish_root(
        login_handle="gate-root@example.test",
        password="gate root proof password",
        raw_token=intent["ONE-TIME BOOTSTRAP TOKEN"],
    )
    app = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=authority_id,
    )

    locker = psycopg.connect(conninfo)
    try:
        locker.execute("SELECT request_engine.acquire_identity_topology_exclusive()")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://control.test"
        ) as client:
            login = await client.post(
                "/auth/native/sessions",
                json={
                    "login_handle": "gate-root@example.test",
                    "password": "gate root proof password",
                },
            )
            assert login.status_code == 201, login.text
    finally:
        locker.rollback()
        locker.close()
