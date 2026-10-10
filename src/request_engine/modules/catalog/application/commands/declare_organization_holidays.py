from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from request_engine.modules.catalog.application.errors import CatalogInvalidInput


@dataclass(frozen=True, slots=True)
class OrganizationHolidayInput:
    date: date
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DeclareOrganizationHolidaysCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    holidays: tuple[OrganizationHolidayInput, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class DeclaredOrganizationHolidaysState:
    holidays: tuple[OrganizationHolidayInput, ...]
    locations_covered: int
    exceptions_created: int
    exceptions_already_declared: int


class DeclareOrganizationHolidaysHandler(Protocol):
    async def declare_organization_holidays(
        self, command: DeclareOrganizationHolidaysCommand
    ) -> DeclaredOrganizationHolidaysState: ...


async def declare_organization_holidays(
    handler: DeclareOrganizationHolidaysHandler,
    command: DeclareOrganizationHolidaysCommand,
) -> DeclaredOrganizationHolidaysState:
    if not command.idempotency_key:
        raise CatalogInvalidInput("idempotency_key is required")
    if not command.holidays:
        raise CatalogInvalidInput("at least one holiday date is required")
    seen: set[date] = set()
    for holiday in command.holidays:
        if holiday.date in seen:
            raise CatalogInvalidInput("holidays must not repeat a date")
        seen.add(holiday.date)
        if holiday.reason is not None and not holiday.reason.strip():
            raise CatalogInvalidInput("holiday reason cannot be blank")
    return await handler.declare_organization_holidays(command)
