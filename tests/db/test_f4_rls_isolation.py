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
        "VALUES (%s,%s,1200)",
        (second.organization_id, second.expected_workload_id),
    )
    assert first_estimate is not None
    first_policy_id = cast(UUID, first_policy[0])
    second_policy_id = cast(UUID, second_policy[0])
    first_estimate_id = cast(UUID, first_estimate[0])

    with psycopg.connect(pg_conninfo) as tenant_conn:
        tenant_conn.execute("SET ROLE request_engine_app")
        tenant_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(first.organization_id),),
        )
        visible_policy_ids = {
            row[0]
            for row in tenant_conn.execute(
                "SELECT id FROM request_engine.live_capacity_projection_policies"
            ).fetchall()
        }
        visible_estimate_ids = {
            row[0]
            for row in tenant_conn.execute(
                "SELECT id FROM request_engine.live_capacity_workload_estimate_policies"
            ).fetchall()
        }

    assert first_policy_id in visible_policy_ids
    assert second_policy_id not in visible_policy_ids
    assert first_estimate_id in visible_estimate_ids
