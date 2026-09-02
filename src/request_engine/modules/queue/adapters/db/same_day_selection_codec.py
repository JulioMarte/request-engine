from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.queue.contracts.same_day_selection import SkipResult
from request_engine.modules.queue.contracts.service_queue import QueueEntry, QueueEntryStatus


def queue_entry_from_row(row: RowMapping) -> QueueEntry:
    return QueueEntry(
        id=cast(UUID, row["id"]),
        queue_id=cast(UUID, row["service_queue_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        status=QueueEntryStatus(cast(str, row["status"])),
        admitted_at=cast(datetime, row["admitted_at"]),
        called_at=cast(datetime | None, row["called_at"]),
        revision=cast(int, row["revision"]),
    )


def queue_entry_to_json(item: QueueEntry) -> dict[str, object]:
    return {
        "id": str(item.id),
        "queue_id": str(item.queue_id),
        "subject_party_id": str(item.subject_party_id),
        "status": item.status.value,
        "admitted_at": item.admitted_at.isoformat(),
        "called_at": item.called_at.isoformat() if item.called_at else None,
        "revision": item.revision,
    }


def queue_entry_from_json(data: dict[str, object]) -> QueueEntry:
    called_at = cast(str | None, data["called_at"])
    return QueueEntry(
        id=UUID(cast(str, data["id"])),
        queue_id=UUID(cast(str, data["queue_id"])),
        subject_party_id=UUID(cast(str, data["subject_party_id"])),
        status=QueueEntryStatus(cast(str, data["status"])),
        admitted_at=datetime.fromisoformat(cast(str, data["admitted_at"])),
        called_at=datetime.fromisoformat(called_at) if called_at else None,
        revision=cast(int, data["revision"]),
    )


def skip_result_to_json(item: SkipResult) -> dict[str, object]:
    return {
        "skipped_entry_id": str(item.skipped_entry_id),
        "called_entry": queue_entry_to_json(item.called_entry) if item.called_entry else None,
    }


def skip_result_from_json(data: dict[str, object]) -> SkipResult:
    called = cast(dict[str, object] | None, data["called_entry"])
    return SkipResult(
        skipped_entry_id=UUID(cast(str, data["skipped_entry_id"])),
        called_entry=queue_entry_from_json(called) if called else None,
    )
