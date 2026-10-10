"""The independent operator read path returns capped aggregates, never row data."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import InsufficientPrivilege
from sqlalchemy.engine import URL

pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.security]
ROOT = Path(__file__).resolve().parents[2]


def _plan_nodes(value: object) -> Iterator[dict[str, object]]:
    if isinstance(value, dict):
        node = cast(dict[str, object], value)
        if "Node Type" in node:
            yield node
        for child in node.values():
            yield from _plan_nodes(child)
    elif isinstance(value, list):
        for child in cast(list[object], value):
            yield from _plan_nodes(child)


def _contains_relation(value: object, relation_name: str) -> bool:
    return any(node.get("Relation Name") == relation_name for node in _plan_nodes(value))


def test_monitor_role_can_read_only_the_bounded_aggregate(admin_conn: Connection[Any]) -> None:
    before = admin_conn.execute("SELECT * FROM request_admin.read_operator_metrics()").fetchone()
    assert before is not None
    organization_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.organizations (id, organization_key, display_name) "
        "VALUES (%s, %s, 'Operator metrics probe')",
        (organization_id, f"metrics-{organization_id}"),
    )
    action_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            id, organization_id, owner_module, action_type, dedupe_key,
            execute_at, next_attempt_at, created_at, updated_at
        ) VALUES (
            %s, %s, 'platform_configuration', 'metrics_probe', %s,
            clock_timestamp(), clock_timestamp(), clock_timestamp(), clock_timestamp()
        )
        """,
        (action_id, organization_id, f"metrics-test-{action_id}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            id, organization_id, owner_module, action_type, dedupe_key,
            execute_at, next_attempt_at, status, completed_at, created_at, updated_at
        ) VALUES (
            %s, %s, 'platform_configuration', 'metrics_probe_done', %s,
            clock_timestamp(), clock_timestamp(), 'completed', clock_timestamp(),
            clock_timestamp(), clock_timestamp()
        )
        """,
        (uuid4(), organization_id, f"metrics-terminal-{uuid4()}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            id, organization_id, owner_module, action_type, dedupe_key,
            execute_at, next_attempt_at, created_at, updated_at
        ) VALUES (
            %s, %s, 'platform_configuration', 'metrics_probe_future', %s,
            clock_timestamp() + interval '1 day', clock_timestamp() + interval '1 day',
            clock_timestamp() - interval '30 days', clock_timestamp()
        )
        """,
        (uuid4(), organization_id, f"metrics-future-{uuid4()}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            id, organization_id, owner_module, action_type, dedupe_key,
            execute_at, next_attempt_at, created_at, updated_at
        ) VALUES (
            %s, %s, 'platform_configuration', 'metrics_probe_overdue', %s,
            clock_timestamp() - interval '2 minutes', clock_timestamp() - interval '30 days',
            clock_timestamp() - interval '30 days', clock_timestamp()
        )
        """,
        (uuid4(), organization_id, f"metrics-overdue-{uuid4()}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, status, created_at, updated_at
        ) VALUES (%s, 'metrics.probe', '{}', 'pending', clock_timestamp(), clock_timestamp())
        """,
        (organization_id,),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id, event_type, payload, status, delivered_at, created_at, updated_at
        ) VALUES (%s, 'metrics.probe.done', '{}', 'delivered', clock_timestamp(),
                  clock_timestamp(), clock_timestamp())
        """,
        (organization_id,),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key, provider_event_id,
            payload_hash, payload, status, received_at, updated_at
        ) VALUES (
            %s, 'metrics-probe', 'metrics-probe', %s, 'probe-hash', '{}',
            'received', clock_timestamp(), clock_timestamp()
        )
        """,
        (organization_id, str(uuid4())),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key, provider_event_id,
            payload_hash, payload, status, received_at, processed_at, updated_at
        ) VALUES (
            %s, 'metrics-probe', 'metrics-probe', %s, 'probe-hash-done', '{}',
            'processed', clock_timestamp(), clock_timestamp(), clock_timestamp()
        )
        """,
        (organization_id, str(uuid4())),
    )

    admin_conn.execute("SET ROLE request_operator_metrics")
    aggregate = admin_conn.execute("SELECT * FROM request_admin.read_operator_metrics()").fetchone()
    assert aggregate is not None
    assert len(aggregate) == 9
    assert aggregate[0] == before[0] + 2
    assert 60.0 < aggregate[1] < 180.0
    assert aggregate[2] == before[2] + 1
    assert aggregate[4] == before[4] + 1
    assert all(value >= 0 for value in aggregate)
    with pytest.raises(InsufficientPrivilege):
        admin_conn.execute("SELECT id FROM request_engine.scheduled_actions LIMIT 1")
    admin_conn.rollback()


def test_monitor_role_cannot_read_internal_tables_or_call_other_admin_functions(
    admin_conn: Connection[Any],
) -> None:
    assert admin_conn.execute(
        "SELECT has_function_privilege('request_operator_metrics', "
        "'request_admin.read_operator_metrics()', 'EXECUTE'), "
        "has_table_privilege('request_operator_metrics', "
        "'request_engine.scheduled_actions', 'SELECT'), "
        "has_function_privilege('request_operator_metrics', "
        "'request_auth.admit_http_authentication(integer)', 'EXECUTE'), "
        "has_function_privilege('public', "
        "'request_admin.read_operator_metrics()', 'EXECUTE')"
    ).fetchone() == (True, False, False, False)


def test_deployment_login_can_only_inherit_the_aggregate_reader(
    admin_conn: Connection[Any],
) -> None:
    login = f"re_metrics_{uuid4().hex[:12]}"
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(login), sql.Literal(uuid4().hex))
    )
    try:
        admin_conn.execute(
            sql.SQL("GRANT request_operator_metrics TO {} WITH INHERIT TRUE, SET FALSE").format(
                sql.Identifier(login)
            )
        )
        privileges = admin_conn.execute(
            "SELECT has_function_privilege(%s, "
            "'request_admin.read_operator_metrics()', 'EXECUTE'), "
            "has_table_privilege(%s, 'request_engine.provider_events', 'SELECT'), "
            "pg_has_role(%s, 'request_engine_app', 'member')",
            (login, login, login),
        ).fetchone()
        assert privileges == (True, False, False)
    finally:
        admin_conn.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(login)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))


def test_operator_projection_plan_uses_ordered_indexes_for_oldest_work(
    admin_conn: Connection[Any],
) -> None:
    organization_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.organizations (id, organization_key, display_name) "
        "VALUES (%s, %s, 'Operator metrics plan probe')",
        (organization_id, f"metrics-plan-{organization_id}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            id, organization_id, owner_module, action_type, dedupe_key,
            execute_at, next_attempt_at, status, claim_token, lease_until,
            created_at, updated_at
        )
        SELECT gen_random_uuid(), %s, 'platform_configuration', 'metrics_plan_probe',
               'pending-' || number::text,
               clock_timestamp() - interval '1 day',
               clock_timestamp() - interval '1 day', 'pending', NULL, NULL,
               clock_timestamp() - interval '1 day', clock_timestamp()
          FROM generate_series(1, 5000) AS number
        """,
        (organization_id,),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            id, organization_id, owner_module, action_type, dedupe_key,
            execute_at, next_attempt_at, status, claim_token, lease_until,
            created_at, updated_at
        )
        SELECT gen_random_uuid(), %s, 'platform_configuration', 'metrics_plan_probe',
               'leased-' || number::text,
               clock_timestamp(), clock_timestamp(), 'leased', gen_random_uuid(),
               clock_timestamp() - interval '2 days', clock_timestamp(), clock_timestamp()
          FROM generate_series(1, 5000) AS number
        """,
        (organization_id,),
    )
    admin_conn.execute("ANALYZE request_engine.scheduled_actions")

    source_row = admin_conn.execute(
        "SELECT prosrc FROM pg_proc WHERE oid = "
        "'request_admin.read_operator_metrics()'::regprocedure"
    ).fetchone()
    assert source_row is not None and isinstance(source_row[0], str)
    admin_conn.execute("SET ROLE request_operator_metrics_definer")
    try:
        plan_row = admin_conn.execute(
            sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ") + sql.SQL(source_row[0])
        ).fetchone()
    finally:
        admin_conn.execute("RESET ROLE")
    assert plan_row is not None
    plan = plan_row[0]
    nodes = list(_plan_nodes(plan))
    index_names = {node.get("Index Name") for node in nodes}
    assert "scheduled_actions_metrics_pending_due_idx" in index_names
    assert "scheduled_actions_metrics_expired_lease_idx" in index_names
    assert not any(
        node.get("Node Type") == "Sort"
        and _contains_relation(node.get("Plans", []), "scheduled_actions")
        for node in nodes
    )

    aggregate = admin_conn.execute("SELECT * FROM request_admin.read_operator_metrics()").fetchone()
    assert aggregate is not None
    assert aggregate[0] == 1001
    assert 0 < aggregate[1] < 3 * 24 * 60 * 60


def test_column_acl_poisoning_rejects_0039_before_any_object_is_installed(
    pg_conninfo: str,
) -> None:
    database = f"re_operator_metrics_acl_{uuid4().hex}"
    cluster_conninfo = make_conninfo(pg_conninfo, dbname="postgres")
    with psycopg.connect(cluster_conninfo, autocommit=True) as cluster_admin:
        cluster_admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

    isolated_conninfo = make_conninfo(pg_conninfo, dbname=database)
    values = conninfo_to_dict(isolated_conninfo)
    host = values.get("host")
    port = values.get("port")
    username = values.get("user")
    password = values.get("password")
    if (
        not isinstance(host, str)
        or not isinstance(port, (str, int))
        or not isinstance(username, str)
        or not isinstance(password, str)
    ):
        raise AssertionError("PostgreSQL test connection info is incomplete")
    migration_url = URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=host,
        port=int(port),
        database=database,
    ).render_as_string(hide_password=False)
    environment = {**os.environ, "MIGRATION_DATABASE_URL": migration_url}
    try:
        baseline = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0038_shared_http_auth_admission"],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert baseline.returncode == 0, baseline.stdout + baseline.stderr
        with psycopg.connect(isolated_conninfo, autocommit=True) as isolated:
            isolated.execute(
                "GRANT SELECT (status) ON request_engine.scheduled_actions "
                "TO request_operator_metrics"
            )
        failed_upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0039_operator_metrics_projection"],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert failed_upgrade.returncode != 0
        assert "pre-existing object grants" in failed_upgrade.stderr
        with psycopg.connect(isolated_conninfo) as isolated:
            assert isolated.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0038_shared_http_auth_admission",
            )
            assert isolated.execute(
                "SELECT to_regclass('request_admin.read_operator_metrics()')"
            ).fetchone() == (None,)
            assert isolated.execute(
                "SELECT to_regclass('request_engine.scheduled_actions_metrics_pending_due_idx')"
            ).fetchone() == (None,)
    finally:
        with psycopg.connect(cluster_conninfo, autocommit=True) as cluster_admin:
            cluster_admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )
