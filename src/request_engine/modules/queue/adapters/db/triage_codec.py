from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.queue.contracts.triage import (
    QueueTriageResult,
    RecallHold,
    RecallHoldKind,
)


def result_to_json(result: QueueTriageResult) -> dict[str, object]:
    hold = result.hold
    return {
        "queue_entry_id": str(result.queue_entry_id),
        "queue_id": str(result.queue_id),
        "status": result.status,
        "revision": result.revision,
        "action": result.action,
        "reason": result.reason,
        "hold": None if hold is None else _hold_to_json(hold),
    }


def result_from_json(data: dict[str, object]) -> QueueTriageResult:
    raw_hold = cast(dict[str, object] | None, data["hold"])
    return QueueTriageResult(
        queue_entry_id=UUID(cast(str, data["queue_entry_id"])),
        queue_id=UUID(cast(str, data["queue_id"])),
        status=cast(str, data["status"]),
        revision=cast(int, data["revision"]),
        action=cast(str, data["action"]),
        reason=cast(str | None, data["reason"]),
        hold=None if raw_hold is None else _hold_from_json(raw_hold),
    )


def _hold_to_json(hold: RecallHold) -> dict[str, object]:
    return {
        "id": str(hold.id),
        "queue_entry_id": str(hold.queue_entry_id),
        "condition_kind": hold.condition_kind.value,
        "until_at": hold.until_at.isoformat() if hold.until_at else None,
        "event_key": hold.event_key,
        "reason": hold.reason,
        "created_at": hold.created_at.isoformat(),
    }


def _hold_from_json(data: dict[str, object]) -> RecallHold:
    raw_until = cast(str | None, data["until_at"])
    return RecallHold(
        id=UUID(cast(str, data["id"])),
        queue_entry_id=UUID(cast(str, data["queue_entry_id"])),
        condition_kind=RecallHoldKind(cast(str, data["condition_kind"])),
        until_at=datetime.fromisoformat(raw_until) if raw_until else None,
        event_key=cast(str | None, data["event_key"]),
        reason=cast(str | None, data["reason"]),
        created_at=datetime.fromisoformat(cast(str, data["created_at"])),
    )
