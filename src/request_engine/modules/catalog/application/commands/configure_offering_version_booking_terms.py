from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OfferingVersionBookingTermsState:
    terms_id: UUID
    offering_version_id: UUID
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ConfigureOfferingVersionBookingTermsCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_version_id: UUID
    amount: Decimal
    currency: str
    idempotency_key: str


class ConfigureOfferingVersionBookingTermsHandler(Protocol):
    async def configure_offering_version_booking_terms(
        self, command: ConfigureOfferingVersionBookingTermsCommand
    ) -> OfferingVersionBookingTermsState: ...


async def configure_offering_version_booking_terms(
    handler: ConfigureOfferingVersionBookingTermsHandler,
    command: ConfigureOfferingVersionBookingTermsCommand,
) -> OfferingVersionBookingTermsState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.amount < 0:
        raise ValueError("amount must be non-negative")
    if (
        len(command.currency) != 3
        or not command.currency.isalpha()
        or command.currency != command.currency.upper()
    ):
        raise ValueError("currency must be an uppercase three-letter code")
    return await handler.configure_offering_version_booking_terms(command)
