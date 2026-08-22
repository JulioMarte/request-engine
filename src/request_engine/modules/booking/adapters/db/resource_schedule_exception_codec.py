from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.booking.application.commands.set_resource_schedule_exception import (
    ResourceScheduleExceptionState,
)


def to_json(state: ResourceScheduleExceptionState) -> dict[str, object]:
    return {
        "exception_id": str(state.exception_id),
        "resource_id": str(state.resource_id),
        "start_at": state.start_at.isoformat(),
        "end_at": state.end_at.isoformat(),
        "exception_kind": state.exception_kind,
        "reason": state.reason,
        "resource_availability_revision": state.resource_availability_revision,
    }


def from_json(value: dict[str, object]) -> ResourceScheduleExceptionState:
    kind = cast(str, value["exception_kind"])
    if kind not in ("available", "unavailable"):
        raise ValueError("stored exception_kind is invalid")
    return ResourceScheduleExceptionState(
        exception_id=UUID(cast(str, value["exception_id"])),
        resource_id=UUID(cast(str, value["resource_id"])),
        start_at=datetime.fromisoformat(cast(str, value["start_at"])),
        end_at=datetime.fromisoformat(cast(str, value["end_at"])),
        exception_kind=kind,
        reason=cast(str | None, value.get("reason")),
        resource_availability_revision=cast(int, value["resource_availability_revision"]),
    )
