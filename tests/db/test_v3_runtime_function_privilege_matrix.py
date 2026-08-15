from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.errors import InsufficientPrivilege

PgConnection = Connection[Any]


def _login_conninfo(pg_conninfo: str, role_name: str, password: str) -> str:
    parts = pg_conninfo.split()
    filtered = [
        part
        for part in parts
        if not part.startswith("user=") and not part.startswith("password=")
    ]
    return " ".join([*filtered, f"user={role_name}", f"password={password}"])


@contextmanager
def _runtime_login(
    admin_conn: PgConnection,
    pg_conninfo: str,
    group_role: str,
) -> Iterator[PgConnection]:
    role_name = f"{group_role}_acl_{uuid4().hex[:16]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT TRUE").format(
            sql.Identifier(group_role),
            sql.Identifier(role_name),
        )
    )

    conn: PgConnection | None = None
    try:
        conn = psycopg.connect(
            _login_conninfo(pg_conninfo, role_name, password),
            autocommit=True,
        )
        yield conn
    finally:
        if conn is not None:
            conn.close()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def _function_matrix(conn: PgConnection, signatures: list[str]) -> dict[str, bool]:
    matrix: dict[str, bool] = {}
    for signature in signatures:
        row = conn.execute(
            "SELECT has_function_privilege(current_user, %s, 'EXECUTE')",
            (signature,),
        ).fetchone()
        assert row is not None
        matrix[signature] = bool(row[0])
    return matrix


def _assert_cannot_set_role(conn: PgConnection, roles: tuple[str, ...]) -> None:
    for role in roles:
        with pytest.raises(InsufficientPrivilege):
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))


@pytest.mark.postgres
def test_real_worker_login_has_exact_worker_function_surface(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    allowed = [
        "request_cmd.claim_scheduled_actions(integer,interval)",
        "request_cmd.complete_scheduled_action(uuid,uuid)",
        "request_cmd.retry_scheduled_action(uuid,uuid,timestamptz,text)",
        "request_cmd.dead_letter_scheduled_action(uuid,uuid,text)",
        "request_cmd.renew_scheduled_action_lease(uuid,uuid,interval)",
        "request_cmd.retry_scheduled_action_after(uuid,uuid,interval,text)",
        "request_cmd.lock_scheduled_action_claim(uuid,uuid)",
        "request_cmd.claim_outbox_messages(integer,interval)",
        "request_cmd.complete_outbox_message(uuid,uuid)",
        "request_cmd.retry_outbox_message(uuid,uuid,timestamptz,text)",
        "request_cmd.dead_letter_outbox_message(uuid,uuid,text)",
        "request_cmd.renew_outbox_message_lease(uuid,uuid,interval)",
        "request_cmd.retry_outbox_message_after(uuid,uuid,interval,text)",
        "request_cmd.claim_provider_events(integer,interval)",
        "request_cmd.renew_provider_event_lease(uuid,uuid,interval)",
        "request_cmd.complete_provider_event(uuid,uuid)",
        "request_cmd.retry_provider_event_after(uuid,uuid,interval,text)",
        "request_cmd.reject_provider_event(uuid,uuid,text)",
        "request_cmd.dead_letter_provider_event(uuid,uuid,text)",
    ]
    denied = [
        "request_cmd.cancel_scheduled_action(uuid,uuid)",
        "request_engine.assert_hold_claim_completeness(uuid,uuid)",
        "request_engine.assert_reservation_claim_completeness(uuid,uuid)",
        "request_engine.check_capacity_owner_completeness()",
        "request_engine.guard_capacity_claim()",
        "request_admin.replay_dead_scheduled_action(uuid,uuid,uuid,integer,text)",
    ]

    with _runtime_login(admin_conn, pg_conninfo, "request_engine_worker") as worker:
        identity = worker.execute(
            """
            SELECT current_user = session_user,
                   pg_has_role(current_user, 'request_engine_worker', 'MEMBER'),
                   pg_has_role(current_user, 'request_engine_app', 'MEMBER'),
                   pg_has_role(current_user, 'request_engine_admin', 'MEMBER'),
                   has_schema_privilege(current_user, 'request_admin', 'USAGE')
            """
        ).fetchone()
        assert identity == (True, True, False, False, False)
        assert _function_matrix(worker, allowed) == dict.fromkeys(allowed, True)
        assert _function_matrix(worker, denied) == dict.fromkeys(denied, False)

        table_overreach = worker.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'request_engine'
              AND c.relkind IN ('r', 'p')
              AND (
                  has_table_privilege(current_user, c.oid, 'TRUNCATE')
                  OR has_table_privilege(current_user, c.oid, 'REFERENCES')
                  OR has_table_privilege(current_user, c.oid, 'TRIGGER')
              )
            ORDER BY c.relname
            """
        ).fetchall()
        assert table_overreach == []
        _assert_cannot_set_role(
            worker,
            ("request_engine_app", "request_engine_admin", "request_engine_schema_owner"),
        )


@pytest.mark.postgres
def test_real_admin_login_can_operate_but_cannot_become_schema_owner(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    allowed = [
        "request_cmd.claim_scheduled_actions(integer,interval)",
        "request_cmd.complete_scheduled_action(uuid,uuid)",
        "request_cmd.cancel_scheduled_action(uuid,uuid)",
        "request_cmd.claim_outbox_messages(integer,interval)",
        "request_cmd.claim_provider_events(integer,interval)",
        "request_admin.replay_dead_scheduled_action(uuid,uuid,uuid,integer,text)",
    ]
    denied = [
        "request_engine.assert_hold_claim_completeness(uuid,uuid)",
        "request_engine.assert_reservation_claim_completeness(uuid,uuid)",
        "request_engine.check_capacity_owner_completeness()",
        "request_engine.guard_capacity_claim()",
    ]

    with _runtime_login(admin_conn, pg_conninfo, "request_engine_admin") as runtime_admin:
        identity = runtime_admin.execute(
            """
            SELECT current_user = session_user,
                   pg_has_role(current_user, 'request_engine_admin', 'MEMBER'),
                   pg_has_role(current_user, 'request_engine_app', 'MEMBER'),
                   pg_has_role(current_user, 'request_engine_worker', 'MEMBER'),
                   has_schema_privilege(current_user, 'request_admin', 'USAGE'),
                   has_schema_privilege(current_user, 'request_engine', 'CREATE')
            """
        ).fetchone()
        assert identity == (True, True, False, False, True, False)
        assert _function_matrix(runtime_admin, allowed) == dict.fromkeys(allowed, True)
        assert _function_matrix(runtime_admin, denied) == dict.fromkeys(denied, False)
        _assert_cannot_set_role(
            runtime_admin,
            ("request_engine_app", "request_engine_worker", "request_engine_schema_owner"),
        )
