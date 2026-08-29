# Direct PostgreSQL proof for the bounded F5 fallback sweep (docs/v3/10): a lost
# wake-up is repaired with the exact trigger identity and processed by the real
# handler; live actions are a clean no-op; dead/cancelled are never resurrected;
# discovery is a worker-only cross-tenant surface and repair composition
# converges to one action per revision.

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql

from e2e import f5_scheduled_assessment_support as assessment_support
from e2e.f5_recovery_support import f5_actor
from e2e.f5_recovery_world import prepare_recovery_world
from e2e.operational_support import PgConnection
from e2e.tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox
from request_engine.bootstrap.recovery_sweep import build_recovery_sweep
from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.modules.operational_recovery.adapters.db.recovery_sweep_store import (
    PostgresRecoverySweepStore,
)
from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


def _async_url(pg_conninfo: str, user: str, password: str) -> str:
    parts = dict(part.split("=", 1) for part in pg_conninfo.split())
    return (
        f"postgresql+asyncpg://{user}:{password}@{parts['host']}:{parts['port']}/{parts['dbname']}"
    )


@pytest_asyncio.fixture
async def worker_session_factory(pg_conninfo: str) -> AsyncIterator[SessionFactory]:
    role = f"request_engine_worker_sweep_{uuid4().hex[:10]}"
    password = uuid4().hex
    admin: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE request_engine_worker").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        engine = create_postgres_engine(_async_url(pg_conninfo, role, password))
        try:
            yield create_session_factory(engine)
        finally:
            await engine.dispose()
        admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
    finally:
        admin.close()


async def _world(
    admin_conn: PgConnection, session_factory: SessionFactory, label: str
) -> TenantSandbox:
    sandbox = seed_tenant_sandbox(admin_conn, label)
    async with client_with_actors(session_factory, {sandbox.token: f5_actor(sandbox)}) as client:
        await prepare_recovery_world(client, admin_conn, sandbox)
    return sandbox


def _action_row(conn: PgConnection, org: UUID, key: str) -> tuple[object, ...] | None:
    row = conn.execute(
        "SELECT owner_module,action_type,action_version,subject_kind,subject_id,payload,"
        "status,max_attempts FROM request_engine.scheduled_actions "
        "WHERE organization_id=%s AND dedupe_key=%s",
        (org, key),
    ).fetchone()
    return tuple(row) if row else None


def _delete_current_action(conn: PgConnection, sandbox: TenantSandbox, revision: int) -> None:
    conn.execute(
        "DELETE FROM request_engine.scheduled_actions WHERE organization_id=%s AND dedupe_key=%s",
        (sandbox.organization_id, f"f5-reassessment:{sandbox.queue_id}:{revision}"),
    )


@pytest.mark.asyncio
async def test_sweep_repairs_lost_wakeup_with_exact_trigger_identity(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    sandbox = await _world(admin_conn, command_session_factory, "f5-sweep-repair")
    revision = assessment_support.current_source_revision(admin_conn, sandbox)
    sweep = build_recovery_sweep(worker_session_factory, command_session_factory)
    key = f"f5-reassessment:{sandbox.queue_id}:{revision}"

    assert await sweep.run_once() == ()

    _delete_current_action(admin_conn, sandbox, revision)
    outcomes = await sweep.run_once()
    assert [outcome.detail for outcome in outcomes] == ["recovery_sweep_repaired"]
    row = _action_row(admin_conn, sandbox.organization_id, key)
    assert row is not None
    assert row[:6] == (
        "operational_recovery",
        "reassess_recovery_scope",
        1,
        "ServiceQueue",
        sandbox.queue_id,
        {"service_queue_id": str(sandbox.queue_id), "source_revision": revision},
    )
    assert row[6:] == ("pending", 8)

    lease = assessment_support.lease_reassessment(admin_conn, sandbox, revision)
    handler = build_recovery_assessment_handler(command_session_factory)
    commit = await handler.handle(lease)
    assert commit.applied is True and commit.incident is not None
    assert assessment_support.incident_revision(admin_conn, sandbox) == (revision, 1)
    assert await sweep.run_once() == ()


@pytest.mark.asyncio
async def test_sweep_never_resurrects_live_or_terminal_actions(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    sandbox = await _world(admin_conn, command_session_factory, "f5-sweep-terminal")
    revision = assessment_support.current_source_revision(admin_conn, sandbox)
    sweep = build_recovery_sweep(worker_session_factory, command_session_factory)
    key = f"f5-reassessment:{sandbox.queue_id}:{revision}"
    for status in ("pending", "completed", "dead", "cancelled"):
        admin_conn.execute(
            "UPDATE request_engine.scheduled_actions SET status=%s, "
            "completed_at=(CASE WHEN %s='completed' THEN clock_timestamp() ELSE NULL END) "
            "WHERE organization_id=%s AND dedupe_key=%s",
            (status, status, sandbox.organization_id, key),
        )
        updated_at = admin_conn.execute(
            "SELECT updated_at FROM request_engine.scheduled_actions "
            "WHERE organization_id=%s AND dedupe_key=%s",
            (sandbox.organization_id, key),
        ).fetchone()
        assert await sweep.run_once() == ()
        remaining = _action_row(admin_conn, sandbox.organization_id, key)
        assert remaining is not None and remaining[6] == status
        count_row = admin_conn.execute(
            "SELECT count(*) FROM request_engine.scheduled_actions "
            "WHERE organization_id=%s AND dedupe_key=%s",
            (sandbox.organization_id, key),
        ).fetchone()
        assert count_row is not None and count_row[0] == 1
        assert (
            admin_conn.execute(
                "SELECT updated_at FROM request_engine.scheduled_actions "
                "WHERE organization_id=%s AND dedupe_key=%s",
                (sandbox.organization_id, key),
            ).fetchone()
            == updated_at
        )


@pytest.mark.asyncio
async def test_sweep_discovery_is_worker_only_cross_tenant_and_converges(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    first = await _world(admin_conn, command_session_factory, "f5-sweep-tenant-a")
    second = await _world(admin_conn, command_session_factory, "f5-sweep-tenant-b")
    store = PostgresRecoverySweepStore(worker_session_factory, command_session_factory)
    scopes = await store.find_scopes(limit=500, offset=0)
    assert {scope.organization_id for scope in scopes} >= {
        first.organization_id,
        second.organization_id,
    }

    app_conn: PgConnection = psycopg.connect(admin_conn.info.dsn, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        with pytest.raises(psycopg.Error) as raised:
            app_conn.execute("SELECT request_cmd.find_recovery_sweep_scopes(1)")
        assert raised.value.sqlstate == "42501"
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,false)",
            (str(first.organization_id),),
        )
        with pytest.raises(psycopg.Error) as raised:
            app_conn.execute(
                "SELECT request_cmd.lock_recovery_source_revision(%s,%s)",
                (second.organization_id, second.queue_id),
            )
        assert raised.value.sqlstate == "23514"
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
