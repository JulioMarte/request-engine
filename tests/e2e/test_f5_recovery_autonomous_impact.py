from __future__ import annotations

from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_escalation_support import (
    automatic_recovery_facts,
    autonomous_impact_task,
    escalation_world,
)
from .f5_recovery_support import f5_actor
from .f5_scheduled_assessment_support import current_source_revision, lease_reassessment
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]


def _communicate_impact_body(sandbox: TenantSandbox, revision: int) -> dict[str, object]:
    return {
        "expected_source_revision": revision,
        "recipient_party_id": str(sandbox.party_id),
        "reason": "material scope breach",
    }


async def test_f5_autonomous_impact_converges_with_explicit_operator_action(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox, _, handler = await escalation_world(
        e2e_admin_conn, e2e_session_factory, "f5-impact-automation"
    )
    revision = current_source_revision(e2e_admin_conn, sandbox)
    lease = lease_reassessment(e2e_admin_conn, sandbox, revision)
    result = await handler.handle(lease)
    assert result.applied is True and result.incident is not None
    task = autonomous_impact_task(e2e_admin_conn, sandbox, result.incident.id, revision)
    assert task is not None
    task_id, task_attribution = task[0], task[1:]
    assert task_attribution == (
        "operational_recovery_impact",
        "operational_recovery.impact",
        "service",
        "operational_recovery_automation",
    )
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (0, 1, 1)

    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        response = await client.post(
            f"/v1/operational-recovery/incidents/{result.incident.id}/communicate-impact",
            json=_communicate_impact_body(sandbox, revision),
            headers=auth(sandbox, idempotency_key=f"f5-impact-explicit-{uuid4().hex}"),
        )
    assert response.status_code == 200, response.text
    assert response.json()["action_kind"] == "communicate_impact"
    assert response.json()["status"] == "succeeded"
    assert response.json()["owner_steps"]["communications"]["communication_task_id"] == str(task_id)
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (1, 1, 1)

    replay = await handler.handle(lease)
    assert replay.applied is False
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == (1, 1, 1)
