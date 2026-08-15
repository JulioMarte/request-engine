import os
from collections.abc import Iterator
from typing import Any, Protocol

import psycopg
import pytest
from psycopg import Connection, sql

os.environ.setdefault("REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY", "x" * 64)

PgConnection = Connection[Any]


class _PostgresTestNode(Protocol):
    def get_closest_marker(self, name: str) -> object | None: ...


class _FixtureRequest(Protocol):
    @property
    def node(self) -> _PostgresTestNode: ...


def _postgres_conninfo() -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE", "request_engine_v3")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "request_engine")
    return f"host={host} port={port} dbname={database} user={user} password={password}"


@pytest.fixture(autouse=True)
def isolate_postgres_test_data(request: _FixtureRequest) -> Iterator[None]:
    """Give every PostgreSQL proof a clean data state, including reordered runs."""

    if request.node.get_closest_marker("postgres") is None:
        yield
        return

    conn: PgConnection = psycopg.connect(_postgres_conninfo(), autocommit=True)
    try:
        tables = conn.execute(
            """
            SELECT n.nspname, c.relname
            FROM pg_catalog.pg_class AS c
            JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'request_engine'
              AND c.relkind IN ('r', 'p')
            ORDER BY n.nspname, c.relname
            """
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

    yield
