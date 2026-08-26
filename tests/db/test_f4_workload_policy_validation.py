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
from request_engine.modules.live_capacity.application.errors import (
    InvalidWorkloadEstimateConfiguration,
)
from request_engine.platform.db.session import SessionFactory


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.invariant
@pytest.mark.adversarial
@pytest.mark.security
@pytest.mark.provenance
async def test_workload_estimate_configuration_validates_authoritative_classification(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    local = create_live_ops_fixture(admin_conn)
    foreign = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, local.organization_id)

    with pytest.raises(InvalidWorkloadEstimateConfiguration):
        await create_workload_estimate_policy(
            command_session_factory,
            CreateWorkloadEstimatePolicyCommand(
                organization_id=local.organization_id,
                principal_id=principal_id,
                workload_classification_id=foreign.expected_workload_id,
                duration_seconds=1200,
                idempotency_key=f"f4-foreign-estimate-{uuid4().hex}",
            ),
        )
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.live_capacity_workload_estimate_policies "
        "WHERE organization_id=%s",
        (local.organization_id,),
    ).fetchone() == (0,)

    policy = await create_workload_estimate_policy(
        command_session_factory,
        CreateWorkloadEstimatePolicyCommand(
            organization_id=local.organization_id,
            principal_id=principal_id,
            workload_classification_id=local.expected_workload_id,
            duration_seconds=1200,
            idempotency_key=f"f4-valid-estimate-{uuid4().hex}",
        ),
    )
    admin_conn.execute(
        "UPDATE request_engine.operational_workload_classifications "
        "SET active=false,revision=revision+1 WHERE id=%s",
        (local.expected_workload_id,),
    )
    with pytest.raises(InvalidWorkloadEstimateConfiguration):
        await update_workload_estimate_policy(
            command_session_factory,
            UpdateWorkloadEstimatePolicyCommand(
                organization_id=local.organization_id,
                principal_id=principal_id,
                policy_id=policy.id,
                duration_seconds=1500,
                active=True,
                expected_revision=policy.revision,
                idempotency_key=f"f4-invalid-reactivate-{uuid4().hex}",
            ),
        )

    disabled = await update_workload_estimate_policy(
        command_session_factory,
        UpdateWorkloadEstimatePolicyCommand(
            organization_id=local.organization_id,
            principal_id=principal_id,
            policy_id=policy.id,
            duration_seconds=policy.duration_seconds,
            active=False,
            expected_revision=policy.revision,
            idempotency_key=f"f4-disable-estimate-{uuid4().hex}",
        ),
    )
    assert disabled.active is False
    assert disabled.revision == policy.revision + 1
