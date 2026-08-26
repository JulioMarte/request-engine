import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from psycopg import Connection

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


@pytest_asyncio.fixture
async def command_session_factory() -> AsyncIterator[SessionFactory]:
    """Real PostgreSQL SessionFactory for application-command concurrency proofs."""
    host, port, database, user, password = _pg_values()
    engine = create_postgres_engine(
        f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
