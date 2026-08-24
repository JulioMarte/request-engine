from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MapOfferingToServiceClassificationCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_id: UUID
    classification_key: str
    idempotency_key: str
    expected_revision: int | None = None


@dataclass(frozen=True, slots=True)
class OfferingServiceClassificationState:
    id: UUID
    offering_id: UUID
    service_classification_id: UUID
    classification_key: str
    status: str
    revision: int


class MapOfferingHandler(Protocol):
    async def map_offering(
        self, command: MapOfferingToServiceClassificationCommand
    ) -> OfferingServiceClassificationState: ...


async def map_offering_to_service_classification(
    handler: MapOfferingHandler,
    command: MapOfferingToServiceClassificationCommand,
) -> OfferingServiceClassificationState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.classification_key.strip():
        raise ValueError("classification_key is required")
    if command.expected_revision is not None and command.expected_revision < 1:
        raise ValueError("expected_revision must be positive")
    return await handler.map_offering(command)
