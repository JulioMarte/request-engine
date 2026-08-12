from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.contracts.request import Request


@dataclass(frozen=True, slots=True)
class CancelRequestCommand:
    organization_id: UUID
    principal_id: UUID
    request_id: UUID
    idempotency_key: str
    reason: str | None = None
    expected_revision: int | None = None
    allow_party_override: bool = False


class CancelRequestHandler(Protocol):
    async def cancel_request(self, command: CancelRequestCommand) -> Request: ...


async def cancel_request(
    handler: CancelRequestHandler,
    command: CancelRequestCommand,
) -> Request:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision is not None and command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await handler.cancel_request(command)
