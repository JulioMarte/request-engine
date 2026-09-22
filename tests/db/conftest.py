import os
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import Connection, sql

from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)

PgConnection = Connection[Any]


def _pg_values() -> tuple[str, str, str, str, str]:
    return (
        os.environ.get("PGHOST", "127.0.0.1"),
        os.environ.get("PGPORT", "5432"),
        os.environ.get("PGDATABASE", "request_engine_v3"),
        os.environ.get("PGUSER", "request_engine"),
        os.environ.get("PGPASSWORD", "request_engine"),
    )


def _conninfo() -> str:
    host, port, database, user, password = _pg_values()
    return f"host={host} port={port} dbname={database} user={user} password={password}"


@pytest.fixture
def pg_conninfo() -> str:
    return _conninfo()


@pytest.fixture
def admin_conn(pg_conninfo: str) -> Iterator[PgConnection]:
    conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def app_role_conn_factory(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> Iterator[Callable[[], PgConnection]]:
    """Factory for release-shaped app LOGINs used by direct runtime proofs."""

    role_name = f"re_native_app_{uuid4().hex[:12]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN NOBYPASSRLS IN ROLE request_engine_app PASSWORD {}").format(
            sql.Identifier(role_name), sql.Literal(password)
        )
    )
    parts = dict(part.split("=", 1) for part in pg_conninfo.split())
    created: list[PgConnection] = []

    def factory() -> PgConnection:
        conn: PgConnection = psycopg.connect(
            f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
            f"user={role_name} password={password}"
        )
        created.append(conn)
        return conn

    try:
        yield factory
    finally:
        for conn in created:
            conn.close()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


@pytest.fixture
def app_role_conn(
    app_role_conn_factory: Callable[[], PgConnection],
) -> Iterator[PgConnection]:
    """One sync release-shaped app LOGIN for direct function-level proofs."""

    yield app_role_conn_factory()


@pytest.fixture
def platform_read_conn_factory(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> Iterator[Callable[[], PgConnection]]:
    """Factory for release-shaped least-privilege platform read LOGINs."""

    role_name = f"re_platform_read_{uuid4().hex[:12]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    for signature in (
        "request_platform.read_platform_configuration_revisions(text)",
        "request_platform.read_platform_secret_binding(uuid)",
    ):
        admin_conn.execute(
            sql.SQL("GRANT EXECUTE ON FUNCTION " + signature + " TO {}").format(
                sql.Identifier(role_name)
            )
        )
    admin_conn.execute(
        sql.SQL("GRANT USAGE ON SCHEMA request_platform TO {}").format(
            sql.Identifier(role_name)
        )
    )

    parts = dict(part.split("=", 1) for part in pg_conninfo.split())
    created: list[PgConnection] = []

    def factory() -> PgConnection:
        conn: PgConnection = psycopg.connect(
            f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
            f"user={role_name} password={password}"
        )
        created.append(conn)
        return conn

    try:
        yield factory
    finally:
        for conn in created:
            conn.close()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


@pytest.fixture
def platform_control_conn_factory(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> Iterator[Callable[[], PgConnection]]:
    """Factory for release-shaped ``request_platform_control`` LOGINs."""

    role_name = f"re_platform_control_{uuid4().hex[:12]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOBYPASSRLS IN ROLE request_platform_control PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    parts = dict(part.split("=", 1) for part in pg_conninfo.split())
    created: list[PgConnection] = []

    def factory() -> PgConnection:
        conn: PgConnection = psycopg.connect(
            f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
            f"user={role_name} password={password}"
        )
        created.append(conn)
        return conn

    try:
        yield factory
    finally:
        for conn in created:
            conn.close()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


@pytest_asyncio.fixture
async def command_session_factory() -> AsyncIterator[SessionFactory]:
    """Execute command races through a release-shaped app LOGIN and RLS."""
    host, port, database, _user, _password = _pg_values()
    role_name = f"request_engine_app_f3_{uuid4().hex[:16]}"
    role_password = uuid4().hex
    admin = psycopg.connect(_conninfo(), autocommit=True)
    try:
        admin.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
            ).format(sql.Identifier(role_name), sql.Literal(role_password))
        )
        admin.execute(sql.SQL("GRANT request_engine_app TO {}").format(sql.Identifier(role_name)))
    finally:
        admin.close()

    engine = create_postgres_engine(
        f"postgresql+asyncpg://{role_name}:{role_password}@{host}:{port}/{database}"
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
        admin = psycopg.connect(_conninfo(), autocommit=True)
        try:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        finally:
            admin.close()


def _worker_async_url(pg_conninfo: str, user: str, password: str) -> str:
    parts = dict(part.split("=", 1) for part in pg_conninfo.split())
    return (
        f"postgresql+asyncpg://{user}:{password}@{parts['host']}:{parts['port']}/{parts['dbname']}"
    )


@pytest_asyncio.fixture
async def worker_session_factory(pg_conninfo: str) -> AsyncIterator[SessionFactory]:
    """Run sweep discovery through a release-shaped worker LOGIN."""

    role_name = f"request_engine_worker_sweep_{uuid4().hex[:10]}"
    role_password = uuid4().hex
    admin = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE request_engine_worker").format(
                sql.Identifier(role_name), sql.Literal(role_password)
            )
        )
    finally:
        admin.close()

    engine = create_postgres_engine(_worker_async_url(pg_conninfo, role_name, role_password))
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
        admin = psycopg.connect(pg_conninfo, autocommit=True)
        try:
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        finally:
            admin.close()
