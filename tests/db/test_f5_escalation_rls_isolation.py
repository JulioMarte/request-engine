from typing import LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_seed import PgConnection, uuid_row

_ESCALATION_TABLE = "request_engine.operational_recovery_escalations"
_INCIDENT_INSERT: LiteralString = (
    "INSERT INTO request_engine.operational_recovery_incidents (organization_id,"
    "service_queue_id,resource_id,location_id,impact_kind,source_revision,source_fingerprint,"
    "last_assessed_at) VALUES (%s,%s,%s,%s,'capacity_shortfall',7,%s,'2035-01-01T09:00Z') "
    "RETURNING id"
)
_ESCALATION_INSERT: LiteralString = (
    "INSERT INTO request_engine.operational_recovery_escalations (organization_id,incident_id,"
    "source_revision,escalation_level,operator_escalation_required,escalation_reason,"
    "customer_impact_required,impact_recipient_party_ids,source_fingerprint) "
    "VALUES (%s,%s,7,2,true,'newly_material',true,%s::jsonb,%s) RETURNING id"
)


def _tenant_context(conn: PgConnection, org: UUID) -> None:
    conn.execute("SELECT set_config('request_engine.organization_id',%s,false)", (str(org),))


def _denied(c: PgConnection, state: str, sql: LiteralString, args: tuple[object, ...] = ()) -> None:
    with pytest.raises(psycopg.Error) as raised:
        c.execute(sql, args)
    assert raised.value.sqlstate == state


@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.security
def test_f5_escalation_facts_are_immutable_and_tenant_isolated(
    admin_conn: PgConnection, pg_conninfo: str
) -> None:
    first = create_live_ops_fixture(admin_conn)
    second = create_live_ops_fixture(admin_conn)
    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        _tenant_context(app_conn, first.organization_id)
        incident = uuid_row(
            app_conn,
            _INCIDENT_INSERT,
            (
                first.organization_id,
                first.queue_id,
                first.resource_id,
                first.location_id,
                uuid4().hex,
            ),
        )
        suffix = uuid4().hex
        escalation = uuid_row(
            app_conn,
            _ESCALATION_INSERT,
            (first.organization_id, incident, f'["{uuid4()}"]', suffix),
        )
        assert escalation is not None

        _tenant_context(app_conn, second.organization_id)
        assert app_conn.execute(f"SELECT id FROM {_ESCALATION_TABLE}").fetchone() is None
        _denied(
            app_conn,
            "23503",
            _ESCALATION_INSERT,
            (second.organization_id, escalation, f'["{uuid4()}"]', uuid4().hex),
        )

        _tenant_context(app_conn, first.organization_id)
        _denied(
            app_conn,
            "42501",
            f"UPDATE {_ESCALATION_TABLE} SET operator_escalation_required=false WHERE id=%s",
            (escalation,),
        )
        _denied(
            app_conn,
            "42501",
            f"DELETE FROM {_ESCALATION_TABLE} WHERE id=%s",
            (escalation,),
        )
        app_conn.execute("RESET ROLE")
        app_conn.execute("SET ROLE request_engine_admin")
        _tenant_context(app_conn, first.organization_id)
        _denied(
            app_conn,
            "23514",
            f"UPDATE {_ESCALATION_TABLE} SET operator_escalation_required=false WHERE id=%s",
            (escalation,),
        )
        _denied(
            app_conn,
            "23514",
            f"DELETE FROM {_ESCALATION_TABLE} WHERE id=%s",
            (escalation,),
        )
        app_conn.execute("RESET ROLE")
        app_conn.execute("SET ROLE request_engine_app")
        _tenant_context(app_conn, first.organization_id)

        for privilege in ("SELECT", "INSERT"):
            granted = app_conn.execute(
                "SELECT has_table_privilege('request_engine_app',%s,%s)",
                (_ESCALATION_TABLE, privilege),
            ).fetchone()
            assert granted is not None and cast(bool, granted[0])
        for privilege in ("UPDATE", "DELETE"):
            revoked = app_conn.execute(
                "SELECT has_table_privilege('request_engine_app',%s,%s)",
                (_ESCALATION_TABLE, privilege),
            ).fetchone()
            assert revoked is not None and not cast(bool, revoked[0])
        app_conn.execute("RESET ROLE")
        app_conn.execute("SET ROLE request_engine_worker")
        _denied(app_conn, "42501", f"SELECT id FROM {_ESCALATION_TABLE}")
        _tenant_context(admin_conn, first.organization_id)
        row = admin_conn.execute(
            "SELECT operator_escalation_required, escalation_reason "
            f"FROM {_ESCALATION_TABLE} WHERE id=%s",
            (escalation,),
        ).fetchone()
        assert row == (True, "newly_material")
    finally:
        app_conn.close()
