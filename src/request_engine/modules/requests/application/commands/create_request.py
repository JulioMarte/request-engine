from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.requests.contracts.request import (
    ExternalCorrelationInput,
    Request,
    RequestParticipantInput,
)


@dataclass(frozen=True, slots=True)
class CreateRequestCommand:
    organization_id: UUID
    principal_id: UUID
    request_definition_version_id: UUID
    payload: dict[str, object]
    idempotency_key: str
    requester_party_id: UUID | None = None
    recipient_party_id: UUID | None = None
    participants: tuple[RequestParticipantInput, ...] = ()
    correlations: tuple[ExternalCorrelationInput, ...] = ()


class CreateRequestHandler(Protocol):
    async def create_request(self, command: CreateRequestCommand) -> Request: ...


async def create_request(handler: CreateRequestHandler, command: CreateRequestCommand) -> Request:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    for participant in command.participants:
        if not participant.role_key:
            raise ValueError("participant role_key is required")
    for correlation in command.correlations:
        if not correlation.correlation_kind:
            raise ValueError("correlation_kind is required")
        if not correlation.provider_key:
            raise ValueError("correlation provider_key is required")
        if not correlation.external_key:
            raise ValueError("correlation external_key is required")
    return await handler.create_request(command)
