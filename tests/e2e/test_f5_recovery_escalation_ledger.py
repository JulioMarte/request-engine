from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import uuid4

import pytest

from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_escalation_support import automatic_recovery_facts, escalation_rows
from .f5_extend_day_fixture import close_location_after_slots, grant_extend_day_authority
from .f5_extend_day_support import owner_revisions, source_revision
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, f5_actor
from .f5_replace_resource_support import seed_incident_for_proposal
from .f5_scheduled_assessment_support import current_source_revision, lease_reassessment
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.provenance,
]


async def test_f5_extend_day_resolution_closes_escalation_ledger_from_fresh_reassessment(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-escalation-ledger-closure")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    handler = build_recovery_assessment_handler(e2e_session_factory)

    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        close_location_after_slots(e2e_admin_conn, sandbox, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        expected_revision = source_revision(proposal)
        location_revision, resource_revision = owner_revisions(e2e_admin_conn, sandbox)
        start_at = datetime.fromisoformat(cast(str, slots[6]["start_at"]))
        end_at = datetime.fromisoformat(cast(str, slots[9]["end_at"]))
        response = await client.post(
            f"/v1/operational-recovery/incidents/{incident_id}/extend-day",
            json={
                "expected_source_revision": expected_revision,
                "authority_party_id": str(sandbox.party_id),
                "assignment_id": str(supply.assignment_id),
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "expected_location_operational_revision": location_revision,
                "expected_resource_availability_revision": resource_revision,
                "reason": "recover commitments beyond closing time",
            },
            headers=auth(sandbox, idempotency_key=f"f5-extend-day-{uuid4().hex}"),
        )

    assert response.status_code == 200, response.text
    action = response.json()
    assert action["status"] == "succeeded"
    facts = automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id)

    assert escalation_rows(e2e_admin_conn, sandbox) == []
    resolved_revision = current_source_revision(e2e_admin_conn, sandbox)
    assert resolved_revision > expected_revision
    pending = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.scheduled_actions "
        "WHERE organization_id=%s AND dedupe_key=%s AND status='pending'",
        (
            sandbox.organization_id,
            f"f5-reassessment:{sandbox.queue_id}:{resolved_revision}",
        ),
    ).fetchone()
    assert pending is not None and pending[0] == 1

    lease = lease_reassessment(e2e_admin_conn, sandbox, resolved_revision)
    result = await handler.handle(lease)
    assert result.applied is True and result.incident is None
    outcome = result.escalation
    assert outcome is not None
    assert outcome.operator_escalation_required is False
    assert outcome.escalation_reason is None
    assert outcome.customer_impact_required is False
    assert escalation_rows(e2e_admin_conn, sandbox) == [
        (resolved_revision, 0, False, None, False, [])
    ]
    assert automatic_recovery_facts(e2e_admin_conn, sandbox.organization_id) == facts

    replay = await handler.handle(lease)
    assert replay.applied is False and replay.escalation is None
    assert escalation_rows(e2e_admin_conn, sandbox) == [
        (resolved_revision, 0, False, None, False, [])
    ]
