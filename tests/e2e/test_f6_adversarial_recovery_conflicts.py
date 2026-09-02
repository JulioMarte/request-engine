import pytest

from request_engine.platform.db.session import SessionFactory

from .f4_capacity_support import seed_today_schedule
from .f4_operational_day_support import configure_projection
from .f5_booking_fixture import five_minute_sandbox
from .f5_recovery_support import book_commitments, restrict_source_to_first_six
from .f6_adversarial_concurrency_support import (
    concurrent_conflicting_posts,
    successful_response,
)
from .f6_copilot_support import copilot_actor, read_tool
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


async def test_f6_recovery_proposal_and_execution_conflicting_races_have_one_winner(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = five_minute_sandbox(
        e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, "f6-race-recovery")
    )
    seed_today_schedule(e2e_admin_conn, sandbox)
    actors = {sandbox.token: copilot_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        await configure_projection(client, sandbox)
        _, slots = await book_commitments(client, e2e_admin_conn, sandbox)
        restrict_source_to_first_six(e2e_admin_conn, sandbox, slots)
        first, second = await concurrent_conflicting_posts(
            client,
            sandbox,
            "/recovery/proposals",
            {"service_queue_id": str(sandbox.queue_id), "search_days": 7},
            {"service_queue_id": str(sandbox.queue_id), "search_days": 14},
        )
        proposal_id = successful_response(first, second).json()["result_id"]
        at_risk = await read_tool(
            client, sandbox, f"/queues/{sandbox.queue_id}/at-risk-reservations"
        )
        reservation_id = at_risk["affected"][0]["reservation_id"]
        await concurrent_conflicting_posts(
            client,
            sandbox,
            "/recovery/executions",
            {
                "proposal_id": proposal_id,
                "reservation_id": reservation_id,
                "notify": True,
            },
            {
                "proposal_id": proposal_id,
                "reservation_id": reservation_id,
                "notify": False,
            },
        )
    row = e2e_admin_conn.execute(
        "SELECT "
        "(SELECT count(*) FROM request_engine.operational_recovery_proposals "
        " WHERE organization_id=%s AND service_queue_id=%s), "
        "(SELECT count(*) FROM request_engine.operational_recovery_executions "
        " WHERE organization_id=%s)",
        (sandbox.organization_id, sandbox.queue_id, sandbox.organization_id),
    ).fetchone()
    assert row == (1, 1)
