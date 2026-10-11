"""Independent PostgreSQL sessions share the HTTP authentication window."""

import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import InsufficientPrivilege, ObjectNotInPrerequisiteState
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.http.request_budget import HttpRequestBudget, RequestBudgetMiddleware

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.integration,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.temporal,
]
ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def admission_app_factories(
    admin_conn: Connection[Any],
    pg_conninfo: str,
) -> Any:
    suffix = uuid4().hex[:12]
    role_name = f"re_http_admit_{suffix}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(sql.SQL("GRANT request_engine_app TO {}").format(sql.Identifier(role_name)))
    parts = conninfo_to_dict(pg_conninfo)
    host = parts.get("host")
    port = parts.get("port")
    database = parts.get("dbname")
    if (
        not isinstance(host, str)
        or not isinstance(port, (str, int))
        or not isinstance(database, str)
    ):
        raise AssertionError("PostgreSQL test connection info is incomplete")
    database_url = URL.create(
        "postgresql+asyncpg",
        username=role_name,
        password=password,
        host=host,
        port=int(port),
        database=database,
    )
    engines: list[AsyncEngine] = []

    def new_factory() -> SessionFactory:
        engine = create_postgres_engine(database_url.render_as_string(hide_password=False))
        engines.append(engine)
        return create_session_factory(engine)

    try:
        yield new_factory
    finally:
        for engine in engines:
            await engine.dispose()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def test_parallel_app_logins_never_exceed_shared_threshold(
    admin_conn: Connection[Any],
    app_role_conn_factory: Callable[[], Connection[Any]],
) -> None:
    admin_conn.execute(
        "UPDATE request_engine.http_auth_admission_state "
        "SET attempts = '{}', configured_limit = NULL WHERE singleton"
    )
    barrier = Barrier(4)

    def attempt(_index: int) -> tuple[bool, int]:
        with app_role_conn_factory() as conn:
            barrier.wait(timeout=5)
            outcome = conn.execute(
                "SELECT * FROM request_auth.admit_http_authentication(3)"
            ).fetchone()
            conn.commit()
            assert outcome is not None
            return (bool(outcome[0]), int(outcome[1]))

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, range(4)))
    final_row = admin_conn.execute(
        "SELECT cardinality(attempts) FROM request_engine.http_auth_admission_state WHERE singleton"
    ).fetchone()
    assert final_row is not None
    final_count = final_row[0]

    assert sorted(allowed for allowed, _retry in outcomes) == [False, True, True, True], (
        outcomes,
        final_count,
    )
    assert all(retry >= 1 for allowed, retry in outcomes if not allowed)
    stored_count = admin_conn.execute(
        "SELECT cardinality(attempts) FROM request_engine.http_auth_admission_state WHERE singleton"
    ).fetchone()
    assert stored_count is not None and stored_count[0] == 3


def test_admission_state_is_function_only_for_app_and_not_public_or_worker(
    admin_conn: Connection[Any],
    app_role_conn_factory: Callable[[], Connection[Any]],
) -> None:
    admin_conn.execute(
        "UPDATE request_engine.http_auth_admission_state "
        "SET attempts = '{}', configured_limit = NULL WHERE singleton"
    )
    assert admin_conn.execute(
        """
        SELECT has_function_privilege(
                   'request_engine_app',
                   'request_auth.admit_http_authentication(integer)', 'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_worker',
                   'request_auth.admit_http_authentication(integer)', 'EXECUTE'
               ),
               EXISTS (
                   SELECT 1
                     FROM pg_proc procedure
                     CROSS JOIN LATERAL aclexplode(
                         COALESCE(procedure.proacl, acldefault('f', procedure.proowner))
                     ) grant_entry
                    WHERE procedure.oid =
                        'request_auth.admit_http_authentication(integer)'::regprocedure
                      AND grant_entry.grantee = 0
                      AND grant_entry.privilege_type = 'EXECUTE'
               )
        """
    ).fetchone() == (True, False, False)
    topology = admin_conn.execute(
        """
        SELECT owner.rolcanlogin, owner.rolsuper, owner.rolcreatedb, owner.rolcreaterole,
               owner.rolreplication, owner.rolbypassrls,
               EXISTS (
                   SELECT 1 FROM pg_auth_members membership
                   WHERE membership.roleid = owner.oid OR membership.member = owner.oid
               ),
               procedure.proowner = owner.oid
          FROM pg_roles owner
          JOIN pg_proc procedure
            ON procedure.oid = 'request_auth.admit_http_authentication(integer)'::regprocedure
         WHERE owner.rolname = 'request_http_admission_definer'
        """
    ).fetchone()
    assert topology == (False, False, False, False, False, False, False, True)
    with app_role_conn_factory() as conn:
        for statement in (
            "SELECT * FROM request_engine.http_auth_admission_state",
            "UPDATE request_engine.http_auth_admission_state SET attempts = '{}'",
            "DELETE FROM request_engine.http_auth_admission_state",
        ):
            with pytest.raises(InsufficientPrivilege):
                conn.execute(statement)
            conn.rollback()


def test_limit_binding_mismatch_fails_closed_and_preserves_recent_window(
    admin_conn: Connection[Any],
    app_role_conn_factory: Callable[[], Connection[Any]],
) -> None:
    admin_conn.execute(
        "UPDATE request_engine.http_auth_admission_state "
        "SET configured_limit = 1, attempts = ARRAY[clock_timestamp() - interval '30 seconds'] "
        "WHERE singleton"
    )
    before_row = admin_conn.execute(
        "SELECT attempts FROM request_engine.http_auth_admission_state WHERE singleton"
    ).fetchone()
    assert before_row is not None
    before = before_row[0]
    with app_role_conn_factory() as conn:
        with pytest.raises(
            ObjectNotInPrerequisiteState,
            match="differs from the shared configured limit",
        ):
            conn.execute("SELECT * FROM request_auth.admit_http_authentication(2)")
        conn.rollback()
        rejected = conn.execute(
            "SELECT * FROM request_auth.admit_http_authentication(1)"
        ).fetchone()
        conn.commit()
    after_row = admin_conn.execute(
        "SELECT attempts FROM request_engine.http_auth_admission_state WHERE singleton"
    ).fetchone()
    assert rejected is not None and after_row is not None
    after = after_row[0]
    assert rejected[0] is False and 1 <= rejected[1] <= 30
    assert after == before


def test_expired_sixty_second_attempt_is_pruned_before_admission(
    admin_conn: Connection[Any],
    app_role_conn_factory: Callable[[], Connection[Any]],
) -> None:
    admin_conn.execute(
        "UPDATE request_engine.http_auth_admission_state "
        "SET configured_limit = 1, attempts = ARRAY[clock_timestamp() - interval '61 seconds'] "
        "WHERE singleton"
    )
    with app_role_conn_factory() as conn:
        outcome = conn.execute("SELECT * FROM request_auth.admit_http_authentication(1)").fetchone()
        conn.commit()
    assert outcome is not None
    assert outcome == (True, 0)
    stored_count = admin_conn.execute(
        "SELECT cardinality(attempts) FROM request_engine.http_auth_admission_state WHERE singleton"
    ).fetchone()
    assert stored_count is not None and stored_count[0] == 1


def test_missing_shared_state_row_fails_closed(
    admin_conn: Connection[Any],
    app_role_conn_factory: Callable[[], Connection[Any]],
) -> None:
    admin_conn.execute("DELETE FROM request_engine.http_auth_admission_state WHERE singleton")
    try:
        with app_role_conn_factory() as conn:
            with pytest.raises(ObjectNotInPrerequisiteState, match="state row is missing"):
                conn.execute("SELECT * FROM request_auth.admit_http_authentication(1)")
            conn.rollback()
    finally:
        admin_conn.execute(
            "INSERT INTO request_engine.http_auth_admission_state(singleton) VALUES (true)"
        )


def test_upgrade_rejects_preexisting_admission_definer_schema_acl_transactionally(
    pg_conninfo: str,
) -> None:
    """A fresh database cannot silently adopt a cluster role with extra local ACLs."""
    database = f"re_http_admission_acl_{uuid4().hex}"
    cluster_conninfo = make_conninfo(pg_conninfo, dbname="postgres")
    created_role = False
    with psycopg.connect(cluster_conninfo, autocommit=True) as cluster_admin:
        assert cluster_admin.info.server_version >= 180000
        if not cluster_admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = 'request_http_admission_definer'"
        ).fetchone():
            cluster_admin.execute(
                "CREATE ROLE request_http_admission_definer NOLOGIN NOSUPERUSER "
                "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
            created_role = True
        cluster_admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    database_conninfo = make_conninfo(pg_conninfo, dbname=database)
    db_values = conninfo_to_dict(database_conninfo)
    migration_url = URL.create(
        "postgresql+psycopg",
        username=str(db_values["user"]),
        password=str(db_values["password"]),
        host=str(db_values["host"]),
        port=int(str(db_values["port"])),
        database=database,
    ).render_as_string(hide_password=False)
    environment = {**os.environ, "MIGRATION_DATABASE_URL": migration_url}
    try:
        baseline = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0037_webauthn_retention"],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        with psycopg.connect(database_conninfo, autocommit=True) as isolated:
            isolated.execute(
                "GRANT USAGE ON SCHEMA request_engine TO request_http_admission_definer"
            )
        failed_upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0038_shared_http_auth_admission"],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert failed_upgrade.returncode != 0
        assert "unexpected object privileges" in failed_upgrade.stderr
        with psycopg.connect(database_conninfo) as isolated:
            assert isolated.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0037_webauthn_retention",
            )
            assert isolated.execute(
                "SELECT to_regclass('request_engine.http_auth_admission_state')"
            ).fetchone() == (None,)
            assert isolated.execute(
                "SELECT has_schema_privilege("
                "'request_http_admission_definer', 'request_engine', 'USAGE')"
            ).fetchone() == (True,)
    finally:
        with psycopg.connect(cluster_conninfo, autocommit=True) as cluster_admin:
            cluster_admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
            if created_role:
                cluster_admin.execute("DROP ROLE request_http_admission_definer")


@pytest.mark.asyncio
async def test_recreated_http_stack_shares_admission_and_lock_failure_precedes_body(
    admin_conn: Connection[Any],
    pg_conninfo: str,
    admission_app_factories: Callable[[], SessionFactory],
) -> None:
    admin_conn.execute(
        "UPDATE request_engine.http_auth_admission_state "
        "SET configured_limit = NULL, attempts = '{}' WHERE singleton"
    )
    factory_builder = admission_app_factories
    calls: list[bytes] = []

    def build_app(factory: SessionFactory) -> FastAPI:
        app = FastAPI()

        async def authenticate(request: Request) -> dict[str, bool]:
            calls.append(await request.body())
            return {"ok": True}

        app.add_api_route("/auth/native/login", authenticate, methods=["POST"])
        app.add_middleware(
            RequestBudgetMiddleware,
            budget=HttpRequestBudget(max_authentication_per_minute=1),
            session_factory=factory,
            shared_admission_required=True,
        )
        return app

    first_app = build_app(factory_builder())
    async with AsyncClient(transport=ASGITransport(first_app), base_url="http://test") as client:
        assert (await client.post("/auth/native/login", content=b"one")).status_code == 200
    # A fresh pool and newly composed middleware represent a restarted replica.
    restarted_app = build_app(factory_builder())
    async with AsyncClient(
        transport=ASGITransport(restarted_app), base_url="http://test"
    ) as client:
        rejected = await client.post("/auth/native/login", content=b"must-not-be-read")
    assert rejected.status_code == 429 and len(calls) == 1

    # Hold the singleton with an independent database transaction. The app-role
    # request must time out before its body reaches the owner and return 503.
    with psycopg.connect(pg_conninfo) as blocker:
        blocker.execute(
            "UPDATE request_engine.http_auth_admission_state "
            "SET attempts = attempts WHERE singleton"
        )
        blocked_app = build_app(factory_builder())
        async with AsyncClient(
            transport=ASGITransport(blocked_app), base_url="http://test"
        ) as client:
            blocked = await client.post("/auth/native/login", content=b"blocked-body")
        assert blocked.status_code == 503 and len(calls) == 1
        blocker.rollback()
    stored_count = admin_conn.execute(
        "SELECT cardinality(attempts) FROM request_engine.http_auth_admission_state WHERE singleton"
    ).fetchone()
    assert stored_count is not None and stored_count[0] == 1
