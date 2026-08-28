from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_extend_day_support import (
    assignment_recovery_exception_count,
    extend_action,
    location_recovery_exception_count,
    owner_revisions,
    source_revision,
)
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, f5_actor
from .f5_replace_resource_support import seed_incident_for_proposal
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
    pytest.mark.provenance,
]


async def test_f5_extend_day_stale_second_step_is_visible_and_idempotent(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f5-extend-day-partial")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        expected_source_revision = source_revision(proposal)
        location_revision, resource_revision = owner_revisions(e2e_admin_conn, sandbox)

        # Advance Booking-owned contextual availability after authorization. The
        # original revision remains a valid positive stale intent token.
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=5)
        _, stale_resource_revision = owner_revisions(e2e_admin_conn, sandbox)
        assert stale_resource_revision > resource_revision

        before_location = location_recovery_exception_count(e2e_admin_conn, sandbox)
        before_assignment = assignment_recovery_exception_count(
            e2e_admin_conn, sandbox, supply.assignment_id
        )
        start_at = datetime.fromisoformat(cast(str, slots[-1]["start_at"]))
        end_at = datetime.fromisoformat(cast(str, slots[-1]["end_at"]))
        key = f"f5-extend-day-stale-{uuid4().hex}"
        body: dict[str, object] = {
            "expected_source_revision": expected_source_revision,
            "assignment_id": str(supply.assignment_id),
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "expected_location_operational_revision": location_revision,
            "expected_resource_availability_revision": resource_revision,
            "reason": "adversarial stale resource revision",
        }
        path = f"/v1/operational-recovery/incidents/{incident_id}/extend-day"
        response = await client.post(path, json=body, headers=auth(sandbox, idempotency_key=key))
        replay = await client.post(path, json=body, headers=auth(sandbox, idempotency_key=key))

    assert response.status_code == replay.status_code == 409
    action_id, status, owner_steps = extend_action(e2e_admin_conn, sandbox, incident_id)
    assert isinstance(action_id, UUID)
    assert status == "partially_applied"
    assert cast(dict[str, object], owner_steps)["catalog_location"]
    assert location_recovery_exception_count(e2e_admin_conn, sandbox) == before_location + 1
    assert (
        assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id)
        == before_assignment
    )
    assert owner_revisions(e2e_admin_conn, sandbox) == (
        location_revision + 1,
        stale_resource_revision,
    )
