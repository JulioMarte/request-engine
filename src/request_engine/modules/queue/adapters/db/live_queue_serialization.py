from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry


def entry_from_row(row: RowMapping) -> LiveQueueEntry:
    return LiveQueueEntry(
        id=cast(UUID, row["id"]),
        queue_id=cast(UUID, row["service_queue_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        reservation_id=cast(UUID | None, row["reservation_id"]),
        offering_id=cast(UUID | None, row["offering_id"]),
        status=cast(str, row["status"]),
        arrived_at=cast(datetime, row["arrived_at"]),
        admitted_at=cast(datetime, row["admitted_at"]),
        called_at=cast(datetime | None, row["called_at"]),
        expected_workload_classification_id=cast(
            UUID | None, row["expected_workload_classification_id"]
        ),
        revision=cast(int, row["revision"]),
    )


def entry_to_json(item: LiveQueueEntry) -> dict[str, object]:
    return {
        "id": str(item.id),
        "queue_id": str(item.queue_id),
        "subject_party_id": str(item.subject_party_id),
        "reservation_id": str(item.reservation_id) if item.reservation_id else None,
        "offering_id": str(item.offering_id) if item.offering_id else None,
        "status": item.status,
        "arrived_at": item.arrived_at.isoformat(),
        "admitted_at": item.admitted_at.isoformat(),
        "called_at": item.called_at.isoformat() if item.called_at else None,
        "expected_workload_classification_id": (
            str(item.expected_workload_classification_id)
            if item.expected_workload_classification_id
            else None
        ),
        "revision": item.revision,
    }


def entry_from_json(data: dict[str, object]) -> LiveQueueEntry:
    reservation = data["reservation_id"]
    offering = data["offering_id"]
    called = data["called_at"]
    workload = data["expected_workload_classification_id"]
    return LiveQueueEntry(
        id=UUID(cast(str, data["id"])),
        queue_id=UUID(cast(str, data["queue_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        reservation_id=UUID(cast(str, reservation)) if reservation else None,
        offering_id=UUID(cast(str, offering)) if offering else None,
        status=cast(str, data["status"]),
        arrived_at=datetime.fromisoformat(cast(str, data["arrived_at"])),
        admitted_at=datetime.fromisoformat(cast(str, data["admitted_at"])),
        called_at=datetime.fromisoformat(cast(str, called)) if called else None,
        expected_workload_classification_id=UUID(cast(str, workload)) if workload else None,
        revision=cast(int, data["revision"]),
    )
