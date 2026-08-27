from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.queue.contracts.intake import QueueIntakeControlState


def intake_state_from_row(row: Mapping[str, object]) -> QueueIntakeControlState:
    return QueueIntakeControlState(
        service_queue_id=cast(UUID, row["service_queue_id"]),
        accepting=cast(bool, row["accepting"]),
        reason=cast(str | None, row["reason"]),
        effective_until=cast(datetime | None, row["effective_until"]),
        revision=cast(int, row["revision"]),
        updated_at=cast(datetime, row["updated_at"]),
    )


def intake_state_to_json(state: QueueIntakeControlState) -> dict[str, object]:
    return {
        "service_queue_id": str(state.service_queue_id),
        "accepting": state.accepting,
        "reason": state.reason,
        "effective_until": state.effective_until.isoformat() if state.effective_until else None,
        "revision": state.revision,
        "updated_at": state.updated_at.isoformat(),
    }


def intake_state_from_json(payload: Mapping[str, object]) -> QueueIntakeControlState:
    effective_until = payload.get("effective_until")
    parsed_effective_until = (
        datetime.fromisoformat(cast(str, effective_until)) if effective_until is not None else None
    )
    return QueueIntakeControlState(
        service_queue_id=UUID(cast(str, payload["service_queue_id"])),
        accepting=cast(bool, payload["accepting"]),
        reason=cast(str | None, payload.get("reason")),
        effective_until=parsed_effective_until,
        revision=cast(int, payload["revision"]),
        updated_at=datetime.fromisoformat(cast(str, payload["updated_at"])),
    )
