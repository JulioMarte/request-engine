import os
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
import pytest_asyncio

from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)


def _pg_values() -> tuple[str, str, str, str, str]:
    return (
        os.environ.get("PGHOST", "127.0.0.1"),
        os.environ.get("PGPORT", "5432"),
        os.environ.get("PGDATABASE", "request_engine_v3"),
        os.environ.get("PGUSER", "request_engine"),
        os.environ.get("PGPASSWORD", "request_engine"),
    )


@pytest.fixture(scope="session")
def pg_admin_dsn() -> str:
    host, port, database, user, password = _pg_values()
    return f"host={host} port={port} dbname={database} user={user} password={password}"


@pytest.fixture(scope="session")
def pg_admin_conn(pg_admin_dsn: str) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(pg_admin_dsn, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest_asyncio.fixture
async def pg_session_factory(pg_admin_dsn: str) -> AsyncIterator[SessionFactory]:
    host, port, database, user, password = _pg_values()
    engine = create_postgres_engine(
        f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
