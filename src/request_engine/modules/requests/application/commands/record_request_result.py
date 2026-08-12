from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.contracts.request import Request


@dataclass(frozen=True, slots=True)
class RecordRequestResultCommand:
    organization_id: UUID
    principal_id: UUID
    request_id: UUID
    result_payload: dict[str, object]
    idempotency_key: str
    expected_revision: int | None = None


class RecordRequestResultHandler(Protocol):
    async def record_request_result(self, command: RecordRequestResultCommand) -> Request: ...


async def record_request_result(
    handler: RecordRequestResultHandler,
    command: RecordRequestResultCommand,
) -> Request:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision is not None and command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await handler.record_request_result(command)
