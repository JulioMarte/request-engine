from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.contracts.policy import (
    ProjectionScopePolicy,
    WorkloadEstimatePolicy,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.outbox.postgres import append_outbox


def projection_scope_from_row(row: RowMapping) -> ProjectionScopePolicy:
    return ProjectionScopePolicy(
        id=cast(UUID, row["id"]),
        service_queue_id=cast(UUID, row["service_queue_id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        active=cast(bool, row["active"]),
        revision=cast(int, row["revision"]),
    )


def workload_policy_from_row(row: RowMapping) -> WorkloadEstimatePolicy:
    return WorkloadEstimatePolicy(
        id=cast(UUID, row["id"]),
        workload_classification_id=cast(UUID, row["workload_classification_id"]),
        duration_seconds=cast(int, row["duration_seconds"]),
        active=cast(bool, row["active"]),
        revision=cast(int, row["revision"]),
    )


def projection_scope_from_json(item: dict[str, object]) -> ProjectionScopePolicy:
    return ProjectionScopePolicy(
        id=UUID(cast(str, item["id"])),
        service_queue_id=UUID(cast(str, item["service_queue_id"])),
        resource_id=UUID(cast(str, item["resource_id"])),
        location_id=UUID(cast(str, item["location_id"])),
        active=cast(bool, item["active"]),
        revision=cast(int, item["revision"]),
    )


def workload_policy_from_json(item: dict[str, object]) -> WorkloadEstimatePolicy:
    return WorkloadEstimatePolicy(
        id=UUID(cast(str, item["id"])),
        workload_classification_id=UUID(cast(str, item["workload_classification_id"])),
        duration_seconds=cast(int, item["duration_seconds"]),
        active=cast(bool, item["active"]),
        revision=cast(int, item["revision"]),
    )


def policy_to_json(policy: ProjectionScopePolicy | WorkloadEstimatePolicy) -> dict[str, object]:
    values: dict[str, object] = {
        "id": str(policy.id),
        "active": policy.active,
        "revision": policy.revision,
    }
    if isinstance(policy, ProjectionScopePolicy):
        values.update(
            service_queue_id=str(policy.service_queue_id),
            resource_id=str(policy.resource_id),
            location_id=str(policy.location_id),
        )
    else:
        values.update(
            workload_classification_id=str(policy.workload_classification_id),
            duration_seconds=policy.duration_seconds,
        )
    return values


async def record_policy_fact(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_id: UUID,
    command_name: str,
    policy: ProjectionScopePolicy | WorkloadEstimatePolicy,
    event_type: str,
) -> None:
    payload = policy_to_json(policy)
    await append_audit(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        command_name=command_name,
        aggregate_kind=type(policy).__name__,
        aggregate_id=policy.id,
        idempotency_id=idempotency_id,
        details=payload,
    )
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type=event_type,
        aggregate_kind=type(policy).__name__,
        aggregate_id=policy.id,
        payload=payload,
    )
