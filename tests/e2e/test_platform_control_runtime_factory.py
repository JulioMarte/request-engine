import asyncio
import socket
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from uvicorn import Config, Server

from request_engine.bootstrap.platform_server import create_app
from request_engine.platform.db.session import SessionFactory

from .conftest import PgConnection, RuntimeCredentials

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security]


@pytest.mark.asyncio
async def test_private_runtime_requires_its_selected_policy_version(
    private_runtime_configuration: tuple[UUID, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert private_runtime_configuration[0]
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://private.test") as client,
    ):
        assert (await client.get("/health/ready")).status_code == 200
        # A future binary selecting an absent policy must fail closed despite
        # the selector function being present and callable. Do not edit catalog history.
        monkeypatch.setattr(
            "request_engine.bootstrap.platform_server.NATIVE_INITIAL_CONTROLLER_POLICY",
            "not-installed-controller-policy",
        )
        unavailable = await client.get("/health/ready")
        assert unavailable.status_code == 503 and unavailable.json() == {"status": "unavailable"}
        assert (await client.get("/health/live")).status_code == 200
    restarted = create_app()
    with pytest.raises(SQLAlchemyError):
        async with restarted.router.lifespan_context(restarted):
            pytest.fail("private runtime accepted an absent selected policy")


@pytest.fixture
def private_runtime_configuration(
    e2e_admin_conn: PgConnection,
    app_runtime_credentials: RuntimeCredentials,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, str, str]:
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"private-http-{authority_id}"),
    )
    monkeypatch.setenv("REQUEST_ENGINE_DATABASE_URL", app_runtime_credentials.database_url)
    monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", str(authority_id))
    read_engine = platform_read_session_factory.kw["bind"]
    write_engine = platform_control_session_factory.kw["bind"]
    assert isinstance(read_engine, AsyncEngine) and isinstance(write_engine, AsyncEngine)
    monkeypatch.setenv(
        "REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL",
        read_engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setenv(
        "REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL",
        write_engine.url.render_as_string(hide_password=False),
    )
    assert read_engine.url.username is not None and write_engine.url.username is not None
    return authority_id, read_engine.url.username, write_engine.url.username


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    [
        "membership",
        "table",
        "function",
        "authority",
        "write_function",
        "write_table",
        "write_membership",
    ],
)
async def test_private_runtime_rechecks_privileges_and_authority(
    e2e_admin_conn: PgConnection,
    private_runtime_configuration: tuple[UUID, str, str],
    drift: str,
) -> None:
    authority_id, read_role, write_role = private_runtime_configuration
    target_role = write_role if drift.startswith("write_") else read_role
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://private-control.test"
        ) as client,
    ):
        assert (await client.get("/health/ready")).json() == {"status": "ready"}
        assert "/v1/platform/organizations" in app.openapi()["paths"]
        assert "/v1/staff/members" not in app.openapi()["paths"]
        denied = await client.post("/v1/platform/provisioners", json={})
        assert denied.status_code == 401
        if drift.endswith("membership"):
            e2e_admin_conn.execute(
                sql.SQL("GRANT pg_read_all_data TO {} WITH INHERIT FALSE").format(
                    sql.Identifier(target_role)
                )
            )
        elif drift.endswith("table"):
            e2e_admin_conn.execute(
                sql.SQL("GRANT SELECT (id) ON request_engine.principals TO {}").format(
                    sql.Identifier(target_role)
                )
            )
        elif drift == "write_function":
            e2e_admin_conn.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION "
                    "request_platform.read_principal_authority(uuid) TO {}"
                ).format(sql.Identifier(target_role))
            )
        elif drift == "function":
            e2e_admin_conn.execute(
                sql.SQL(
                    "GRANT EXECUTE ON FUNCTION request_platform.provision_tenant_provisioner"
                    "(uuid,text,text) TO {}"
                ).format(sql.Identifier(target_role))
            )
        else:
            e2e_admin_conn.execute(
                "UPDATE request_engine.identity_authorities SET status='disabled', "
                "revision=revision+1 WHERE id=%s",
                (authority_id,),
            )
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        assert response.headers["Cache-Control"] == "no-store"
        assert (await client.get("/health/live")).status_code == 200
    restarted = create_app()
    with pytest.raises(RuntimeError):
        async with restarted.router.lifespan_context(restarted):
            pytest.fail("Private control accepted a drifted privilege/authority boundary")


@pytest.mark.asyncio
async def test_private_control_runtime_serves_real_tcp(
    private_runtime_configuration: tuple[UUID, str, str],
) -> None:
    assert private_runtime_configuration[0]
    server = Server(Config(create_app(), log_level="error", access_log=False))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if serving.done():
                        await serving
                        pytest.fail("Private HTTP server exited before startup")
                    await asyncio.sleep(0.01)
            async with AsyncClient(
                base_url=f"http://127.0.0.1:{listener.getsockname()[1]}"
            ) as client:
                assert (await client.get("/health/ready")).status_code == 200
                schema = (await client.get("/openapi.json")).json()
                operation = schema["paths"]["/v1/platform/organizations"]["post"]
                assert operation["operationId"] == "platform_native_organization_create"
                assert operation["security"] == [{"NativeSessionBearer": []}]
                enrolled = await client.post(
                    "/auth/native/identities",
                    json={
                        "login_handle": "tcp-native@example.test",
                        "password": "tcp proof password",
                    },
                )
                assert enrolled.status_code == 201
                denied = await client.post("/v1/platform/organizations", json={})
                assert denied.status_code == 401
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, timeout=15)


@pytest.mark.asyncio
async def test_private_runtime_rejects_auth_login_with_direct_platform_grant(
    e2e_admin_conn: PgConnection,
    app_runtime_credentials: RuntimeCredentials,
    private_runtime_configuration: tuple[UUID, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert private_runtime_configuration[0]
    role = f"re_private_auth_proof_{uuid4().hex}"
    password = uuid4().hex
    e2e_admin_conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE request_engine_app").format(
            sql.Identifier(role), sql.Literal(password)
        )
    )
    try:
        e2e_admin_conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA request_platform TO {}").format(sql.Identifier(role))
        )
        e2e_admin_conn.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION request_platform.read_principal_authority(uuid) TO {}"
            ).format(sql.Identifier(role))
        )
        monkeypatch.setenv(
            "REQUEST_ENGINE_DATABASE_URL",
            make_url(app_runtime_credentials.database_url)
            .set(username=role, password=password)
            .render_as_string(hide_password=False),
        )
        app = create_app()
        with pytest.raises(RuntimeError, match="private platform authority"):
            async with app.router.lifespan_context(app):
                pytest.fail("App auth login bypassed platform-read separation")
    finally:
        e2e_admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        e2e_admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
