from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ProviderDeliveryStatus(StrEnum):
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class ProviderSendRequest:
    delivery_id: UUID
    communication_task_id: UUID
    provider_key: str
    provider_idempotency_key: str
    channel: str
    destination: str
    template_key: str
    template_version: int
    render_context: dict[str, object]


@dataclass(frozen=True, slots=True)
class ProviderLookupRequest:
    delivery_id: UUID
    communication_task_id: UUID
    provider_key: str
    provider_idempotency_key: str
    provider_message_id: str | None


@dataclass(frozen=True, slots=True)
class ProviderDeliveryResult:
    status: ProviderDeliveryStatus
    provider_message_id: str | None = None
    retryable: bool = False
    result_data: dict[str, object] = field(default_factory=dict)


class CommunicationDeliveryProvider(Protocol):
    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult: ...

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult: ...
