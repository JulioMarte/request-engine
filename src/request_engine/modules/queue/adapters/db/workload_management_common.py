from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.contracts.live_queue import WorkloadClassification
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.outbox.postgres import append_outbox


def workload_from_row(row: RowMapping) -> WorkloadClassification:
    return WorkloadClassification(
        id=cast(UUID, row["id"]),
        workload_key=cast(str, row["workload_key"]),
        display_name=cast(str, row["display_name"]),
        active=cast(bool, row["active"]),
        revision=cast(int, row["revision"]),
    )


def workload_to_json(item: WorkloadClassification) -> dict[str, object]:
    return {
        "id": str(item.id),
        "workload_key": item.workload_key,
        "display_name": item.display_name,
        "active": item.active,
        "revision": item.revision,
    }


def workload_from_json(item: dict[str, object]) -> WorkloadClassification:
    return WorkloadClassification(
        id=UUID(cast(str, item["id"])),
        workload_key=cast(str, item["workload_key"]),
        display_name=cast(str, item["display_name"]),
        active=cast(bool, item["active"]),
        revision=cast(int, item["revision"]),
    )


async def record_workload_fact(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_id: UUID,
    command_name: str,
    workload: WorkloadClassification,
    event_type: str,
) -> None:
    payload = workload_to_json(workload)
    await append_audit(
        session,
        organization_id=organization_id,
        principal_id=principal_id,
        command_name=command_name,
        aggregate_kind="OperationalWorkloadClassification",
        aggregate_id=workload.id,
        idempotency_id=idempotency_id,
        details=payload,
    )
    await append_outbox(
        session,
        organization_id=organization_id,
        event_type=event_type,
        aggregate_kind="OperationalWorkloadClassification",
        aggregate_id=workload.id,
        payload=payload,
    )
