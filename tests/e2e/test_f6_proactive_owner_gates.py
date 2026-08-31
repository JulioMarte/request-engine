from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .f5_extend_day_fixture import grant_extend_day_authority
from .f6_copilot_support import copilot_actor
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.postgres, pytest.mark.adversarial]


def _without(actor: ActorContext, capability: str) -> ActorContext:
    return ActorContext(
        actor.organization_id,
        actor.principal_id,
        actor.capabilities - {capability},
    )


async def test_f6_proactive_intake_requires_queue_owner_capability(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-proactive-intake-owner-gate")
    actor = _without(copilot_actor(sandbox), "queue.manage_intake")
    actors = {sandbox.token: actor}

    async with client_with_actors(e2e_session_factory, actors) as client:
        response = await client.post(
            "/v1/operational-copilot/tools/queues/intake-control",
            json={
                "service_queue_id": str(sandbox.queue_id),
                "accepting": False,
                "expected_intake_revision": 1,
                "reason": "gate proof",
            },
            headers=auth(sandbox, idempotency_key=f"gate-{uuid4().hex}"),
        )

    assert response.status_code == 403, response.text
    row = e2e_admin_conn.execute(
        "SELECT accepting, revision FROM request_engine.service_queue_intake_controls "
        "WHERE organization_id=%s AND service_queue_id=%s",
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchone()
    assert row is None


async def test_f6_proactive_extend_requires_booking_owner_capability(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f6-proactive-extend-owner-gate")
    grant_extend_day_authority(e2e_admin_conn, sandbox)
    actor = _without(copilot_actor(sandbox), "booking.manage_supply")
    actors = {sandbox.token: actor}
    start = datetime.now(UTC) + timedelta(hours=1)

    async with client_with_actors(e2e_session_factory, actors) as client:
        response = await client.post(
            "/v1/operational-copilot/tools/assignments/day-extensions",
            json={
                "assignment_id": str(uuid4()),
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(hours=1)).isoformat(),
                "expected_resource_availability_revision": 1,
                "reason": "gate proof",
            },
            headers=auth(sandbox, idempotency_key=f"gate-{uuid4().hex}"),
        )

    assert response.status_code == 403, response.text
