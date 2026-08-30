from __future__ import annotations

import pytest

from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryIncidentStatus,
)
from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f5_escalation_support import (
    advance_source_revision,
    automatic_recovery_facts,
    autonomous_impact_task,
    escalation_rows,
    escalation_world,
    unresolved_incident_state,
)
from .f5_recovery_support import restrict_source_to_first_slots
from .f5_scheduled_assessment_support import current_source_revision, lease_reassessment
from .operational_support import PgConnection

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
    sandbox, _, handler = await escalation_world(
        e2e_admin_conn, e2e_session_factory, "f5-escalation-material"
    )
    revision = current_source_revision(e2e_admin_conn, sandbox)
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
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 1, 1)
    task = autonomous_impact_task(
        e2e_admin_conn, sandbox, result.incident.id, revision
    )
    assert task[1:] == (
        "operational_recovery_impact",
        "operational_recovery.impact",
        "service",
        "operational_recovery_automation",
    )

    replay = await handler.handle(lease)
    assert replay.applied is False and replay.escalation is None
    assert escalation_rows(e2e_admin_conn, sandbox) == first_rows
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 1, 1)

    advance_source_revision(e2e_admin_conn, sandbox)
    stale = await handler.handle(lease)
    assert stale.applied is False and stale.stale is True and stale.escalation is None
    assert escalation_rows(e2e_admin_conn, sandbox) == first_rows
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 1, 1)


async def test_f5_escalation_worsens_when_delay_becomes_capacity_shortfall(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox, world, handler = await escalation_world(
        e2e_admin_conn,
        e2e_session_factory,
        "f5-escalation-worsening",
        capacity_slots=10,
        walk_in=True,
    )
    delay_revision = current_source_revision(e2e_admin_conn, sandbox)
    first = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, delay_revision))
    assert first.applied is True and first.incident is not None
    assert first.escalation is not None
    assert first.escalation.customer_impact_required is False
    assert escalation_rows(e2e_admin_conn, sandbox) == [
        (delay_revision, 1, True, "newly_material", False, [])
    ]
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 0, 0)

    restrict_source_to_first_slots(e2e_admin_conn, sandbox, list(world.slots), count=6)
    shortfall_revision = current_source_revision(e2e_admin_conn, sandbox)
    assert shortfall_revision > delay_revision
    second = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, shortfall_revision))
    assert second.applied is True and second.escalation is not None
    assert second.escalation.escalation_reason == "worsening_severity"
    assert second.escalation.customer_impact_required is True
    assert second.escalation.impact_recipient_party_ids == (sandbox.party_id,)
    rows = escalation_rows(e2e_admin_conn, sandbox)
    recipients = [str(sandbox.party_id)]
    assert len(rows) == 2
    assert rows[0] == (delay_revision, 1, True, "newly_material", False, [])
    assert rows[1] == (shortfall_revision, 2, True, "worsening_severity", True, recipients)
    assert second.incident is not None
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 1, 1)
    assert autonomous_impact_task(
        e2e_admin_conn, sandbox, second.incident.id, shortfall_revision
    )[1:] == (
        "operational_recovery_impact",
        "operational_recovery.impact",
        "service",
        "operational_recovery_automation",
    )


async def test_f5_escalation_clears_only_from_fresh_resolving_assessment(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox, _, handler = await escalation_world(
        e2e_admin_conn, e2e_session_factory, "f5-escalation-resolution"
    )
    revision = current_source_revision(e2e_admin_conn, sandbox)
    first = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, revision))
    assert first.applied is True and first.escalation is not None
    assert first.escalation.customer_impact_required is True
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 1, 1)

    seed_today_schedule(e2e_admin_conn, sandbox)
    restored_revision = current_source_revision(e2e_admin_conn, sandbox)
    assert restored_revision > revision
    second = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, restored_revision))
    assert second.applied is True and second.incident is not None
    assert second.incident.status is RecoveryIncidentStatus.RESOLVED
    assert second.escalation is not None
    assert second.escalation.operator_escalation_required is False
    assert second.escalation.customer_impact_required is False
    cleared: tuple[object, ...] = (restored_revision, 0, False, None, False, [])
    assert escalation_rows(e2e_admin_conn, sandbox)[-1] == cleared
    assert unresolved_incident_state(e2e_admin_conn, sandbox) == ("resolved", 0)
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 1, 1)
