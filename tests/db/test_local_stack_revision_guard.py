"""Real PostgreSQL regression for clean startup and non-destructive lineage refusal.

The guard must accept an absent/empty Alembic table, accept a known revision and
refuse a retired revision without changing either migration state or existing data.
A CASE containing a reference to an absent table must fail the clean-world case.
"""

import argparse
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import LiteralString, Protocol, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

pytestmark = [pytest.mark.postgres, pytest.mark.contract]
ROOT = Path(__file__).resolve().parents[2]


class RevisionGuard(Protocol):
    def require_known_revision(self) -> None: ...


@pytest.mark.parametrize("revision", [None, "", "0001_initial", "0047_reservation_calendar_read"])
def test_revision_guard_preserves_empty_current_and_retired_databases(
    revision: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", [str(ROOT / "scripts" / "dev"), *sys.path])
    namespace = runpy.run_path(str(ROOT / "scripts" / "dev" / "local_stack.py"))
    factory = cast(Callable[[argparse.Namespace], RevisionGuard], namespace["Stack"])
    stack = factory(argparse.Namespace(project="revision-guard-test"))
    database = f"re_revision_guard_{uuid4().hex}"
    with psycopg.connect(dbname="postgres", autocommit=True) as cluster:
        assert cluster.info.server_version >= 180000
        cluster.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            with psycopg.connect(dbname=database, autocommit=True) as conn:
                conn.execute("CREATE TABLE preserved_data (value text)")
                conn.execute("INSERT INTO preserved_data VALUES ('keep this state')")
                if revision is not None:
                    conn.execute("CREATE TABLE public.alembic_version (version_num varchar(64))")
                    if revision:
                        conn.execute("INSERT INTO public.alembic_version VALUES (%s)", (revision,))

                def psql(_self: object, query: LiteralString) -> str:
                    row = conn.execute(sql.SQL(query)).fetchone()
                    assert row is not None
                    value = row[0]
                    return "t" if value is True else "f" if value is False else str(value or "")

                monkeypatch.setattr(type(stack), "psql", psql)
                if revision == "0047_reservation_calendar_read":
                    with pytest.raises(SystemExit, match="Preserve this project"):
                        stack.require_known_revision()
                else:
                    stack.require_known_revision()
                assert conn.execute("SELECT value FROM preserved_data").fetchall() == [
                    ("keep this state",)
                ]
                if revision is None:
                    assert conn.execute(
                        "SELECT to_regclass('public.alembic_version')"
                    ).fetchone() == (None,)
                else:
                    assert conn.execute(
                        "SELECT version_num FROM public.alembic_version"
                    ).fetchall() == ([(revision,)] if revision else [])
        finally:
            cluster.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
