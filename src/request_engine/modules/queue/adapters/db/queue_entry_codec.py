from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.queue.contracts.service_queue import QueueEntry, QueueEntryStatus


def queue_entry_from_row(row: RowMapping) -> QueueEntry:
    """Map the stable queue-entry persistence projection into the module contract."""

    return QueueEntry(
        id=cast(UUID, row["id"]),
        queue_id=cast(UUID, row["service_queue_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        status=QueueEntryStatus(cast(str, row["status"])),
        admitted_at=cast(datetime, row["admitted_at"]),
        called_at=cast(datetime | None, row["called_at"]),
        revision=cast(int, row["revision"]),
    )


def queue_entry_to_json(entry: QueueEntry) -> dict[str, object]:
    """Serialize a QueueEntry for deterministic idempotency replay storage."""

    return {
        "id": str(entry.id),
        "queue_id": str(entry.queue_id),
        "subject_party_id": str(entry.subject_party_id),
        "status": entry.status.value,
        "admitted_at": entry.admitted_at.isoformat(),
        "called_at": entry.called_at.isoformat() if entry.called_at else None,
        "revision": entry.revision,
    }


def queue_entry_from_json(data: dict[str, object]) -> QueueEntry:
    """Restore a QueueEntry from a completed idempotency result."""

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
