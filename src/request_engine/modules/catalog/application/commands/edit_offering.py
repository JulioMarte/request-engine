"""Owner edits of an existing Offering: label rename and version supersession.

An OfferingVersion is immutable once created (booking terms and resource
requirements are INSERT-once per version). Duration and base price therefore
change by appending version N+1; existing Reservations, Holds and waitlist facts
keep the exact version they reference. The Offering-level label is mutable
configuration and is compare-and-set through ``offerings.revision``.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.catalog.application.commands.configure_offering_version_booking_terms import (  # noqa: E501
    ConfigureOfferingVersionBookingTermsCommand,
    validate_booking_terms_input,
)
from request_engine.modules.catalog.application.commands.update_location_operational_info import (
    validate_display_name,
)
from request_engine.modules.catalog.application.errors import CatalogInvalidInput

MAX_DURATION_MINUTES = 1440


@dataclass(frozen=True, slots=True)
class UpdateOfferingCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_id: UUID
    display_name: str
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OfferingState:
    offering_id: UUID
    offering_key: str
    display_name: str
    active: bool
    revision: int


@dataclass(frozen=True, slots=True)
class BaseTermsInput:
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class SupersedeOfferingVersionCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    offering_id: UUID
    expected_current_offering_version_id: UUID
    idempotency_key: str
    duration_minutes: int | None = None
    booking_terms: BaseTermsInput | None = None


@dataclass(frozen=True, slots=True)
class SupersededBaseTermsState:
    terms_id: UUID
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class SupersededOfferingVersionState:
    offering_id: UUID
    offering_version_id: UUID
    version: int
    previous_offering_version_id: UUID
    duration_minutes: int | None
    booking_terms: SupersededBaseTermsState | None
    requirement_count: int


class UpdateOfferingHandler(Protocol):
    async def update_offering(self, command: UpdateOfferingCommand) -> OfferingState: ...


class SupersedeOfferingVersionHandler(Protocol):
    async def supersede_offering_version(
        self, command: SupersedeOfferingVersionCommand
    ) -> SupersededOfferingVersionState: ...


async def update_offering(
    handler: UpdateOfferingHandler, command: UpdateOfferingCommand
) -> OfferingState:
    validate_update_offering(command)
    return await handler.update_offering(command)


def validate_update_offering(command: UpdateOfferingCommand) -> str:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if command.expected_revision <= 0:
        raise CatalogInvalidInput("expected_revision must be positive")
    return validate_display_name(command.display_name)


async def supersede_offering_version(
    handler: SupersedeOfferingVersionHandler, command: SupersedeOfferingVersionCommand
) -> SupersededOfferingVersionState:
    validate_supersede_offering_version(command)
    return await handler.supersede_offering_version(command)


def validate_supersede_offering_version(command: SupersedeOfferingVersionCommand) -> None:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if command.duration_minutes is None and command.booking_terms is None:
        raise CatalogInvalidInput("duration_minutes or booking_terms is required")
    if command.duration_minutes is not None and not (
        1 <= command.duration_minutes <= MAX_DURATION_MINUTES
    ):
        raise CatalogInvalidInput("duration_minutes must be between 1 and 1440")
    if command.booking_terms is not None:
        validate_booking_terms_input(
            ConfigureOfferingVersionBookingTermsCommand(
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                offering_version_id=command.expected_current_offering_version_id,
                amount=command.booking_terms.amount,
                currency=command.booking_terms.currency,
                idempotency_key=command.idempotency_key,
            )
        )
