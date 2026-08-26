import asyncio
from uuid import uuid4

import pytest
from f3_live_ops_fixture import create_live_ops_fixture
from f3_live_ops_seed import PgConnection
from f4_customer_projection_fixture import create_principal

from request_engine.modules.live_capacity.adapters.db.create_workload_policy import (
    create_workload_estimate_policy,
)
from request_engine.modules.live_capacity.adapters.db.update_workload_policy import (
    update_workload_estimate_policy,
)
from request_engine.modules.live_capacity.application.commands.policy import (
    CreateWorkloadEstimatePolicyCommand,
    UpdateWorkloadEstimatePolicyCommand,
)
from request_engine.modules.live_capacity.application.errors import PolicyRevisionConflict
from request_engine.modules.live_capacity.contracts.policy import WorkloadEstimatePolicy
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.concurrency
@pytest.mark.provenance
async def test_workload_estimate_revision_race_has_one_winner_and_one_conflict(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup.organization_id)
    policy = await create_workload_estimate_policy(
        command_session_factory,
        CreateWorkloadEstimatePolicyCommand(
            organization_id=setup.organization_id,
            principal_id=principal_id,
            workload_classification_id=setup.expected_workload_id,
            duration_seconds=1200,
            idempotency_key=f"f4-estimate-race-create-{uuid4().hex}",
        ),
    )

    async def update(duration_seconds: int) -> WorkloadEstimatePolicy | Exception:
        try:
            return await update_workload_estimate_policy(
                command_session_factory,
                UpdateWorkloadEstimatePolicyCommand(
                    organization_id=setup.organization_id,
                    principal_id=principal_id,
                    policy_id=policy.id,
                    duration_seconds=duration_seconds,
                    active=True,
                    expected_revision=policy.revision,
                    idempotency_key=f"f4-estimate-race-{duration_seconds}-{uuid4().hex}",
                ),
            )
        except Exception as exc:
            return exc

    results = await asyncio.gather(update(1500), update(1800))
    winners = [result for result in results if isinstance(result, WorkloadEstimatePolicy)]
    losers = [result for result in results if isinstance(result, PolicyRevisionConflict)]
    assert len(winners) == 1
    assert len(losers) == 1
    winner = winners[0]
    assert winner.revision == policy.revision + 1

    row = admin_conn.execute(
        "SELECT duration_seconds,active,revision "
        "FROM request_engine.live_capacity_workload_estimate_policies "
        "WHERE organization_id=%s AND id=%s",
        (setup.organization_id, policy.id),
    ).fetchone()
    assert row == (winner.duration_seconds, True, winner.revision)
