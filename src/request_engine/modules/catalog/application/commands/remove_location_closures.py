"""Remove saved Location closures by deactivating them (rows stay auditable).

``location_hours_exceptions`` rows are never deleted: a removed special schedule
or holiday is the same row with ``active = false``. The row's trigger advances
the Location ``operational_revision`` exactly as any other exception change.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from request_engine.modules.catalog.application.commands.set_location_hours_exception import (
    LocationHoursExceptionState,
)
from request_engine.modules.catalog.application.errors import CatalogInvalidInput

MAX_HOLIDAY_DATES = 366


@dataclass(frozen=True, slots=True)
class DeactivateLocationHoursExceptionCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    exception_id: UUID
    expected_operational_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RemoveOrganizationHolidaysCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    dates: tuple[date, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class RemovedOrganizationHolidaysState:
    dates: tuple[date, ...]
    locations_examined: int
    exceptions_deactivated: int
    dates_not_found: tuple[date, ...]


class DeactivateLocationHoursExceptionHandler(Protocol):
    async def deactivate_location_hours_exception(
        self, command: DeactivateLocationHoursExceptionCommand
    ) -> LocationHoursExceptionState: ...


class RemoveOrganizationHolidaysHandler(Protocol):
    async def remove_organization_holidays(
        self, command: RemoveOrganizationHolidaysCommand
    ) -> RemovedOrganizationHolidaysState: ...


async def deactivate_location_hours_exception(
    handler: DeactivateLocationHoursExceptionHandler,
    command: DeactivateLocationHoursExceptionCommand,
) -> LocationHoursExceptionState:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if command.expected_operational_revision <= 0:
        raise CatalogInvalidInput("expected_operational_revision must be positive")
    return await handler.deactivate_location_hours_exception(command)


async def remove_organization_holidays(
    handler: RemoveOrganizationHolidaysHandler,
    command: RemoveOrganizationHolidaysCommand,
) -> RemovedOrganizationHolidaysState:
    validate_holiday_removal(command)
    return await handler.remove_organization_holidays(command)


def validate_holiday_removal(command: RemoveOrganizationHolidaysCommand) -> None:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if not command.dates:
        raise CatalogInvalidInput("at least one holiday date is required")
    if len(command.dates) > MAX_HOLIDAY_DATES:
        raise CatalogInvalidInput("at most 366 holiday dates can be removed at once")
    if len(set(command.dates)) != len(command.dates):
        raise CatalogInvalidInput("dates must not repeat")
