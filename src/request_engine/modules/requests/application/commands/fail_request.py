from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.contracts.request import Request


@dataclass(frozen=True, slots=True)
class FailRequestCommand:
    organization_id: UUID
    principal_id: UUID
    request_id: UUID
    idempotency_key: str
    error_class: str
    details: dict[str, object] | None = None
    expected_revision: int | None = None


class FailRequestHandler(Protocol):
    async def fail_request(self, command: FailRequestCommand) -> Request: ...


async def fail_request(
    handler: FailRequestHandler,
    command: FailRequestCommand,
) -> Request:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.error_class:
        raise ValueError("error_class is required")
    if command.expected_revision is not None and command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await handler.fail_request(command)
