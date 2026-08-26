from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.delivery.contracts.service_session import (
    ResourceActivity,
    ResourceActivityKind,
    ServiceSession,
    ServiceSessionStatus,
)


def session_from_row(row: RowMapping) -> ServiceSession:
    return ServiceSession(
        id=cast(UUID, row["id"]),
        queue_entry_id=cast(UUID, row["queue_entry_id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        status=ServiceSessionStatus(cast(str, row["status"])),
        started_at=cast(datetime, row["started_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
        actual_workload_classification_id=cast(
            UUID | None, row["actual_workload_classification_id"]
        ),
        revision=cast(int, row["revision"]),
    )


def session_to_json(item: ServiceSession) -> dict[str, object]:
    return {
        "id": str(item.id),
        "queue_entry_id": str(item.queue_entry_id),
        "resource_id": str(item.resource_id),
        "location_id": str(item.location_id),
        "status": item.status.value,
        "started_at": item.started_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "actual_workload_classification_id": (
            str(item.actual_workload_classification_id)
            if item.actual_workload_classification_id
            else None
        ),
        "revision": item.revision,
    }


def session_from_json(data: dict[str, object]) -> ServiceSession:
    actual = data["actual_workload_classification_id"]
    completed = data["completed_at"]
    return ServiceSession(
        id=UUID(cast(str, data["id"])),
        queue_entry_id=UUID(cast(str, data["queue_entry_id"])),
        resource_id=UUID(cast(str, data["resource_id"])),
        location_id=UUID(cast(str, data["location_id"])),
        status=ServiceSessionStatus(cast(str, data["status"])),
        started_at=datetime.fromisoformat(cast(str, data["started_at"])),
        completed_at=datetime.fromisoformat(cast(str, completed)) if completed else None,
        actual_workload_classification_id=UUID(cast(str, actual)) if actual else None,
        revision=cast(int, data["revision"]),
    )


def activity_from_row(row: RowMapping) -> ResourceActivity:
    return ResourceActivity(
        id=cast(UUID, row["id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        kind=ResourceActivityKind(cast(str, row["activity_kind"])),
        started_at=cast(datetime, row["started_at"]),
        ended_at=cast(datetime | None, row["ended_at"]),
        revision=cast(int, row["revision"]),
    )


def activity_to_json(item: ResourceActivity) -> dict[str, object]:
    return {
        "id": str(item.id),
        "resource_id": str(item.resource_id),
        "location_id": str(item.location_id) if item.location_id else None,
        "kind": item.kind.value,
        "started_at": item.started_at.isoformat(),
        "ended_at": item.ended_at.isoformat() if item.ended_at else None,
        "revision": item.revision,
    }


def activity_from_json(data: dict[str, object]) -> ResourceActivity:
    location = data["location_id"]
    ended = data["ended_at"]
    return ResourceActivity(
        id=UUID(cast(str, data["id"])),
        resource_id=UUID(cast(str, data["resource_id"])),
        location_id=UUID(cast(str, location)) if location else None,
        kind=ResourceActivityKind(cast(str, data["kind"])),
        started_at=datetime.fromisoformat(cast(str, data["started_at"])),
        ended_at=datetime.fromisoformat(cast(str, ended)) if ended else None,
        revision=cast(int, data["revision"]),
    )
