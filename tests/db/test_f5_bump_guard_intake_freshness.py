# Direct PostgreSQL proof for the F5 contract (docs/v3/32): the recovery bump
# fence rejects caller-supplied foreign tenant authority (section 15-H), and a
# Queue intake-control mutation durably advances the recovery source revision
# with exactly one deduped reassessment per material change (section 12).

from uuid import UUID

import psycopg
import pytest
from f2_discovery_fixture import DiscoveryFixture, create_discovery_fixture, uuid_row
from f3_live_ops_seed import PgConnection

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.integration,
    pytest.mark.invariant,
    pytest.mark.contract,
]


def _revision(conn: PgConnection, org: UUID, queue: UUID) -> int | None:
    row = conn.execute(
        "SELECT revision FROM request_engine.recovery_source_revisions "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (org, queue),
    ).fetchone()
    return int(row[0]) if row else None


def _reassessment_count(conn: PgConnection, org: UUID, queue: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.scheduled_actions "
        "WHERE organization_id=%s AND dedupe_key LIKE 'f5-reassessment:' || %s || ':%%'",
        (org, str(queue)),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _queue(conn: PgConnection, base: DiscoveryFixture) -> UUID:
    return uuid_row(
        conn,
        "INSERT INTO request_engine.service_queues (organization_id,location_id,offering_id,"
        "queue_key,display_name) VALUES (%s,%s,%s,%s,'Guard Queue') RETURNING id",
        (base.organization_id, base.location_id, base.offering_id, f"guard-{base.organization_id}"),
    )


def test_bump_fence_rejects_foreign_tenant_authority(admin_conn: PgConnection) -> None:
    base_a = create_discovery_fixture(admin_conn)
    base_b = create_discovery_fixture(admin_conn)
    queue_a = _queue(admin_conn, base_a)
    queue_b = _queue(admin_conn, base_b)
    org_a = base_a.organization_id
    org_b = base_b.organization_id
    try:
        admin_conn.execute("SET ROLE request_engine_schema_owner")
        admin_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)", (str(org_a),)
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(
                "SELECT request_engine.bump_recovery_source_revision(%s, %s)", (org_b, queue_b)
            )
        assert _revision(admin_conn, org_b, queue_b) is None
        admin_conn.execute(
            "SELECT request_engine.bump_recovery_source_revision(%s, %s)", (org_a, queue_a)
        )
        assert _revision(admin_conn, org_a, queue_a) == 1
    finally:
        admin_conn.execute("RESET ROLE")
        admin_conn.execute("SELECT set_config('request_engine.organization_id', '', false)")


def test_intake_mutation_schedules_fresh_reprojection(admin_conn: PgConnection) -> None:
    base = create_discovery_fixture(admin_conn)
    org = base.organization_id
    queue = _queue(admin_conn, base)
    assert _revision(admin_conn, org, queue) is None
    admin_conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)", (str(org),)
    )
    admin_conn.execute(
        "UPDATE request_engine.service_queue_intake_controls "
        "SET accepting=false, reason='recovery shortfall', updated_at=clock_timestamp() "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (org, queue),
    )
    assert _revision(admin_conn, org, queue) == 1
    assert _reassessment_count(admin_conn, org, queue) == 1
    admin_conn.execute(
        "UPDATE request_engine.service_queue_intake_controls "
        "SET accepting=false, reason='recovery shortfall', updated_at=clock_timestamp() "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (org, queue),
    )
    assert _revision(admin_conn, org, queue) == 1
    assert _reassessment_count(admin_conn, org, queue) == 1
    admin_conn.execute(
        "UPDATE request_engine.service_queue_intake_controls "
        "SET accepting=true, reason=NULL, updated_at=clock_timestamp() "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (org, queue),
    )
    assert _revision(admin_conn, org, queue) == 2
    assert _reassessment_count(admin_conn, org, queue) == 2
