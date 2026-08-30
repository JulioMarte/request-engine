from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_assertions import create_proposal
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f6_copilot_support import copilot_actor, interpret
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
]


async def test_f6_copilot_resolves_execute_fingerprints_through_owner_read(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-fingerprints")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        proposal = await create_proposal(client, sandbox)
        reservation_id = proposal["affected"][0]["reservation_id"]
        text = f"execute recovery proposal {proposal['id']} for reservation {reservation_id}"
        decision = await interpret(client, sandbox, text, f"f6-resolve-{uuid4().hex}")
        assert decision["action"] == "execute_recovery"
        operation = cast(dict[str, Any], decision["operation"])
        assert operation["expected_source_fingerprint"] == proposal["source_fingerprint"]
        assert operation["expected_proposal_fingerprint"] == proposal["proposal_fingerprint"]
        execution = await client.post(
            f"/v1/operational-recovery/proposals/{proposal['id']}/execute",
            json={
                "reservation_id": str(reservation_id),
                "expected_source_fingerprint": operation["expected_source_fingerprint"],
                "expected_proposal_fingerprint": operation["expected_proposal_fingerprint"],
                "notify": True,
            },
            headers=auth(sandbox, idempotency_key=f"f6-execute-{uuid4().hex}"),
        )
        assert execution.status_code == 200, execution.text
        assert execution.json()["status"] == "succeeded"
