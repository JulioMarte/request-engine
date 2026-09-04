from typing import LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from f3_live_ops_fixture import LiveOpsFixture, create_live_ops_fixture
from f3_live_ops_race_support import create_principal
from f3_live_ops_seed import PgConnection, uuid_row

WORKFLOW_TABLES = (
    "request_engine.operational_recovery_incidents",
    "request_engine.operational_recovery_actions",
    "request_engine.operational_recovery_proposals",
)
_ID_COLUMNS = ", ".join(f"(SELECT id FROM {t})" for t in WORKFLOW_TABLES)
_BUMP: LiteralString = "SELECT request_engine.bump_recovery_source_revision(%s,%s)"
_LOCK: LiteralString = "SELECT request_cmd.lock_recovery_source_revision(%s,%s)"
_ALTER_PROBE: LiteralString = (
    "ALTER TABLE request_engine.operational_recovery_proposals ADD COLUMN probe text"
)
_INCIDENT_FORGED_UPDATE: LiteralString = (
    "UPDATE request_engine.operational_recovery_incidents SET status='resolved' WHERE id=%s"
)
_ACTION_FORGED_UPDATE: LiteralString = (
    "UPDATE request_engine.operational_recovery_actions SET status='succeeded' "
    "WHERE organization_id=%s"
)
_PROPOSAL_FORGED_UPDATE: LiteralString = (
    "UPDATE request_engine.operational_recovery_proposals SET command_fingerprint='forged' "
    "WHERE id=%s"
)
_ACTION_INSERT: LiteralString = (
    "INSERT INTO request_engine.operational_recovery_actions (organization_id,incident_id,"
    "action_kind,principal_id,idempotency_key,command_fingerprint,expected_source_revision,"
    "payload) VALUES (%s,%s,'stop_intake',%s,%s,%s,%s,'{}'::jsonb) RETURNING id"
)
_INCIDENT_INSERT: LiteralString = (
    "INSERT INTO request_engine.operational_recovery_incidents (organization_id,"
    "service_queue_id,resource_id,location_id,impact_kind,source_revision,source_fingerprint,"
    "last_assessed_at) VALUES (%s,%s,%s,%s,'capacity_shortfall',7,%s,'2035-01-01T09:00Z') "
    "RETURNING id"
)
_PROPOSAL_INSERT: LiteralString = (
    "INSERT INTO request_engine.operational_recovery_proposals (organization_id,service_queue_id,"
    "resource_id,location_id,created_by_principal_id,idempotency_key,command_fingerprint,"
    "observed_at,horizon_end,source_fingerprint,proposal_fingerprint,executable_capacity_seconds,"
    "committed_capacity_seconds,shortfall_seconds,snapshot) VALUES (%s,%s,%s,%s,%s,%s,%s,"
    "'2035-01-01T09:00Z','2035-01-01T17:00Z',%s,%s,3600,5400,1800,'{}'::jsonb) RETURNING id"
)
_FOREIGN_STATE = (
    "SELECT (SELECT status FROM request_engine.operational_recovery_incidents WHERE id=%s),"
    "(SELECT status FROM request_engine.operational_recovery_actions WHERE id=%s)"
)


def _tenant_context(conn: PgConnection, org: UUID) -> None:
    conn.execute("SELECT set_config('request_engine.organization_id',%s,false)", (str(org),))


def _denied(c: PgConnection, state: str, sql: LiteralString, args: tuple[object, ...] = ()) -> None:
    with pytest.raises(psycopg.Error) as raised:
        c.execute(sql, args)
    assert raised.value.sqlstate == state


def _has_privilege(conn: PgConnection, role: str, table: str, privilege: str) -> bool:
    row = conn.execute(
        "SELECT has_table_privilege(%s,%s,%s)",
        (role, table, privilege),
    ).fetchone()
    assert row is not None
    return cast(bool, row[0])


def _all_have_privilege(conn: PgConnection, role: str, privilege: str) -> bool:
    return all(_has_privilege(conn, role, table, privilege) for table in WORKFLOW_TABLES)


def _none_have_privilege(conn: PgConnection, role: str, privilege: str) -> bool:
    return all(not _has_privilege(conn, role, table, privilege) for table in WORKFLOW_TABLES)


def _seed_tenant_workflow(
    conn: PgConnection, setup: LiveOpsFixture, principal_id: UUID
) -> tuple[UUID, UUID, UUID]:
    suffix = uuid4().hex
    _tenant_context(conn, setup.organization_id)
    params = (setup.organization_id, setup.queue_id, setup.resource_id, setup.location_id, suffix)
    incident = uuid_row(conn, _INCIDENT_INSERT, params)
    params = (setup.organization_id, incident, principal_id, suffix, f"cmd-{suffix}", 7)
    action = uuid_row(conn, _ACTION_INSERT, params)
    params = (setup.organization_id, setup.queue_id, setup.resource_id, setup.location_id)
    params += (principal_id, suffix, suffix, f"cmd-{suffix}", f"prop-{suffix}")
    proposal = uuid_row(conn, _PROPOSAL_INSERT, params)
    return incident, action, proposal


@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.security
def test_f5_workflow_tables_force_rls_and_runtime_least_privilege(
    admin_conn: PgConnection, pg_conninfo: str
) -> None:
    first = create_live_ops_fixture(admin_conn)
    second = create_live_ops_fixture(admin_conn)
    first_principal = create_principal(admin_conn, first)
    second_principal = create_principal(admin_conn, second)
    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        first_rows = _seed_tenant_workflow(app_conn, first, first_principal)
        second_rows = _seed_tenant_workflow(app_conn, second, second_principal)
        _tenant_context(app_conn, first.organization_id)
        assert app_conn.execute(f"SELECT {_ID_COLUMNS}").fetchone() == first_rows

        assert app_conn.execute(_INCIDENT_FORGED_UPDATE, (second_rows[0],)).rowcount == 0
        assert app_conn.execute(_ACTION_FORGED_UPDATE, (second.organization_id,)).rowcount == 0
        _denied(app_conn, "42501", _PROPOSAL_FORGED_UPDATE, (second_rows[2],))

        forged = (second.organization_id, second_rows[0], second_principal, "guess", "forged", 1)
        _denied(app_conn, "42501", _ACTION_INSERT, forged)

        admin_conn.execute("SET ROLE request_engine_schema_owner")
        _tenant_context(admin_conn, first.organization_id)
        assert admin_conn.execute(f"SELECT {_ID_COLUMNS}").fetchone() == first_rows
        admin_conn.execute("RESET ROLE")

        for privilege in ("SELECT", "INSERT"):
            assert _all_have_privilege(app_conn, "request_engine_app", privilege)
        assert _has_privilege(
            app_conn,
            "request_engine_app",
            "request_engine.operational_recovery_incidents",
            "UPDATE",
        )
        assert _has_privilege(
            app_conn,
            "request_engine_app",
            "request_engine.operational_recovery_actions",
            "UPDATE",
        )
        assert not _has_privilege(
            app_conn,
            "request_engine_app",
            "request_engine.operational_recovery_proposals",
            "UPDATE",
        )
        for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER", "MAINTAIN"):
            assert _none_have_privilege(app_conn, "request_engine_app", privilege)
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert _none_have_privilege(app_conn, "request_engine_worker", privilege)

        _denied(app_conn, "42501", "DELETE FROM request_engine.operational_recovery_incidents")
        _denied(app_conn, "42501", "TRUNCATE request_engine.operational_recovery_actions")
        _denied(app_conn, "42501", _ALTER_PROBE)
        _denied(app_conn, "42501", _BUMP, (second.organization_id, second.queue_id))
        _denied(app_conn, "23514", _LOCK, (second.organization_id, second.queue_id))
        app_conn.execute("RESET ROLE")
        app_conn.execute("SET ROLE request_engine_worker")
        _denied(app_conn, "42501", "SELECT id FROM request_engine.operational_recovery_incidents")
        _denied(app_conn, "42501", _BUMP, (first.organization_id, first.queue_id))
    finally:
        app_conn.close()

    final = admin_conn.execute(_FOREIGN_STATE, (second_rows[0], second_rows[1])).fetchone()
    assert final == ("open", "prepared")
