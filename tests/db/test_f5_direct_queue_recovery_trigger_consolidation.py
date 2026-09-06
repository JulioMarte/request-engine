from uuid import UUID

import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_seed import PgConnection

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.integration,
    pytest.mark.invariant,
    pytest.mark.contract,
]

_SHARED_FUNCTION = "bump_direct_queue_recovery_source_revision"
_OLD_FUNCTIONS = {
    "bump_projection_policy_recovery_source_revision",
    "bump_queue_recovery_source_revision",
}
_EXPECTED_TRIGGERS = {
    "live_capacity_projection_policies_bump_recovery_source_revision",
    "queue_entries_bump_recovery_source_revision",
}


def _revision(conn: PgConnection, organization_id: UUID, queue_id: UUID) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.recovery_source_revisions "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (organization_id, queue_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_direct_queue_sources_share_one_freshness_bump(admin_conn: PgConnection) -> None:
    fixture = create_live_ops_fixture(admin_conn)
    org = fixture.organization_id
    queue = fixture.queue_id
    baseline = _revision(admin_conn, org, queue)

    admin_conn.execute(
        "UPDATE request_engine.queue_entries "
        "SET called_at = called_at + interval '1 second' "
        "WHERE organization_id=%s AND id=%s",
        (org, fixture.entry_b_id),
    )
    assert _revision(admin_conn, org, queue) == baseline + 1

    admin_conn.execute(
        "INSERT INTO request_engine.live_capacity_projection_policies "
        "(organization_id,service_queue_id,resource_id,location_id) "
        "VALUES (%s,%s,%s,%s)",
        (org, queue, fixture.resource_id, fixture.location_id),
    )
    assert _revision(admin_conn, org, queue) == baseline + 2


def test_direct_queue_recovery_trigger_topology_is_narrow(admin_conn: PgConnection) -> None:
    rows = admin_conn.execute(
        "SELECT t.tgname, p.proname, pg_get_triggerdef(t.oid) "
        "FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid=t.tgfoid "
        "JOIN pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='request_engine' AND NOT t.tgisinternal "
        "AND t.tgname = ANY(%s) ORDER BY t.tgname",
        (list(_EXPECTED_TRIGGERS),),
    ).fetchall()
    assert {str(row[0]) for row in rows} == _EXPECTED_TRIGGERS
    assert {str(row[1]) for row in rows} == {_SHARED_FUNCTION}
    for row in rows:
        definition = str(row[2])
        assert "AFTER INSERT OR DELETE OR UPDATE" in definition
        assert "FOR EACH ROW" in definition

    function_row = admin_conn.execute(
        "SELECT r.rolname, p.prosecdef, p.proconfig, "
        "COALESCE(bool_or(a.grantee=0 AND a.privilege_type='EXECUTE'), false) "
        "FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace "
        "JOIN pg_roles r ON r.oid=p.proowner "
        "LEFT JOIN LATERAL aclexplode(COALESCE(p.proacl, acldefault('f',p.proowner))) a ON true "
        "WHERE n.nspname='request_engine' AND p.proname=%s "
        "GROUP BY r.rolname,p.prosecdef,p.proconfig",
        (_SHARED_FUNCTION,),
    ).fetchone()
    assert function_row is not None
    assert function_row[0] == "request_engine_schema_owner"
    assert function_row[1] is True
    assert function_row[2] == ["search_path=pg_catalog, request_engine, pg_temp"]
    assert function_row[3] is False

    old_count = admin_conn.execute(
        "SELECT count(*) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='request_engine' AND p.proname = ANY(%s)",
        (list(_OLD_FUNCTIONS),),
    ).fetchone()
    assert old_count is not None
    assert int(old_count[0]) == 0
