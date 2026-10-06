from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID

from request_engine.modules.booking.application.operational_errors import BookingTermsInvalidInput


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
    validate_context_terms_amount(command.amount)
    return await handler.configure_booking_context_terms(command)


def validate_context_terms_amount(amount: Decimal | None) -> None:
    """Admit exact numeric(20,6) values without decimal-context rounding."""
    if amount is None:
        return
    if not amount.is_finite() or amount < 0:
        raise BookingTermsInvalidInput("amount must be finite and non-negative")
    representation = amount.as_tuple()
    exponent = cast(int, representation.exponent)
    if not -16383 <= exponent <= 131071:
        raise BookingTermsInvalidInput("amount exponent exceeds numeric representation limits")
    if amount >= Decimal("100000000000000"):
        raise BookingTermsInvalidInput("amount cannot exceed 14 integer digits")
    significant_end = len(representation.digits)
    while significant_end and representation.digits[significant_end - 1] == 0:
        significant_end -= 1
        exponent += 1
    if significant_end and exponent < -6:
        raise BookingTermsInvalidInput("amount cannot exceed 6 significant fractional digits")
