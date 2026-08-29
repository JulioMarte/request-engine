# Direct PostgreSQL proof for the F5 fallback sweep discovery surface: it is a
# worker-only cross-tenant read over scheduled actions (RLS hardening untouched),
# and repair composition converges to exactly one action per revision.

from __future__ import annotations

import json

import psycopg
import pytest
from f5_sweep_support import sweep_world

from e2e import f5_scheduled_assessment_support as assessment_support
from e2e.operational_support import PgConnection
from request_engine.modules.operational_recovery.adapters.db.recovery_sweep_store import (
    PostgresRecoverySweepStore,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


@pytest.mark.asyncio
async def test_sweep_discovery_is_worker_only_cross_tenant_and_converges(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    first = await sweep_world(admin_conn, command_session_factory, "f5-sweep-tenant-a")
    second = await sweep_world(admin_conn, command_session_factory, "f5-sweep-tenant-b")
    store = PostgresRecoverySweepStore(worker_session_factory, command_session_factory)
    scopes = await store.find_scopes(limit=500, offset=0)
    assert {scope.organization_id for scope in scopes} >= {
        first.organization_id,
        second.organization_id,
    }

    app_conn: PgConnection = psycopg.connect(admin_conn.info.dsn, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        with pytest.raises(psycopg.Error) as denied:
            app_conn.execute("SELECT request_cmd.find_recovery_sweep_scopes(1)")
        assert denied.value.sqlstate == "42501"
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,false)",
            (str(first.organization_id),),
        )
        with pytest.raises(psycopg.Error) as forged:
            app_conn.execute(
                "SELECT request_cmd.lock_recovery_source_revision(%s,%s)",
                (second.organization_id, second.queue_id),
            )
        assert forged.value.sqlstate == "23514"
    finally:
        app_conn.close()

    revision = assessment_support.current_source_revision(admin_conn, first)
    key = f"f5-reassessment:{first.queue_id}:{revision}"
    duplicate = (
        "INSERT INTO request_engine.scheduled_actions "
        "(organization_id,owner_module,action_type,action_version,subject_kind,"
        "subject_id,payload,dedupe_key,execute_at,next_attempt_at,max_attempts) "
        "VALUES (%s,'operational_recovery','reassess_recovery_scope',1,'ServiceQueue',"
        "%s,%s::jsonb,%s,clock_timestamp(),clock_timestamp(),8) "
        "ON CONFLICT (organization_id, dedupe_key) DO NOTHING"
    )
    payload = json.dumps({"service_queue_id": str(first.queue_id), "source_revision": revision})
    second_insert = admin_conn.execute(
        duplicate,
        (first.organization_id, first.queue_id, payload, key),
    )
    assert second_insert.rowcount == 0
    count_row = admin_conn.execute(
        "SELECT count(*) FROM request_engine.scheduled_actions "
        "WHERE organization_id=%s AND dedupe_key=%s",
        (first.organization_id, key),
    ).fetchone()
    assert count_row is not None and count_row[0] == 1
