from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest

from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    SetRecoveryIntakeCommand,
)
from request_engine.platform.db.session import SessionFactory

from .f3_acceptance_assertions import seed_walk_in_subject
from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f5_replace_resource_support import seed_incident_for_proposal
from .f6_copilot_support import copilot_actor, intake_body, interpret
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


async def test_f6_language_never_bypasses_owner_gates(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-gates")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        source_revision = int(proposal["source_checkpoint"]["recovery_source_revision"])

        stop_text = (
            f"stop walk-ins for incident {incident_id} "
            f"source revision {source_revision} intake revision 1"
        )
        key = f"f6-stop-intake-{uuid4().hex}"
        decision = await interpret(client, sandbox, stop_text, key)
        assert decision["action"] == "set_recovery_intake"
        operation = cast(dict[str, Any], decision["operation"])
        assert operation["accepting"] is False
        assert operation["organization_id"] == str(sandbox.organization_id)
        assert operation["principal_id"] == str(sandbox.principal_id)
        assert operation["idempotency_key"] == key
        assert await interpret(client, sandbox, stop_text, key) == decision
        renamed = await interpret(client, sandbox, stop_text, f"f6-other-key-{uuid4().hex}")
        assert renamed["operation"]["idempotency_key"] != operation["idempotency_key"]
        command = SetRecoveryIntakeCommand(
            organization_id=sandbox.organization_id,
            principal_id=sandbox.principal_id,
            incident_id=incident_id,
            expected_source_revision=int(operation["expected_source_revision"]),
            expected_intake_revision=int(operation["expected_intake_revision"]),
            accepting=False,
            idempotency_key=key,
        )
        stopped = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
            json=intake_body(command),
            headers=auth(sandbox, idempotency_key=key),
        )
        replay = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
            json=intake_body(command),
            headers=auth(sandbox, idempotency_key=key),
        )
        assert stopped.status_code == replay.status_code == 200, stopped.text
        assert stopped.json()["action_kind"] == "stop_intake"
        assert replay.json()["id"] == stopped.json()["id"]

        subject = seed_walk_in_subject(e2e_admin_conn, sandbox)
        blocked = await client.post(
            f"/v1/queues/{sandbox.queue_id}/check-in",
            json={"subject_party_id": str(subject)},
            headers=auth(sandbox, idempotency_key=f"f6-walk-in-{uuid4().hex}"),
        )
        assert blocked.status_code == 409, blocked.text
        stale_text = (
            f"stop walk-ins for incident {incident_id} source revision 99 intake revision 99"
        )
        stale = await interpret(client, sandbox, stale_text, f"f6-stale-{uuid4().hex}")
        rejected = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/intake-control",
            json={
                "expected_source_revision": int(stale["operation"]["expected_source_revision"]),
                "expected_intake_revision": int(stale["operation"]["expected_intake_revision"]),
                "accepting": False,
            },
            headers=auth(sandbox, idempotency_key=f"f6-stale-post-{uuid4().hex}"),
        )
        assert rejected.status_code == 409, rejected.text

        risk = await interpret(
            client,
            sandbox,
            f"show reservations at risk for queue {sandbox.queue_id}",
            f"f6-risk-{uuid4().hex}",
        )
        assert risk["action"] == "show_at_risk_reservations"
        assert risk["service_queue_id"] == str(sandbox.queue_id)
        assert len(risk["at_risk_reservations"]) >= 1
