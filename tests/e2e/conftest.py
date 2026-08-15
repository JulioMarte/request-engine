from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

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


@dataclass(frozen=True, slots=True)
class RuntimeCredentials:
    role_name: str
    password: str
    database_url: str


def _pg_values() -> tuple[str, str, str, str, str]:
    return (
        os.environ.get("PGHOST", "127.0.0.1"),
        os.environ.get("PGPORT", "5432"),
        os.environ.get("PGDATABASE", "request_engine_v3"),
        os.environ.get("PGUSER", "request_engine"),
        os.environ.get("PGPASSWORD", "request_engine"),
    )


@pytest.fixture(scope="session")
def e2e_admin_conn() -> Iterator[PgConnection]:
    host, port, database, user, password = _pg_values()
    conn: PgConnection = psycopg.connect(
        f"host={host} port={port} dbname={database} user={user} password={password}",
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


def _runtime_credentials(
    conn: PgConnection,
    *,
    parent_role: str,
) -> RuntimeCredentials:
    host, port, database, _, _ = _pg_values()
    role_name = f"re_e2e_{parent_role.removeprefix('request_engine_')}_{secrets.token_hex(6)}"
    password = secrets.token_urlsafe(24)
    conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {} NOBYPASSRLS").format(
            sql.Identifier(role_name),
            sql.Literal(password),
            sql.Identifier(parent_role),
        )
    )
    database_url = (
        f"postgresql+asyncpg://{quote_plus(role_name)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )
    return RuntimeCredentials(
        role_name=role_name,
        password=password,
        database_url=database_url,
    )


def _drop_runtime_role(conn: PgConnection, credentials: RuntimeCredentials) -> None:
    conn.execute(
        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(credentials.role_name))
    )


@pytest.fixture(scope="session")
def app_runtime_credentials(
    e2e_admin_conn: PgConnection,
) -> Iterator[RuntimeCredentials]:
    credentials = _runtime_credentials(
        e2e_admin_conn,
        parent_role="request_engine_app",
    )
    try:
        yield credentials
    finally:
        _drop_runtime_role(e2e_admin_conn, credentials)


@pytest.fixture(scope="session")
def worker_runtime_credentials(
    e2e_admin_conn: PgConnection,
) -> Iterator[RuntimeCredentials]:
    credentials = _runtime_credentials(
        e2e_admin_conn,
        parent_role="request_engine_worker",
    )
    try:
        yield credentials
    finally:
        _drop_runtime_role(e2e_admin_conn, credentials)


@pytest_asyncio.fixture(scope="session")
async def e2e_session_factory(
    app_runtime_credentials: RuntimeCredentials,
) -> AsyncIterator[SessionFactory]:
    engine = create_postgres_engine(app_runtime_credentials.database_url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
