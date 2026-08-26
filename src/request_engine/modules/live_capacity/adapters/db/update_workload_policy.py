from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.live_capacity.adapters.db.policy_common import (
    policy_to_json,
    record_policy_fact,
    workload_policy_from_json,
    workload_policy_from_row,
)
from request_engine.modules.live_capacity.adapters.db.workload_policy_validation import (
    validate_workload_estimate_target,
)
from request_engine.modules.live_capacity.application.commands.policy import (
    UpdateWorkloadEstimatePolicyCommand,
)
from request_engine.modules.live_capacity.application.errors import (
    PolicyRevisionConflict,
    WorkloadEstimatePolicyNotFound,
)
from request_engine.modules.live_capacity.contracts.policy import WorkloadEstimatePolicy
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def update_workload_estimate_policy(
    session_factory: SessionFactory, command: UpdateWorkloadEstimatePolicyCommand
) -> WorkloadEstimatePolicy:
    payload = {
        "policy_id": str(command.policy_id),
        "duration_seconds": command.duration_seconds,
        "active": command.active,
        "expected_revision": command.expected_revision,
    }
    fingerprint = command_fingerprint("live_capacity.configure_estimate", payload)
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="live_capacity.configure_estimate",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return workload_policy_from_json(cast(dict[str, object], replay["policy"]))
        if command.active:
            workload_classification_id = await session.scalar(
                text(
                    "SELECT workload_classification_id "
                    "FROM request_engine.live_capacity_workload_estimate_policies "
                    "WHERE organization_id=:organization_id AND id=:policy_id"
                ),
                {"organization_id": command.organization_id, "policy_id": command.policy_id},
            )
            if workload_classification_id is not None:
                await validate_workload_estimate_target(
                    session,
                    organization_id=command.organization_id,
                    workload_classification_id=cast(UUID, workload_classification_id),
                )
        row = (
            (
                await session.execute(
                    text(
                        "UPDATE request_engine.live_capacity_workload_estimate_policies "
                        "SET duration_seconds=:duration_seconds,active=:active,revision=revision+1 "
                        "WHERE organization_id=:organization_id AND id=:policy_id "
                        "AND revision=:expected_revision "
                        "RETURNING id,workload_classification_id,duration_seconds,active,revision"
                    ),
                    {"organization_id": command.organization_id, **payload},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            exists = await session.scalar(
                text(
                    "SELECT 1 FROM request_engine.live_capacity_workload_estimate_policies "
                    "WHERE organization_id=:organization_id AND id=:policy_id"
                ),
                {"organization_id": command.organization_id, "policy_id": command.policy_id},
            )
            if exists is None:
                raise WorkloadEstimatePolicyNotFound(command.policy_id)
            raise PolicyRevisionConflict(command.expected_revision)
        policy = workload_policy_from_row(row)
        await record_policy_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="live_capacity.configure_estimate",
            policy=policy,
            event_type="live_capacity.workload_estimate_updated.v1",
        )
        await complete_idempotency(session, idem, {"policy": policy_to_json(policy)})
        return policy
