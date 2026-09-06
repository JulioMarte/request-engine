from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .f6_copilot_support import copilot_actor
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.concurrency,
    pytest.mark.adversarial,
]


def _second_principal(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"bot-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _intake_state(conn: PgConnection, organization_id: UUID, queue_id: UUID) -> tuple[bool, int]:
    row = conn.execute(
        """
        SELECT accepting, revision
        FROM request_engine.service_queue_intake_controls
        WHERE organization_id = %s AND service_queue_id = %s
        """,
        (organization_id, queue_id),
    ).fetchone()
    assert row is not None
    return bool(row[0]), int(row[1])


async def test_admin_and_bot_compete_through_one_owner_without_last_write_wins(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    """Two principals must serialize on Queue truth even with distinct idempotency keys."""
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "cross-principal-intake-race")
    initial_accepting, initial_revision = _intake_state(
        e2e_admin_conn, sandbox.organization_id, sandbox.queue_id
    )
    assert initial_accepting is True

    operator = copilot_actor(sandbox)
    bot_principal_id = _second_principal(e2e_admin_conn, sandbox.organization_id)
    bot = ActorContext(
        organization_id=sandbox.organization_id,
        principal_id=bot_principal_id,
        capabilities=operator.capabilities,
    )
    operator_token = f"operator-{uuid4().hex}"
    bot_token = f"bot-{uuid4().hex}"
    actors = {operator_token: operator, bot_token: bot}
    body = {
        "service_queue_id": str(sandbox.queue_id),
        "accepting": False,
        "expected_intake_revision": initial_revision,
        "reason": "adversarial cross-principal stop",
    }
    path = "/v1/operational-copilot/tools/queues/intake-control"

    async with client_with_actors(e2e_session_factory, actors) as client:
        operator_response, bot_response = await asyncio.gather(
            client.post(
                path,
                json=body,
                headers={
                    "Authorization": f"Bearer {operator_token}",
                    "Idempotency-Key": f"operator-{uuid4().hex}",
                },
            ),
            client.post(
                path,
                json=body,
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Idempotency-Key": f"bot-{uuid4().hex}",
                },
            ),
        )

    assert sorted((operator_response.status_code, bot_response.status_code)) == [200, 409], (
        operator_response.text,
        bot_response.text,
    )
    assert _intake_state(e2e_admin_conn, sandbox.organization_id, sandbox.queue_id) == (
        False,
        initial_revision + 1,
    )

    rows = e2e_admin_conn.execute(
        """
        SELECT actor_principal_id
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND command_name = 'queue.set_intake_control'
          AND aggregate_id = %s
        """,
        (sandbox.organization_id, sandbox.queue_id),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] in {operator.principal_id, bot_principal_id}
