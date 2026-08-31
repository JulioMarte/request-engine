from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f6_copilot_support import copilot_actor, interpret
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.invariant,
]


async def test_f6_resolves_current_queue_for_natural_at_risk_inspection(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    base = seed_tenant_sandbox(e2e_admin_conn, "f6-copilot-natural-at-risk")
    sandbox = five_minute_sandbox(e2e_admin_conn, base)
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}

    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        reservations, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)

        result = await interpret(
            client,
            sandbox,
            "show me which Reservations are at risk",
            f"f6-natural-at-risk-{uuid4().hex}",
        )

    assert result["action"] == "show_at_risk_reservations"
    assert result["service_queue_id"] == str(sandbox.queue_id)
    assert result["projection_state"] == "known"
    assert result["shortfall_seconds"] > 0
    affected = result["at_risk_reservations"]
    assert affected
    reservation_ids = {item["reservation_id"] for item in affected}
    committed_ids = {str(reservation_id) for reservation_id in reservations}
    assert reservation_ids <= committed_ids
