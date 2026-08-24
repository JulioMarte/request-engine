from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.discovery.application.commands.mapping import (
    OfferingServiceClassificationState,
)


@dataclass(frozen=True, slots=True)
class RevokeOfferingServiceClassificationCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_id: UUID
    expected_revision: int
    idempotency_key: str


class RevokeOfferingMappingHandler(Protocol):
    async def revoke_mapping(
        self, command: RevokeOfferingServiceClassificationCommand
    ) -> OfferingServiceClassificationState: ...


async def revoke_offering_service_classification(
    handler: RevokeOfferingMappingHandler,
    command: RevokeOfferingServiceClassificationCommand,
) -> OfferingServiceClassificationState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    return await handler.revoke_mapping(command)
