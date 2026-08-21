import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo

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
