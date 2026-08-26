from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from f3_live_ops_fixture import LiveOpsFixture, PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_paused_session


def _activity_resource(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.resources "
        "(organization_id,resource_key,display_name,capacity_model,capacity_units) "
        "VALUES (%s,%s,'F3 RLS activity resource','exclusive',1) RETURNING id",
        (organization_id, f"f3-rls-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _seed_activity(conn: PgConnection, setup: LiveOpsFixture, principal_id: UUID) -> UUID:
    resource_id = _activity_resource(conn, setup.organization_id)
    row = conn.execute(
        "INSERT INTO request_engine.resource_activities "
        "(organization_id,resource_id,activity_kind,started_by_principal_id) "
        "VALUES (%s,%s,'administrative',%s) RETURNING id",
        (setup.organization_id, resource_id, principal_id),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.postgres
@pytest.mark.security
def test_f3_relations_force_rls_and_hide_foreign_tenant_rows(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    first = create_live_ops_fixture(admin_conn)
    second = create_live_ops_fixture(admin_conn)
    first_session, first_principal = create_paused_session(admin_conn, first)
    create_paused_session(admin_conn, second)
    first_activity = _seed_activity(admin_conn, first, first_principal)
    second_principal = admin_conn.execute(
        "SELECT started_by_principal_id FROM request_engine.service_session_interruptions "
        "WHERE organization_id=%s LIMIT 1",
        (second.organization_id,),
    ).fetchone()
    assert second_principal is not None
    _seed_activity(admin_conn, second, cast(UUID, second_principal[0]))

    names = [
        "operational_workload_classifications",
        "service_sessions",
        "service_session_interruptions",
        "resource_activities",
    ]
    rows = admin_conn.execute(
        "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='request_engine' AND relname=ANY(%s::text[])",
        (names,),
    ).fetchall()
    assert len(rows) == len(names)
    assert all(cast(bool, row[1]) and cast(bool, row[2]) for row in rows)

    app_conn: PgConnection = psycopg.connect(pg_conninfo)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,false)",
            (str(first.organization_id),),
        )
        assert app_conn.execute("SELECT id FROM request_engine.service_sessions").fetchall() == [
            (first_session,)
        ]
        assert app_conn.execute("SELECT id FROM request_engine.resource_activities").fetchall() == [
            (first_activity,)
        ]
        assert app_conn.execute(
            "SELECT count(*) FROM request_engine.service_session_interruptions"
        ).fetchone() == (1,)
        assert app_conn.execute(
            "SELECT count(*) FROM request_engine.operational_workload_classifications"
        ).fetchone() == (2,)

        with pytest.raises(psycopg.Error) as denied:
            app_conn.execute(
                "INSERT INTO request_engine.operational_workload_classifications "
                "(organization_id,workload_key,display_name) VALUES (%s,%s,'Foreign')",
                (second.organization_id, f"foreign-{uuid4().hex}"),
            )
        assert denied.value.sqlstate == "42501"
    finally:
        app_conn.close()
