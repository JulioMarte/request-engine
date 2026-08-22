from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    BookingContextTermsState,
)
from request_engine.modules.booking.application.commands.supersede_booking_context_terms import (
    SupersedeBookingContextTermsCommand,
)


def command_payload(
    command: SupersedeBookingContextTermsCommand,
    *,
    cutover: datetime,
) -> dict[str, object]:
    return {
        "authority_party_id": command.authority_party_id,
        "current_context_terms_id": command.current_context_terms_id,
        "expected_current_revision": command.expected_current_revision,
        "effective_from": cutover,
        "amount": str(command.amount) if command.amount is not None else None,
        "currency": command.currency,
        "planned_duration_minutes": command.planned_duration_minutes,
        "bookable": command.bookable,
    }


def to_json(state: BookingContextTermsState) -> dict[str, object]:
    return {
        "context_terms_id": str(state.context_terms_id),
        "resource_location_assignment_id": str(state.resource_location_assignment_id),
        "offering_version_id": str(state.offering_version_id),
        "effective_from": state.effective_from.isoformat(),
        "effective_until": state.effective_until.isoformat() if state.effective_until else None,
        "amount": str(state.amount) if state.amount is not None else None,
        "currency": state.currency,
        "planned_duration_minutes": state.planned_duration_minutes,
        "bookable": state.bookable,
        "revision": state.revision,
    }


def from_json(value: dict[str, object]) -> BookingContextTermsState:
    end = cast(str | None, value.get("effective_until"))
    amount = cast(str | None, value.get("amount"))
    return BookingContextTermsState(
        UUID(cast(str, value["context_terms_id"])),
        UUID(cast(str, value["resource_location_assignment_id"])),
        UUID(cast(str, value["offering_version_id"])),
        datetime.fromisoformat(cast(str, value["effective_from"])),
        datetime.fromisoformat(end) if end else None,
        Decimal(amount) if amount else None,
        cast(str | None, value.get("currency")),
        cast(int | None, value.get("planned_duration_minutes")),
        cast(bool, value["bookable"]),
        cast(int, value["revision"]),
    )
