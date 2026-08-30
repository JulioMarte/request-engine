from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply, restrict_contextual_capacity
from .f5_extend_day_fixture import (
    close_location_after_slots,
    grant_extend_day_authority,
    recurring_schedule_snapshot,
)
from .f5_extend_day_support import (
    assignment_recovery_exception_count,
    location_recovery_exception_count,
    owner_revisions,
    source_revision,
)
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments
from .f5_replace_resource_support import seed_incident_for_proposal
from .f6_copilot_support import copilot_actor, execute
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
]


async def test_f6_copilot_extend_day_executes_owner_extend_day(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-extend-day")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    seed_today_schedule(e2e_admin_conn, sandbox)
    supply = contextualize_recovery_supply(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_contextual_capacity(e2e_admin_conn, sandbox, supply, slots, count=6)
        close_location_after_slots(e2e_admin_conn, sandbox, slots, count=6)
        proposal = await create_proposal(client, sandbox)
        incident_id = seed_incident_for_proposal(e2e_admin_conn, sandbox, proposal)
        location_revision, resource_revision = owner_revisions(e2e_admin_conn, sandbox)
        recurring_before = recurring_schedule_snapshot(
            e2e_admin_conn, sandbox, supply.assignment_id
        )
        location_before = location_recovery_exception_count(e2e_admin_conn, sandbox)
        assignment_before = assignment_recovery_exception_count(
            e2e_admin_conn, sandbox, supply.assignment_id
        )
        start_at = datetime.fromisoformat(cast(str, slots[6]["start_at"]))
        end_at = datetime.fromisoformat(cast(str, slots[9]["end_at"]))
        text = (
            f"extend day for incident {incident_id} assignment {supply.assignment_id} "
            f"from {start_at.isoformat()} to {end_at.isoformat()} "
            f"source revision {source_revision(proposal)} "
            f"location revision {location_revision} "
            f"availability revision {resource_revision} reason recover commitments"
        )
        key = f"f6-extend-{uuid4().hex}"

        executed = await execute(client, sandbox, text, key)
        replay = await execute(client, sandbox, text, key)

    assert executed["action"] == "extend_day"
    assert executed["status"] == "succeeded"
    assert executed["idempotency_key"] == key
    assert replay["owner_action_id"] == executed["owner_action_id"]
    assert location_recovery_exception_count(e2e_admin_conn, sandbox) == location_before + 1
    assert assignment_recovery_exception_count(e2e_admin_conn, sandbox, supply.assignment_id) == (
        assignment_before + 1
    )
    assert (
        recurring_schedule_snapshot(e2e_admin_conn, sandbox, supply.assignment_id)
        == recurring_before
    )
