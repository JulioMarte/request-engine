import asyncio
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_recovery_assertions import (
    communication_lineage,
    create_proposal,
    execute_proposal,
    execution_row,
    outbox_for_task,
    reservation_state,
)
from .f5_recovery_support import f5_actor
from .f5_recovery_world import prepare_recovery_world
from .operational_support import PgConnection
from .tenant_sandbox import client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.contract,
    pytest.mark.adversarial,
    pytest.mark.concurrency,
    pytest.mark.capacity,
    pytest.mark.provenance,
]


async def test_f5_identical_concurrent_execution_converges_on_one_booking_and_communication(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "f5-race")
    actors = {sandbox.token: f5_actor(sandbox)}
    async with client_with_actors(e2e_session_factory, actors) as setup_client:
        await prepare_recovery_world(setup_client, e2e_admin_conn, sandbox)
        proposal = await create_proposal(setup_client, sandbox)
    affected = proposal["affected"][0]
    reservation_id = UUID(affected["reservation_id"])
    before = reservation_state(e2e_admin_conn, reservation_id)
    before_revision = cast(int, before[0])
    target_start = datetime.fromisoformat(cast(str, affected["target"]["start_at"]))
    idempotency_key = f"f5-race-execute-{uuid4().hex}"

    async with (
        client_with_actors(e2e_session_factory, actors) as first_client,
        client_with_actors(e2e_session_factory, actors) as second_client,
    ):
        first, second = await asyncio.gather(
            execute_proposal(
                first_client,
                sandbox,
                proposal,
                reservation_id,
                idempotency_key=idempotency_key,
            ),
            execute_proposal(
                second_client,
                sandbox,
                proposal,
                reservation_id,
                idempotency_key=idempotency_key,
            ),
        )
        replay = await execute_proposal(
            first_client,
            sandbox,
            proposal,
            reservation_id,
            idempotency_key=idempotency_key,
        )

    assert [first.status_code, second.status_code, replay.status_code] == [200, 200, 200]
    bodies = [response.json() for response in (first, second, replay)]
    assert len({body["id"] for body in bodies}) == 1
    assert all(body["status"] == "succeeded" for body in bodies)
    after = reservation_state(e2e_admin_conn, reservation_id)
    after_revision = cast(int, after[0])
    assert after_revision == before_revision + 1
    assert after[1] == "confirmed"
    assert cast(datetime, after[2]) == target_start

    row = execution_row(
        e2e_admin_conn,
        sandbox.organization_id,
        UUID(proposal["id"]),
        reservation_id,
    )
    execution_id = UUID(str(row[0]))
    assert row[1] == "succeeded"
    assert row[2] == sandbox.principal_id
    assert row[3] == before_revision and row[4] == after_revision
    task_id = UUID(str(row[5]))
    lineage = communication_lineage(e2e_admin_conn, sandbox.organization_id, execution_id)
    assert lineage == [
        (
            task_id,
            f"operational-recovery:{execution_id}:rescheduled:v1",
            "OperationalRecoveryExecution",
            execution_id,
        )
    ]
    outbox = outbox_for_task(e2e_admin_conn, sandbox.organization_id, task_id)
    assert len(outbox) == 1
    assert outbox[0][1:] == ("communication.task_created.v1", "CommunicationTask", task_id)
