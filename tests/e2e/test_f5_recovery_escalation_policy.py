from __future__ import annotations

import pytest

from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryIncidentStatus,
)
from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f5_delay_communication_support import add_delay_walk_in
from .f5_escalation_support import escalation_rows, unresolved_incident_state
from .f5_recovery_support import f5_actor, restrict_source_to_first_slots
from .f5_recovery_world import prepare_recovery_world
from .f5_scheduled_assessment_support import current_source_revision, lease_reassessment
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


async def test_f5_scheduled_assessment_records_newly_material_escalation_policy(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-escalation-newly-material")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await prepare_recovery_world(client, e2e_admin_conn, sandbox)
    revision = current_source_revision(e2e_admin_conn, sandbox)
    handler = build_recovery_assessment_handler(e2e_session_factory)
    lease = lease_reassessment(e2e_admin_conn, sandbox, revision)

    result = await handler.handle(lease)
    assert result.applied is True and result.incident is not None
    outcome = result.escalation
    assert outcome is not None
    assert outcome.operator_escalation_required is True
    assert outcome.escalation_reason == "newly_material"
    assert outcome.customer_impact_required is True
    assert outcome.impact_recipient_party_ids == (sandbox.party_id,)
    first_rows = [(revision, 2, True, "newly_material", True, [str(sandbox.party_id)])]
    assert escalation_rows(e2e_admin_conn, sandbox) == first_rows

    replay = await handler.handle(lease)
    assert replay.applied is False and replay.escalation is None
    assert escalation_rows(e2e_admin_conn, sandbox) == first_rows

    e2e_admin_conn.execute(
        "INSERT INTO request_engine.location_hours_exceptions "
        "(organization_id,location_id,during,exception_kind,reason,active) "
        "VALUES (%s,%s,tstzrange(clock_timestamp()+interval '3 days',"
        "clock_timestamp()+interval '3 days 1 hour','[)'),'available','stale policy',true)",
        (sandbox.organization_id, sandbox.location_id),
    )
    stale = await handler.handle(lease)
    assert stale.applied is False and stale.stale is True and stale.escalation is None
    assert escalation_rows(e2e_admin_conn, sandbox) == first_rows


async def test_f5_escalation_worsens_when_delay_becomes_capacity_shortfall(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-escalation-worsening")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        world = await prepare_recovery_world(
            client,
            e2e_admin_conn,
            sandbox,
            capacity_slots=10,
        )
        await add_delay_walk_in(client, e2e_admin_conn, sandbox, world)
    handler = build_recovery_assessment_handler(e2e_session_factory)
    delay_revision = current_source_revision(e2e_admin_conn, sandbox)
    first = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, delay_revision))
    assert first.applied is True and first.incident is not None
    assert first.escalation is not None
    assert first.escalation.customer_impact_required is False
    assert escalation_rows(e2e_admin_conn, sandbox) == [
        (delay_revision, 1, True, "newly_material", False, [])
    ]

    restrict_source_to_first_slots(e2e_admin_conn, sandbox, list(world.slots), count=6)
    shortfall_revision = current_source_revision(e2e_admin_conn, sandbox)
    assert shortfall_revision > delay_revision
    second = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, shortfall_revision))
    assert second.applied is True and second.escalation is not None
    assert second.escalation.escalation_reason == "worsening_severity"
    assert second.escalation.operator_escalation_required is True
    assert second.escalation.customer_impact_required is True
    assert second.escalation.impact_recipient_party_ids == (sandbox.party_id,)
    rows = escalation_rows(e2e_admin_conn, sandbox)
    assert rows == [
        (delay_revision, 1, True, "newly_material", False, []),
        (
            shortfall_revision,
            2,
            True,
            "worsening_severity",
            True,
            [str(sandbox.party_id)],
        ),
    ]


async def test_f5_escalation_clears_only_from_fresh_resolving_assessment(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-escalation-resolution")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await prepare_recovery_world(client, e2e_admin_conn, sandbox)
    handler = build_recovery_assessment_handler(e2e_session_factory)
    revision = current_source_revision(e2e_admin_conn, sandbox)
    first = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, revision))
    assert first.applied is True and first.escalation is not None
    assert first.escalation.customer_impact_required is True

    seed_today_schedule(e2e_admin_conn, sandbox)
    restored_revision = current_source_revision(e2e_admin_conn, sandbox)
    assert restored_revision > revision
    second = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, restored_revision))
    assert second.applied is True and second.incident is not None
    assert second.incident.status is RecoveryIncidentStatus.RESOLVED
    assert second.escalation is not None
    assert second.escalation.operator_escalation_required is False
    assert second.escalation.customer_impact_required is False
    assert escalation_rows(e2e_admin_conn, sandbox)[-1] == (
        restored_revision,
        0,
        False,
        None,
        False,
        [],
    )
    assert unresolved_incident_state(e2e_admin_conn, sandbox) == ("resolved", 0)
