import os
from collections.abc import AsyncIterator, Iterator
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


def _admin_connection() -> PgConnection:
    host, port, database, user, password = _pg_values()
    return psycopg.connect(
        f"host={host} port={port} dbname={database} user={user} password={password}",
        autocommit=True,
    )


@pytest.fixture
def admin_conn() -> Iterator[PgConnection]:
    conn = _admin_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[SessionFactory]:
    host, port, database, user, password = _pg_values()
    engine = create_postgres_engine(
        f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def app_session_factory() -> AsyncIterator[SessionFactory]:
    """Use a real LOGIN that inherits only the application runtime role."""

    host, port, database, _, _ = _pg_values()
    role_name = f"request_engine_app_test_{uuid4().hex[:16]}"
    password = uuid4().hex

    admin = _admin_connection()
    admin.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin.execute(sql.SQL("GRANT request_engine_app TO {}").format(sql.Identifier(role_name)))
    admin.close()

    engine = create_postgres_engine(
        f"postgresql+asyncpg://{role_name}:{password}@{host}:{port}/{database}"
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
        admin = _admin_connection()
        try:
            admin.execute(
                sql.SQL("REASSIGN OWNED BY {} TO request_engine_schema_owner").format(
                    sql.Identifier(role_name)
                )
            )
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        finally:
            admin.close()
