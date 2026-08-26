from typing import cast
from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_seed import PgConnection


@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.security
def test_f4_policy_tables_force_rls_and_hide_foreign_tenant_rows(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    first = create_live_ops_fixture(admin_conn)
    second = create_live_ops_fixture(admin_conn)
    first_policy = admin_conn.execute(
        "INSERT INTO request_engine.live_capacity_projection_policies "
        "(organization_id,service_queue_id,resource_id,location_id) "
        "VALUES (%s,%s,%s,%s) RETURNING id",
        (first.organization_id, first.queue_id, first.resource_id, first.location_id),
    ).fetchone()
    second_policy = admin_conn.execute(
        "INSERT INTO request_engine.live_capacity_projection_policies "
        "(organization_id,service_queue_id,resource_id,location_id) "
        "VALUES (%s,%s,%s,%s) RETURNING id",
        (second.organization_id, second.queue_id, second.resource_id, second.location_id),
    ).fetchone()
    assert first_policy is not None and second_policy is not None
    first_estimate = admin_conn.execute(
        "INSERT INTO request_engine.live_capacity_workload_estimate_policies "
        "(organization_id,workload_classification_id,duration_seconds) "
        "VALUES (%s,%s,1200) RETURNING id",
        (first.organization_id, first.expected_workload_id),
    ).fetchone()
    admin_conn.execute(
        "INSERT INTO request_engine.live_capacity_workload_estimate_policies "
        "(organization_id,workload_classification_id,duration_seconds) "
        "VALUES (%s,%s,1800)",
        (second.organization_id, second.expected_workload_id),
    )
    assert first_estimate is not None

    names = [
        "live_capacity_projection_policies",
        "live_capacity_workload_estimate_policies",
    ]
    relations = admin_conn.execute(
        "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='request_engine' AND relname=ANY(%s::text[])",
        (names,),
    ).fetchall()
    assert len(relations) == len(names)
    assert all(cast(bool, row[1]) and cast(bool, row[2]) for row in relations)

    app_conn: PgConnection = psycopg.connect(pg_conninfo)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,false)",
            (str(first.organization_id),),
        )
        assert app_conn.execute(
            "SELECT id FROM request_engine.live_capacity_projection_policies"
        ).fetchall() == [(cast(UUID, first_policy[0]),)]
        assert app_conn.execute(
            "SELECT id FROM request_engine.live_capacity_workload_estimate_policies"
        ).fetchall() == [(cast(UUID, first_estimate[0]),)]

        with pytest.raises(psycopg.Error) as denied:
            app_conn.execute(
                "INSERT INTO request_engine.live_capacity_projection_policies "
                "(organization_id,service_queue_id,resource_id,location_id) "
                "VALUES (%s,%s,%s,%s)",
                (
                    second.organization_id,
                    second.queue_id,
                    second.resource_id,
                    second.location_id,
                ),
            )
        assert denied.value.sqlstate == "42501"
    finally:
        app_conn.close()
