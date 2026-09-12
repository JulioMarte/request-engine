import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy.engine import URL

from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)

os.environ.setdefault("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "x" * 64)

PgConnection = Connection[Any]
APPLICATION_SCHEMAS = ("request_engine", "request_read", "request_cmd", "request_admin")
TEST_ROOT = Path(__file__).resolve().parent


class _PostgresTestNode(Protocol):
    def get_closest_marker(self, name: str) -> object | None: ...


class _FixtureRequest(Protocol):
    @property
    def node(self) -> _PostgresTestNode: ...


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify evidence by scope without child conftest/import ambiguity."""
    for item in items:
        item_path = Path(item.path).resolve()
        try:
            relative = item_path.relative_to(TEST_ROOT)
        except ValueError:
            continue
        if not relative.parts:
            continue
        if relative.parts[0] == "architecture":
            item.add_marker(pytest.mark.fitness)
        elif relative.parts[0] == "historical":
            item.add_marker(pytest.mark.historical)


def postgres_test_conninfo() -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE", "request_engine_v3")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "request_engine")
    return make_conninfo(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
        connect_timeout=5,
        application_name="request-engine-pytest-isolation",
    )


def _platform_test_url(role_name: str, password: str) -> str:
    config = conninfo_to_dict(postgres_test_conninfo())
    return URL.create(
        "postgresql+asyncpg",
        username=role_name,
        password=password,
        host=str(config["host"]),
        port=int(str(config["port"])),
        database=str(config["dbname"]),
    ).render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def platform_read_session_factory() -> AsyncIterator[SessionFactory]:
    """Separate LOGIN can execute the platform projection, not read/write tables."""
    role_name = f"re_platform_read_{uuid4().hex[:16]}"
    role_password = uuid4().hex
    admin = psycopg.connect(postgres_test_conninfo(), autocommit=True)
    engine = None
    try:
        admin.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOINHERIT NOBYPASSRLS NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
            ).format(sql.Identifier(role_name), sql.Literal(role_password))
        )
        admin.execute(
            sql.SQL("GRANT USAGE ON SCHEMA request_platform TO {}").format(
                sql.Identifier(role_name)
            )
        )
        admin.execute(
            sql.SQL(
                "GRANT EXECUTE ON FUNCTION request_platform.read_principal_authority(uuid) TO {}"
            ).format(sql.Identifier(role_name))
        )
        engine = create_postgres_engine(_platform_test_url(role_name, role_password))
        yield create_session_factory(engine)
    finally:
        if engine is not None:
            await engine.dispose()
        admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        admin.close()


@pytest_asyncio.fixture
async def platform_control_session_factory() -> AsyncIterator[SessionFactory]:
    """Write commands use a separate non-superuser platform-control LOGIN."""
    role_name = f"re_platform_control_{uuid4().hex[:16]}"
    role_password = uuid4().hex
    admin = psycopg.connect(postgres_test_conninfo(), autocommit=True)
    admin.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE request_platform_control").format(
            sql.Identifier(role_name), sql.Literal(role_password)
        )
    )
    engine = create_postgres_engine(_platform_test_url(role_name, role_password))
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
        admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        admin.close()


@pytest.fixture(autouse=True)
def isolate_postgres_test_data(request: _FixtureRequest) -> Iterator[None]:
    """Give every PostgreSQL proof a clean data state and fail fast on leaked locks."""

    if request.node.get_closest_marker("postgres") is None:
        yield
        return

    def truncate() -> None:
        conn: PgConnection = psycopg.connect(postgres_test_conninfo(), autocommit=True)
        try:
            conn.execute("SET lock_timeout = '5s'")
            conn.execute("SET statement_timeout = '30s'")
            tables = conn.execute(
                """
                SELECT n.nspname, c.relname
                FROM pg_catalog.pg_class AS c
                JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname::text = ANY (%s)
                  AND c.relkind IN ('r', 'p')
                  AND NOT c.relispartition
                  -- Migration-defined immutable policy is configuration, not
                  -- test-created business state or a seeded command result.
                  AND NOT (n.nspname = 'request_engine'
                           AND c.relname = 'initial_controller_policies')
                ORDER BY n.nspname, c.relname
                """,
                (list(APPLICATION_SCHEMAS),),
            ).fetchall()
            if tables:
                conn.execute(
                    sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                        sql.SQL(", ").join(
                            sql.Identifier(schema_name, table_name)
                            for schema_name, table_name in tables
                        )
                    )
                )
        finally:
            conn.close()

    truncate()
    try:
        yield
    finally:
        # The second reset is intentional. It proves a test cannot silently leave
        # authoritative rows or an open lock behind for the next proof.
        truncate()
