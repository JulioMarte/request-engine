from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID

from request_engine.modules.catalog.application.errors import CatalogInvalidInput


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
    validate_booking_terms_input(command)
    return await handler.configure_offering_version_booking_terms(command)


def validate_booking_terms_input(command: ConfigureOfferingVersionBookingTermsCommand) -> None:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if not command.amount.is_finite() or command.amount < 0:
        raise CatalogInvalidInput("amount must be finite and non-negative")
    if command.amount >= Decimal("100000000000000"):
        raise CatalogInvalidInput("amount cannot exceed 14 integer digits")
    representation = command.amount.as_tuple()
    exponent = cast(int, representation.exponent)
    if not -16383 <= exponent <= 131071:
        raise CatalogInvalidInput(
            "amount exponent exceeds PostgreSQL numeric representation limits"
        )
    digits = representation.digits
    significant_end = len(digits)
    while significant_end and digits[significant_end - 1] == 0:
        significant_end -= 1
    exponent += len(digits) - significant_end
    if significant_end and exponent < -6:
        raise CatalogInvalidInput("amount cannot exceed 6 fractional digits")
    if (
        len(command.currency) != 3
        or not command.currency.isascii()
        or not command.currency.isalpha()
        or command.currency != command.currency.upper()
    ):
        raise CatalogInvalidInput("currency must be an uppercase three-letter code")
