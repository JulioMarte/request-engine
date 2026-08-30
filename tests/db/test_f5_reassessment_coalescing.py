# Direct PostgreSQL proof for F5 change-storm coalescing (docs/v3/10, contract 32
# section 5): the shared enqueue primitive supersedes older pending reassessments
# so a real trigger storm leaves exactly one pending action at the maximum
# revision, a deterministic two-connection bump race converges to one survivor,
# and the bounded sweep repairs through the same primitive without resurrecting
# cancelled actions.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import psycopg
import pytest
from f5_sweep_support import sweep_world

from e2e import f5_scheduled_assessment_support as assessment_support
from e2e.f5_recovery_support import f5_actor
from e2e.f5_recovery_world import prepare_recovery_world
from e2e.operational_support import PgConnection
from e2e.tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox
from request_engine.bootstrap.recovery_sweep import build_recovery_sweep
from request_engine.platform.db.session import SessionFactory

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.contract,
]

STORM_BUMPS = 50

_BUMP_SQL = (
    "INSERT INTO request_engine.location_hours_exceptions "
    "(organization_id,location_id,during,exception_kind,reason,active) "
    "VALUES (%s,%s,tstzrange(%s,%s,'[)'),'available','storm',true)"
)


def _bump(conn: PgConnection, sandbox: TenantSandbox, offset: int) -> None:
    start = datetime.now(UTC) + timedelta(days=5, hours=offset)
    end = start + timedelta(hours=1)
    conn.execute(_BUMP_SQL, (sandbox.organization_id, sandbox.location_id, start, end))


def _action_states(admin_conn: PgConnection, organization_id: object) -> dict[int, str]:
    rows = admin_conn.execute(
        "SELECT (payload->>'source_revision')::int, status "
        "FROM request_engine.scheduled_actions WHERE organization_id=%s "
        "AND action_type='reassess_recovery_scope' ORDER BY 1",
        (organization_id,),
    ).fetchall()
    return {int(revision): str(status) for revision, status in rows}


def _assert_single_pending(admin_conn: PgConnection, organization_id: object) -> int:
    states = _action_states(admin_conn, organization_id)
    max_revision = max(states)
    assert [r for r, s in states.items() if s == "pending"] == [max_revision]
    assert all(s == "cancelled" for r, s in states.items() if r < max_revision)
    return max_revision


async def _prepared_world(
    admin_conn: PgConnection, session_factory: SessionFactory, label: str
) -> TenantSandbox:
    sandbox = seed_tenant_sandbox(admin_conn, label)
    async with client_with_actors(session_factory, {sandbox.token: f5_actor(sandbox)}) as client:
        await prepare_recovery_world(client, admin_conn, sandbox)
    return sandbox


async def _single_pending_world(
    admin_conn: PgConnection, session_factory: SessionFactory, label: str, bumps: int
) -> tuple[TenantSandbox, dict[int, str]]:
    sandbox = await _prepared_world(admin_conn, session_factory, label)
    for offset in range(bumps):
        _bump(admin_conn, sandbox, offset)
    states = _action_states(admin_conn, sandbox.organization_id)
    return sandbox, states


async def test_storm_of_triggers_leaves_exactly_one_pending_at_the_max_revision(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    sandbox, states = await _single_pending_world(
        admin_conn, command_session_factory, "f5-coalescing-storm", STORM_BUMPS
    )
    max_revision = _assert_single_pending(admin_conn, sandbox.organization_id)
    assert len(states) >= STORM_BUMPS
    assert assessment_support.current_source_revision(admin_conn, sandbox) == max_revision


async def test_concurrent_bumps_on_two_connections_converge_to_one_pending(
    admin_conn: PgConnection, command_session_factory: SessionFactory, pg_conninfo: str
) -> None:
    sandbox = await _prepared_world(admin_conn, command_session_factory, "f5-coalescing-race")
    session_a = psycopg.connect(pg_conninfo, autocommit=False)
    session_b = psycopg.connect(pg_conninfo, autocommit=False)
    for session in (session_a, session_b):
        session.execute("SET lock_timeout = '10s'")
    entered_b = Event()
    failure: list[Exception] = []

    def bump_b() -> None:
        try:
            entered_b.wait(timeout=10)
            _bump(session_b, sandbox, 24)
            session_b.commit()
        except Exception as exc:  # noqa: BLE001 - surfaced through the failure assertion
            failure.append(exc)

    worker = Thread(target=bump_b)
    worker.start()
    entered_b.wait(timeout=10)
    _bump(session_a, sandbox, 0)
    session_a.commit()
    worker.join(timeout=15)
    assert not failure and not worker.is_alive()
    session_a.close()
    session_b.close()
    _assert_single_pending(admin_conn, sandbox.organization_id)


async def test_sweep_repairs_through_the_shared_enqueue_without_resurrecting_cancellations(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    sandbox = await sweep_world(admin_conn, command_session_factory, "f5-coalescing-sweep")
    superseded = assessment_support.current_source_revision(admin_conn, sandbox)
    _bump(admin_conn, sandbox, 1)
    revision = assessment_support.current_source_revision(admin_conn, sandbox)
    states = _action_states(admin_conn, sandbox.organization_id)
    assert states[superseded] == "cancelled"
    assert [r for r, s in states.items() if s == "pending"] == [revision]
    sweep = build_recovery_sweep(worker_session_factory, command_session_factory)

    assert await sweep.run_once() == ()

    admin_conn.execute(
        "DELETE FROM request_engine.scheduled_actions WHERE organization_id=%s AND dedupe_key=%s",
        (sandbox.organization_id, f"f5-reassessment:{sandbox.queue_id}:{revision}"),
    )
    assert await sweep.run_once() != ()
    states = _action_states(admin_conn, sandbox.organization_id)
    assert states[superseded] == "cancelled"
    assert [r for r, s in states.items() if s == "pending"] == [revision]
