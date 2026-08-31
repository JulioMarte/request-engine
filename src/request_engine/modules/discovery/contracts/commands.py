import typing
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


DiscoveryEffectiveStartOrigin = typing.Literal["explicit", "resolved_now"]


@dataclass(frozen=True, slots=True)
class PublishDiscoverySupplyCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_id: UUID
    location_id: UUID
    resource_id: UUID | None
    effective_start: datetime
    effective_end: datetime | None
    provider_visibility: str
    idempotency_key: str
    effective_start_origin: DiscoveryEffectiveStartOrigin = "explicit"


@dataclass(frozen=True, slots=True)
class RevokeDiscoveryPublicationCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    publication_id: UUID
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class DiscoveryPublicationState:
    id: UUID
    offering_id: UUID
    location_id: UUID
    resource_id: UUID | None
    effective_start: datetime
    effective_end: datetime | None
    provider_visibility: str
    status: str
    revision: int
