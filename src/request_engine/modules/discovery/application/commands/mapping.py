from dataclasses import dataclass
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
