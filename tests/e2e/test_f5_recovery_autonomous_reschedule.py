from __future__ import annotations

import pytest

from request_engine.modules.operational_recovery.adapters.worker.scheduled_assessment import (
    RecoveryAssessmentScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory

from .f5_autonomy_support import (
    AffectedFact,
    autonomous_action_rows,
    autonomous_rescheduled_tasks,
    grant_autonomy_policy,
    open_incident_status,
    proposal_affected,
    reservation_window,
)
from .f5_escalation_support import escalation_world
from .f5_scheduled_assessment_support import current_source_revision, lease_reassessment
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

_AUTOMATION_ATTRIBUTION = ("service", "operational_recovery_automation")


async def _open_incident(
    conn: PgConnection, session_factory: SessionFactory, label: str
) -> tuple[TenantSandbox, RecoveryAssessmentScheduledHandler, list[AffectedFact]]:
    sandbox, _, handler = await escalation_world(conn, session_factory, label)
    revision = current_source_revision(conn, sandbox)
    lease = lease_reassessment(conn, sandbox, revision)
    opened = await handler.handle(lease)
    assert opened.applied is True and opened.incident is not None
    assert opened.proposal_id is not None
    affected = proposal_affected(conn, sandbox.organization_id, opened.proposal_id)
    assert affected, "world must produce envelope-relevant affected reservations"
    return sandbox, handler, affected


async def test_f5_autonomy_reschedules_within_operator_envelope(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox, handler, affected = await _open_incident(
        e2e_admin_conn, e2e_session_factory, "f5-autonomy-reschedule"
    )
    original = {r: reservation_window(e2e_admin_conn, sandbox, r) for r, *_ in affected}
    assert autonomous_action_rows(e2e_admin_conn, sandbox) == []
    body = await grant_autonomy_policy(
        e2e_session_factory,
        sandbox,
        max_delay_minutes=240,
        max_auto_actions_per_incident=len(affected) + 1,
    )
    assert (body["enabled"], body["granted_by"]) == (True, str(sandbox.principal_id))

    for _ in range(len(affected) + 1):
        revision = current_source_revision(e2e_admin_conn, sandbox)
        await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, revision))
        if open_incident_status(e2e_admin_conn, sandbox) == "resolved":
            break

    actions = autonomous_action_rows(e2e_admin_conn, sandbox)
    assert len(actions) == len(affected)
    assert all(row[:3] == ("reschedule", "succeeded", None) for row in actions)
    assert all(row[3:] == _AUTOMATION_ATTRIBUTION for row in actions)
    tasks = autonomous_rescheduled_tasks(e2e_admin_conn, sandbox)
    assert len(tasks) == len(affected)
    assert all(task[0] == "operational_recovery_rescheduled" for task in tasks)
    assert all(task[1] == "operational_recovery.rescheduled" for task in tasks)
    assert {task[3] for task in tasks} == {"operational_recovery_automation"}
    for reservation_id, original_start, target_start, actionable in affected:
        assert actionable and target_start is not None
        assert 0 < (target_start - original_start).total_seconds() <= 240 * 60
        window = reservation_window(e2e_admin_conn, sandbox, reservation_id)
        assert window[0] == target_start and window[2] == original[reservation_id][2]
    assert open_incident_status(e2e_admin_conn, sandbox) == "resolved"


async def test_f5_autonomy_without_envelope_room_stays_operator_only(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox, handler, affected = await _open_incident(
        e2e_admin_conn, e2e_session_factory, "f5-autonomy-tight-envelope"
    )
    before = {r: reservation_window(e2e_admin_conn, sandbox, r) for r, *_ in affected}
    await grant_autonomy_policy(
        e2e_session_factory, sandbox, max_delay_minutes=1, max_auto_actions_per_incident=5
    )
    revision = current_source_revision(e2e_admin_conn, sandbox)
    replayed = await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, revision))
    assert replayed.incident is not None
    assert autonomous_action_rows(e2e_admin_conn, sandbox) == []
    assert autonomous_rescheduled_tasks(e2e_admin_conn, sandbox) == []
    for reservation_id, *_ in affected:
        assert reservation_window(e2e_admin_conn, sandbox, reservation_id) == before[reservation_id]
    assert open_incident_status(e2e_admin_conn, sandbox) == "open"


async def test_f5_autonomy_honors_per_incident_budget(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    sandbox, handler, affected = await _open_incident(
        e2e_admin_conn, e2e_session_factory, "f5-autonomy-budget"
    )
    assert len(affected) >= 2
    await grant_autonomy_policy(
        e2e_session_factory, sandbox, max_delay_minutes=240, max_auto_actions_per_incident=2
    )
    for _ in range(len(affected) + 2):
        revision = current_source_revision(e2e_admin_conn, sandbox)
        await handler.handle(lease_reassessment(e2e_admin_conn, sandbox, revision))
        if len(autonomous_action_rows(e2e_admin_conn, sandbox)) >= 2:
            break
    actions = autonomous_action_rows(e2e_admin_conn, sandbox)
    assert len(actions) == 2
    assert all(row[1] == "succeeded" for row in actions)
    assert open_incident_status(e2e_admin_conn, sandbox) == "open"
