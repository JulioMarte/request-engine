from dataclasses import dataclass, field
from datetime import datetime
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
    expires_at: datetime | None = None
    reconcile_after_seconds: int | None = None


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
    result_data: dict[str, object] = field(default_factory=lambda: _empty_result_data())


class CommunicationDeliveryProvider(Protocol):
    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult: ...

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult: ...


def _empty_result_data() -> dict[str, object]:
    return {}
