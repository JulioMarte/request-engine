from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, unquote, urlsplit

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
_RUNTIME_DATABASE_URLS = {
    "request_engine_app": "REQUEST_ENGINE_APP_DATABASE_URL",
    "request_engine_worker": "REQUEST_ENGINE_WORKER_DATABASE_URL",
}


@dataclass(frozen=True, slots=True)
class RuntimeCredentials:
    role_name: str
    password: str
    database_url: str
    domain_database_url: str | None = None


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


def _preprovisioned_credentials(parent_role: str) -> RuntimeCredentials | None:
    configured_url = os.environ.get(_RUNTIME_DATABASE_URLS[parent_role])
    if not configured_url:
        return None
    parsed = urlsplit(configured_url)
    if not parsed.username or parsed.password is None:
        raise RuntimeError(f"preprovisioned {parent_role} URL lacks username/password")
    return RuntimeCredentials(
        role_name=unquote(parsed.username),
        password=unquote(parsed.password),
        database_url=configured_url,
    )


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
    conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(credentials.role_name)))


@pytest.fixture(scope="session")
def app_runtime_credentials(
    e2e_admin_conn: PgConnection,
) -> Iterator[RuntimeCredentials]:
    configured = _preprovisioned_credentials("request_engine_app")
    if configured is not None:
        yield configured
        return

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
    app_runtime_credentials: RuntimeCredentials,
) -> Iterator[RuntimeCredentials]:
    configured = _preprovisioned_credentials("request_engine_worker")
    if configured is not None:
        yield RuntimeCredentials(
            role_name=configured.role_name,
            password=configured.password,
            database_url=configured.database_url,
            domain_database_url=app_runtime_credentials.database_url,
        )
        return

    credentials = _runtime_credentials(
        e2e_admin_conn,
        parent_role="request_engine_worker",
    )
    try:
        yield RuntimeCredentials(
            role_name=credentials.role_name,
            password=credentials.password,
            database_url=credentials.database_url,
            domain_database_url=app_runtime_credentials.database_url,
        )
    finally:
        _drop_runtime_role(e2e_admin_conn, credentials)


@pytest_asyncio.fixture
async def e2e_session_factory(
    app_runtime_credentials: RuntimeCredentials,
) -> AsyncIterator[SessionFactory]:
    engine = create_postgres_engine(app_runtime_credentials.database_url)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
