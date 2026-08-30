# Direct PostgreSQL proof for the F5 change-storm skip-ahead (docs/v3/10 fence,
# docs/v3/32 section 5): a storm of real material bumps drains through the real
# scheduled handler with exactly one F4 computation and one applied commit at the
# maximum revision, and a bump landing between the advisory pre-check and the commit
# still loses at the authoritative commit fence.

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from e2e import f5_automatic_proposal_support as proposal_support
from e2e import f5_scheduled_assessment_support as assessment_support
from e2e.f5_recovery_support import f5_actor
from e2e.f5_recovery_world import prepare_recovery_world
from e2e.operational_support import PgConnection
from e2e.tenant_sandbox import TenantSandbox, client_with_actors, seed_tenant_sandbox
from request_engine.bootstrap import recovery_worker
from request_engine.modules.booking.api import live_capacity as booking_live
from request_engine.modules.booking.api.recovery import build_recovery_booking_port
from request_engine.modules.delivery.api import live_capacity as delivery_live
from request_engine.modules.live_capacity.api.recovery import build_recovery_capacity_source
from request_engine.modules.live_capacity.contracts import recovery as recovery_contracts
from request_engine.modules.operational_recovery.adapters.db import (
    scheduled_assessment_fence,
    scheduled_assessment_store,
)
from request_engine.modules.operational_recovery.adapters.worker import scheduled_assessment
from request_engine.modules.queue.api import live_capacity as queue_live
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]
pytestmark += [pytest.mark.invariant, pytest.mark.contract, pytest.mark.adversarial]

STORM_BUMPS = 40

_BUMP_SQL = (
    "INSERT INTO request_engine.location_hours_exceptions "
    "(organization_id,location_id,during,exception_kind,reason,active) "
    "VALUES (%s,%s,tstzrange(%s,%s,'[)'),'available','storm',true)"
)


def _bump(conn: PgConnection, sandbox: TenantSandbox, offset: int) -> None:
    start = datetime.now(UTC) + timedelta(days=5, hours=offset)
    window = (sandbox.organization_id, sandbox.location_id, start, start + timedelta(hours=1))
    conn.execute(_BUMP_SQL, window)


class _CountingCapacity:
    def __init__(
        self, inner: recovery_contracts.RecoveryCapacitySource, hook: Callable[[], None]
    ) -> None:
        self._inner, self._hook, self.calls = inner, hook, 0

    async def assess_recovery_capacity(
        self, *, organization_id: UUID, service_queue_id: UUID
    ) -> recovery_contracts.RecoveryCapacityAssessment:
        self.calls += 1
        self._hook()
        return await self._inner.assess_recovery_capacity(
            organization_id=organization_id, service_queue_id=service_queue_id
        )


def _instrumented_handler(
    session_factory: SessionFactory, hook: Callable[[], None]
) -> tuple[scheduled_assessment.RecoveryAssessmentScheduledHandler, _CountingCapacity]:
    real = build_recovery_capacity_source(
        session_factory,
        booking_source=booking_live.build_live_capacity_source(),
        queue_source=queue_live.build_live_capacity_source(),
        delivery_source=delivery_live.build_live_capacity_source(),
    )
    capacity = _CountingCapacity(real, hook)
    real_booking = build_recovery_booking_port(session_factory)
    handler = scheduled_assessment.RecoveryAssessmentScheduledHandler(
        capacity,
        real_booking,
        scheduled_assessment_store.PostgresScheduledAssessmentStore(session_factory),
        scheduled_assessment_fence.RecoverySourceRevisionReader(session_factory),
        recovery_worker.build_recovery_impact_automation(session_factory),
        recovery_worker.build_recovery_reschedule_autonomy(session_factory, capacity, real_booking),
    )
    return handler, capacity


async def _prepared_world(
    admin_conn: PgConnection, session_factory: SessionFactory, label: str
) -> TenantSandbox:
    sandbox = seed_tenant_sandbox(admin_conn, label)
    async with client_with_actors(session_factory, {sandbox.token: f5_actor(sandbox)}) as client:
        await prepare_recovery_world(client, admin_conn, sandbox)
    return sandbox


async def test_change_storm_computes_f4_once_and_applies_only_the_max_revision(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    sandbox = await _prepared_world(admin_conn, command_session_factory, "f5-reassessment-storm")
    for offset in range(STORM_BUMPS):
        _bump(admin_conn, sandbox, offset)
    handler, capacity = _instrumented_handler(command_session_factory, lambda: None)
    rows = admin_conn.execute(
        "SELECT (payload->>'source_revision')::int FROM request_engine.scheduled_actions "
        "WHERE organization_id=%s AND action_type='reassess_recovery_scope' AND subject_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchall()
    revisions = sorted(int(row[0]) for row in rows)
    assert len(revisions) >= STORM_BUMPS + 1
    applied: list[int] = []
    for revision in revisions:
        lease = assessment_support.lease_reassessment(admin_conn, sandbox, revision)
        commit = await handler.handle(lease)
        assert commit.stale is (revision != revisions[-1])
        if commit.applied:
            applied.append(revision)
            assert commit.incident is not None
    assert applied == [revisions[-1]] and capacity.calls == 1
    assert assessment_support.incident_revision(admin_conn, sandbox) == (revisions[-1], 1)
    proposals = proposal_support.automatic_proposals(admin_conn, sandbox)
    assert [p.source_revision for p in proposals] == [revisions[-1]]


async def test_bump_during_assessment_still_loses_at_the_commit_fence(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    sandbox = await _prepared_world(admin_conn, command_session_factory, "f5-storm-fence")
    revision = assessment_support.current_source_revision(admin_conn, sandbox)
    handler, capacity = _instrumented_handler(
        command_session_factory, lambda: _bump(admin_conn, sandbox, STORM_BUMPS)
    )
    lease = assessment_support.lease_reassessment(admin_conn, sandbox, revision)
    commit = await handler.handle(lease)
    assert (commit.applied, commit.stale, capacity.calls) == (False, True, 1)
    assert commit.incident is None and commit.proposal_id is None
    assert assessment_support.current_source_revision(admin_conn, sandbox) == revision + 1
    assert assessment_support.incident_revision(admin_conn, sandbox) is None
