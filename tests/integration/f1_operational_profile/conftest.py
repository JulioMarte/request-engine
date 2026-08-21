import os
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from psycopg import Connection

from tests.integration.f1_operational_profile.scenarios import (
    F1OperationalScenario,
    seed_bookable_f1_scenario,
)

PgConnection = Connection[Any]
F1ScenarioFactory = Callable[[str], F1OperationalScenario]


def _conninfo() -> str:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE", "request_engine_f1")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "request_engine")
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
def f1_scenario_factory(admin_conn: PgConnection) -> F1ScenarioFactory:
    def seed(label: str) -> F1OperationalScenario:
        return seed_bookable_f1_scenario(admin_conn, label)

    return seed
