"""HTTP containment is enforced by PostgreSQL, and failed work releases locks."""

import asyncio
import os
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection, sql
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from request_engine.platform.db.execution_budget import PostgresExecutionBudget
from request_engine.platform.db.session import create_postgres_engine

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


@pytest.fixture
def bounded_database_url(admin_conn: Connection[Any], driver: str) -> Iterator[str]:
    # Technical query/lock evidence under an unprivileged login, not an owner
    # command proof or a claim about the application's complete ACL inventory.
    name, password = f"re_budget_{uuid4().hex[:16]}", uuid4().hex
    admin_conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
            sql.Identifier(name), sql.Literal(password)
        )
    )
    url = URL.create(
        f"postgresql+{driver}",
        username=name,
        password=password,
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        database=os.environ.get("PGDATABASE", "request_engine_v3"),
    )
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


@asynccontextmanager
async def _bounded_engine(url: str) -> AsyncGenerator[AsyncEngine]:
    engine = create_postgres_engine(
        url,
        budget=PostgresExecutionBudget(
            statement_ms=80, lock_ms=20, transaction_ms=5000, idle_transaction_ms=5000
        ),
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.parametrize("driver", ["asyncpg", "psycopg"])
def test_statement_timeout_rolls_back_and_releases_transaction_lock(
    bounded_database_url: str,
) -> None:
    # Psycopg requires SelectorEventLoop on Windows. Keep this loop local to
    # this proof rather than changing other tests' process-global policy.
    asyncio.run(_statement_timeout(bounded_database_url), loop_factory=asyncio.SelectorEventLoop)


async def _statement_timeout(url: str) -> None:
    key = uuid4().int & ((1 << 63) - 1)
    async with (
        _bounded_engine(url) as engine,
        engine.connect() as operation,
        engine.connect() as observer,
    ):
        assert await operation.scalar(text("SHOW statement_timeout")) == "80ms"
        assert await operation.scalar(text("SHOW lock_timeout")) == "20ms"
        assert await operation.scalar(text("SHOW transaction_timeout")) == "5s"
        assert await operation.scalar(text("SHOW idle_in_transaction_session_timeout")) == "5s"
        await operation.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        assert not await observer.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}
        )
        with pytest.raises(DBAPIError) as failure:
            await operation.execute(text("SELECT pg_sleep(1)"))
        assert getattr(failure.value.orig, "sqlstate", None) == "57014"
        await operation.rollback()
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
        assert await operation.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("driver", ["asyncpg", "psycopg"])
def test_lock_timeout_is_distinct_and_does_not_disturb_winner(bounded_database_url: str) -> None:
    asyncio.run(_lock_timeout(bounded_database_url), loop_factory=asyncio.SelectorEventLoop)


async def _lock_timeout(url: str) -> None:
    key = uuid4().int & ((1 << 63) - 1)
    async with (
        _bounded_engine(url) as engine,
        engine.connect() as winner,
        engine.connect() as loser,
    ):
        await winner.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        with pytest.raises(DBAPIError) as failure:
            await loser.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        assert getattr(failure.value.orig, "sqlstate", None) == "55P03"
        await loser.rollback()
        assert not await loser.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
        await winner.rollback()
        assert await loser.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key})
