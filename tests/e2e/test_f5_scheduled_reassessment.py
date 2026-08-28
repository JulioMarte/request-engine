from __future__ import annotations

import pytest

from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.modules.booking.api.live_capacity import (
    build_live_capacity_source as build_booking_live_capacity_source,
)
from request_engine.modules.delivery.api.live_capacity import (
    build_live_capacity_source as build_delivery_live_capacity_source,
)
from request_engine.modules.live_capacity.api.recovery import build_recovery_capacity_source
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_store import (
    PostgresScheduledAssessmentStore,
)
from request_engine.modules.queue.api.live_capacity import (
    build_live_capacity_source as build_queue_live_capacity_source,
)
from request_engine.platform.db.session import SessionFactory

from .f5_recovery_support import f5_actor
from .f5_recovery_world import prepare_recovery_world
from .f5_scheduled_assessment_support import (
    current_source_revision,
    incident_revision,
    lease_reassessment,
)
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.provenance,
    pytest.mark.adversarial,
]


async def _material_world(
    conn: PgConnection,
    session_factory: SessionFactory,
    label: str,
):
    sandbox = seed_tenant_sandbox(conn, label)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(session_factory, actors) as client:
        await prepare_recovery_world(client, conn, sandbox)
    return sandbox


async def test_f5_scheduled_reassessment_persists_current_material_truth(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = await _material_world(
        e2e_admin_conn, e2e_session_factory, "f5-scheduled-reassessment-current"
    )
    revision = current_source_revision(e2e_admin_conn, sandbox)
    lease = lease_reassessment(e2e_admin_conn, sandbox, revision)

    result = await build_recovery_assessment_handler(e2e_session_factory).handle(lease)

    assert result.applied is True
    assert result.stale is False
    assert result.incident is not None
    assert result.incident.source_revision == revision
    assert incident_revision(e2e_admin_conn, sandbox) == (revision, 1)


async def test_f5_scheduled_reassessment_cannot_commit_superseded_truth(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = await _material_world(
        e2e_admin_conn, e2e_session_factory, "f5-scheduled-reassessment-stale"
    )
    revision = current_source_revision(e2e_admin_conn, sandbox)
    lease = lease_reassessment(e2e_admin_conn, sandbox, revision)
    capacity = build_recovery_capacity_source(
        e2e_session_factory,
        booking_source=build_booking_live_capacity_source(),
        queue_source=build_queue_live_capacity_source(),
        delivery_source=build_delivery_live_capacity_source(),
    )
    assessment = await capacity.assess_recovery_capacity(
        organization_id=sandbox.organization_id,
        service_queue_id=sandbox.queue_id,
    )
    assert assessment.checkpoint.recovery_source_revision == revision

    e2e_admin_conn.execute(
        "INSERT INTO request_engine.location_hours_exceptions "
        "(organization_id,location_id,during,exception_kind,reason,active) "
        "VALUES (%s,%s,tstzrange(clock_timestamp()+interval '2 days',"
        "clock_timestamp()+interval '2 days 1 hour','[)'),'available','stale fence',true)",
        (sandbox.organization_id, sandbox.location_id),
    )
    assert current_source_revision(e2e_admin_conn, sandbox) == revision + 1

    result = await PostgresScheduledAssessmentStore(e2e_session_factory).commit(
        organization_id=sandbox.organization_id,
        service_queue_id=sandbox.queue_id,
        target_source_revision=revision,
        action_id=lease.id,
        claim_token=lease.claim_token,
        assessment=assessment,
    )
    assert result.applied is False
    assert result.stale is True
    assert result.incident is None
    assert incident_revision(e2e_admin_conn, sandbox) is None
