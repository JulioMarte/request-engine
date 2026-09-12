"""Real runtime-login startup, with no external identity provider configured."""

import asyncio
import secrets
import socket
from uuid import uuid4

import pytest
from httpx import AsyncClient
from psycopg import sql
from sqlalchemy.engine import make_url
from uvicorn import Config, Server

from request_engine.bootstrap.server import create_app

from .conftest import PgConnection, RuntimeCredentials

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security]


@pytest.mark.asyncio
async def test_runtime_factory_starts_under_real_app_login(
    e2e_admin_conn: PgConnection,
    app_runtime_credentials: RuntimeCredentials,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_DATABASE_URL", app_runtime_credentials.database_url)
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"runtime-proof-{authority_id}"),
    )
    monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", str(authority_id))
    monkeypatch.setenv("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "a" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY", "b" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_OIDC_ENABLED", "false")
    server = Server(Config(create_app(), log_level="error", access_log=False))
    # Reserve the port until the real ASGI server takes ownership; no free-port race.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if serving.done():
                        await serving
                        pytest.fail("HTTP server exited before startup")
                    await asyncio.sleep(0.01)
            async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                assert (await client.get("/health/ready")).json() == {"status": "ready"}
                assert (await client.get("/health/live")).status_code == 200
                schema = await client.get("/openapi.json")
                assert schema.status_code == 200
                assert "/auth/native/identities" in schema.json()["paths"]
                denied = await client.get("/v1/integrations")
                assert denied.status_code == 401
                e2e_admin_conn.execute(
                    "UPDATE request_engine.identity_authorities "
                    "SET status = 'disabled', revision = revision + 1 WHERE id = %s",
                    (authority_id,),
                )
                unready = await client.get("/health/ready")
                assert unready.status_code == 503
                assert unready.json() == {"status": "unavailable"}
                assert unready.headers["cache-control"] == "no-store"
                assert (await client.get("/health/live")).json() == {"status": "alive"}
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=15)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_role", ["request_engine_worker", "request_platform_definer", "pg_read_all_data"]
)
async def test_runtime_factory_rejects_app_login_with_additional_role_membership(
    e2e_admin_conn: PgConnection,
    app_runtime_credentials: RuntimeCredentials,
    monkeypatch: pytest.MonkeyPatch,
    extra_role: str,
) -> None:
    # Never elevate an operator-supplied/preprovisioned runtime account for a test.
    role_name = f"re_http_role_proof_{uuid4().hex}"
    password = secrets.token_urlsafe(24)
    e2e_admin_conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE request_engine_app").format(
            sql.Identifier(role_name), sql.Literal(password)
        )
    )
    try:
        # Even NOINHERIT membership permits SET ROLE and is unsafe for HTTP.
        e2e_admin_conn.execute(
            sql.SQL("GRANT {} TO {} WITH INHERIT FALSE").format(
                sql.Identifier(extra_role), sql.Identifier(role_name)
            )
        )
        database_url = make_url(app_runtime_credentials.database_url).set(
            username=role_name, password=password
        )
        monkeypatch.setenv(
            "REQUEST_ENGINE_DATABASE_URL", database_url.render_as_string(hide_password=False)
        )
        monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", str(uuid4()))
        monkeypatch.setenv("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "a" * 64)
        monkeypatch.setenv("REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY", "b" * 64)
        monkeypatch.setenv("REQUEST_ENGINE_OIDC_ENABLED", "false")
        app = create_app()
        with pytest.raises(RuntimeError, match="least-privilege"):
            async with app.router.lifespan_context(app):
                pytest.fail("HTTP accepted a login able to assume another database role")
    finally:
        e2e_admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_state", ["absent", "disabled", "oidc"])
async def test_runtime_rejects_unusable_native_authority(
    e2e_admin_conn: PgConnection,
    app_runtime_credentials: RuntimeCredentials,
    monkeypatch: pytest.MonkeyPatch,
    authority_state: str,
) -> None:
    authority_id = uuid4()
    if authority_state != "absent":
        e2e_admin_conn.execute(
            "INSERT INTO request_engine.identity_authorities "
            "(id, kind, status, issuer_or_environment) VALUES (%s, %s, %s, %s)",
            (
                authority_id,
                "oidc" if authority_state == "oidc" else "native",
                "disabled" if authority_state == "disabled" else "active",
                f"runtime-rejected-{authority_id}",
            ),
        )
    monkeypatch.setenv("REQUEST_ENGINE_DATABASE_URL", app_runtime_credentials.database_url)
    monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", str(authority_id))
    monkeypatch.setenv("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "a" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY", "b" * 64)
    monkeypatch.setenv("REQUEST_ENGINE_OIDC_ENABLED", "false")
    app = create_app()
    with pytest.raises(RuntimeError, match="native identity authority is unavailable"):
        async with app.router.lifespan_context(app):
            pytest.fail("HTTP started with an unusable configured authentication authority")
