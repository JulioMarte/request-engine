from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BookingContextTermsState:
    context_terms_id: UUID
    resource_location_assignment_id: UUID
    offering_version_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    amount: Decimal | None
    currency: str | None
    planned_duration_minutes: int | None
    bookable: bool
    revision: int


@dataclass(frozen=True, slots=True)
class ConfigureBookingContextTermsCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    resource_location_assignment_id: UUID
    offering_version_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    amount: Decimal | None
    currency: str | None
    planned_duration_minutes: int | None
    bookable: bool
    idempotency_key: str


class ConfigureBookingContextTermsHandler(Protocol):
    async def configure_booking_context_terms(
        self,
        command: ConfigureBookingContextTermsCommand,
    ) -> BookingContextTermsState: ...


async def configure_booking_context_terms(
    handler: ConfigureBookingContextTermsHandler,
    command: ConfigureBookingContextTermsCommand,
) -> BookingContextTermsState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await handler.configure_booking_context_terms(command)
