from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection, label: str) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"prov-{label}-{suffix}", f"Provenance {label} {suffix}"),
    )


def _principal(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"admin-{uuid4().hex}"),
    )


def _dead_action(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            payload, dedupe_key, execute_at, next_attempt_at,
            status, attempt_count, max_attempts, last_error_class
        ) VALUES (
            %s, 'booking', 'test.provenance', 1, '{}'::jsonb, %s,
            clock_timestamp(), clock_timestamp(), 'dead', 8, 8, 'test_failure'
        )
        RETURNING id
        """,
        (organization_id, f"prov:{uuid4().hex}"),
    )


@pytest.mark.postgres
def test_admin_replay_rejects_missing_trusted_actor_context(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "missing")
    action_id = _dead_action(admin_conn, organization_id)

    conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        conn.execute("SET ROLE request_engine_admin")
        with pytest.raises(Error) as exc_info:
            conn.execute(
                "SELECT request_admin.replay_dead_scheduled_action(%s, %s, 3, 'manual replay')",
                (organization_id, action_id),
            ).fetchone()
        assert exc_info.value.sqlstate == "42501"
    finally:
        conn.close()


@pytest.mark.postgres
def test_admin_replay_rejects_cross_tenant_execution_context(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    target_org = _organization(admin_conn, "target")
    actor_org = _organization(admin_conn, "actor")
    actor = _principal(admin_conn, actor_org)
    action_id = _dead_action(admin_conn, target_org)

    conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        conn.execute("SET ROLE request_engine_admin")
        conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(actor_org),),
        )
        conn.execute(
            "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
            (str(actor),),
        )
        with pytest.raises(Error) as exc_info:
            conn.execute(
                "SELECT request_admin.replay_dead_scheduled_action(%s, %s, 3, 'manual replay')",
                (target_org, action_id),
            ).fetchone()
        assert exc_info.value.sqlstate == "42501"
    finally:
        conn.close()


@pytest.mark.postgres
def test_admin_replay_audit_actor_and_correlation_come_from_execution_context(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, "success")
    actor = _principal(admin_conn, organization_id)
    action_id = _dead_action(admin_conn, organization_id)
    correlation_id = uuid4()

    conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        conn.execute("SET ROLE request_engine_admin")
        settings = {
            "request_engine.organization_id": str(organization_id),
            "request_engine.authenticated_principal_id": str(actor),
            "request_engine.principal_kind": "human",
            "request_engine.authentication_method": "test_adapter",
            "request_engine.correlation_id": str(correlation_id),
        }
        for key, value in settings.items():
            conn.execute("SELECT set_config(%s, %s, false)", (key, value))

        row = conn.execute(
            "SELECT request_admin.replay_dead_scheduled_action(%s, %s, 3, 'manual replay')",
            (organization_id, action_id),
        ).fetchone()
        assert row == (True,)
    finally:
        conn.close()

    audit = admin_conn.execute(
        """
        SELECT actor_principal_id,
               correlation_data->>'correlation_id',
               correlation_data->>'principal_kind',
               correlation_data->>'authentication_method'
          FROM request_engine.audit_records
         WHERE organization_id = %s
           AND aggregate_kind = 'ScheduledAction'
           AND aggregate_id = %s
           AND command_name = 'admin.replay_scheduled_action'
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (organization_id, action_id),
    ).fetchone()
    assert audit == (actor, str(correlation_id), "human", "test_adapter")
