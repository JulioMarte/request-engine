# Direct PostgreSQL proof for the bounded F5 fallback sweep (docs/v3/10): a lost
# wake-up is repaired with the exact trigger identity and processed by the real
# handler, replay is a clean no-op, and live or terminal actions are never
# resurrected by the sweep.

from __future__ import annotations

import pytest
from e2e import f5_scheduled_assessment_support as assessment_support
from e2e.operational_support import PgConnection
from request_engine.bootstrap.recovery_sweep import build_recovery_sweep
from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.platform.db.session import SessionFactory

from f5_sweep_support import (
    delete_sweep_action,
    sweep_action_row,
    sweep_world,
    worker_session_factory,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


@pytest.mark.asyncio
async def test_sweep_repairs_lost_wakeup_with_exact_trigger_identity(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    sandbox = await sweep_world(admin_conn, command_session_factory, "f5-sweep-repair")
    revision = assessment_support.current_source_revision(admin_conn, sandbox)
    sweep = build_recovery_sweep(worker_session_factory, command_session_factory)
    key = f"f5-reassessment:{sandbox.queue_id}:{revision}"

    assert await sweep.run_once() == ()

    delete_sweep_action(admin_conn, sandbox, revision)
    outcomes = await sweep.run_once()
    assert [outcome.detail for outcome in outcomes] == ["recovery_sweep_repaired"]
    row = sweep_action_row(admin_conn, sandbox.organization_id, key)
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
    sandbox = await sweep_world(admin_conn, command_session_factory, "f5-sweep-terminal")
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
        remaining = sweep_action_row(admin_conn, sandbox.organization_id, key)
        assert remaining is not None and remaining[6] == status
        count_row = admin_conn.execute(
            "SELECT count(*) FROM request_engine.scheduled_actions "
            "WHERE organization_id=%s AND dedupe_key=%s",
            (sandbox.organization_id, key),
        ).fetchone()
        assert count_row is not None and count_row[0] == 1
        assert admin_conn.execute(
            "SELECT updated_at FROM request_engine.scheduled_actions "
            "WHERE organization_id=%s AND dedupe_key=%s",
            (sandbox.organization_id, key),
        ).fetchone() == updated_at
