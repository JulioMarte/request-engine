from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.contracts.request import Request


@dataclass(frozen=True, slots=True)
class CompleteRequestCommand:
    organization_id: UUID
    principal_id: UUID
    request_id: UUID
    idempotency_key: str
    result_payload: dict[str, object] | None = None
    expected_revision: int | None = None


class CompleteRequestHandler(Protocol):
    async def complete_request(self, command: CompleteRequestCommand) -> Request: ...


async def complete_request(
    handler: CompleteRequestHandler,
    command: CompleteRequestCommand,
) -> Request:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision is not None and command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await handler.complete_request(command)
