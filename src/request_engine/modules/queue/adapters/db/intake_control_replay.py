from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.queue.contracts.intake import SetQueueIntakeControlRequest


def request_to_json(request: SetQueueIntakeControlRequest) -> dict[str, object]:
    return {
        "service_queue_id": str(request.service_queue_id),
        "accepting": request.accepting,
        "expected_revision": request.expected_revision,
        "reason": request.reason,
        "effective_until": (
            request.effective_until.isoformat() if request.effective_until is not None else None
        ),
    }


def request_from_json(
    payload: dict[str, object],
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
) -> SetQueueIntakeControlRequest:
    effective_until = payload.get("effective_until")
    return SetQueueIntakeControlRequest(
        organization_id=organization_id,
        principal_id=principal_id,
        service_queue_id=UUID(str(payload["service_queue_id"])),
        accepting=cast(bool, payload["accepting"]),
        expected_revision=cast(int, payload["expected_revision"]),
        idempotency_key=idempotency_key,
        reason=cast(str | None, payload.get("reason")),
        effective_until=(
            datetime.fromisoformat(str(effective_until)) if effective_until is not None else None
        ),
    )
