from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    BookingContextTermsState,
)
from request_engine.modules.booking.domain.availability import require_aware_utc


@dataclass(frozen=True, slots=True)
class SupersedeBookingContextTermsCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    current_context_terms_id: UUID
    expected_current_revision: int
    effective_from: datetime
    amount: Decimal | None
    currency: str | None
    planned_duration_minutes: int | None
    bookable: bool
    idempotency_key: str


class SupersedeBookingContextTermsHandler(Protocol):
    async def supersede_booking_context_terms(
        self, command: SupersedeBookingContextTermsCommand
    ) -> BookingContextTermsState: ...


async def supersede_booking_context_terms(
    handler: SupersedeBookingContextTermsHandler,
    command: SupersedeBookingContextTermsCommand,
) -> BookingContextTermsState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_current_revision <= 0:
        raise ValueError("expected_current_revision must be positive")
    require_aware_utc(command.effective_from, "effective_from")
    if (command.amount is None) != (command.currency is None):
        raise ValueError("amount and currency must be present together")
    if command.amount is not None and command.amount < 0:
        raise ValueError("amount must be non-negative")
    if command.currency is not None and (
        len(command.currency) != 3
        or not command.currency.isalpha()
        or command.currency != command.currency.upper()
    ):
        raise ValueError("currency must be an uppercase three-letter code")
    if command.planned_duration_minutes is not None and command.planned_duration_minutes <= 0:
        raise ValueError("planned_duration_minutes must be positive")
    if command.amount is None and command.planned_duration_minutes is None and command.bookable:
        raise ValueError("bookable context terms require a material override")
    return await handler.supersede_booking_context_terms(command)
