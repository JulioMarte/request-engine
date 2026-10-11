from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SupplyConfigurationQuery:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    limit: int = 50
    after: UUID | None = None
    resource_id: UUID | None = None
    location_id: UUID | None = None
    assignment_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ResourceConfiguration:
    resource_id: UUID
    resource_key: str
    display_name: str
    capacity_model: str
    capacity_units: int
    active: bool
    availability_revision: int
    capability_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class AssignmentConfiguration:
    assignment_id: UUID
    resource_id: UUID
    location_id: UUID
    status: str
    effective_from: datetime
    effective_until: datetime | None
    assignment_revision: int
    resource_availability_revision: int


@dataclass(frozen=True, slots=True)
class TermsConfiguration:
    context_terms_id: UUID
    resource_location_assignment_id: UUID
    offering_version_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    amount: Decimal | None
    currency: str | None
    planned_duration_minutes: int | None
    bookable: bool
    active: bool
    revision: int


@dataclass(frozen=True, slots=True)
class AvailabilityConfiguration:
    window_id: UUID
    assignment_id: UUID
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None
    valid_until: date | None
    active: bool
    resource_availability_revision: int


@dataclass(frozen=True, slots=True)
class ExceptionConfiguration:
    exception_id: UUID
    resource_id: UUID
    assignment_id: UUID | None
    start_at: datetime
    end_at: datetime
    exception_kind: str
    reason: str | None
    active: bool
    resource_availability_revision: int


class SupplyConfigurationReader(Protocol):
    async def read_resources(
        self, query: SupplyConfigurationQuery
    ) -> tuple[ResourceConfiguration, ...]: ...
    async def read_assignments(
        self, query: SupplyConfigurationQuery
    ) -> tuple[AssignmentConfiguration, ...]: ...
    async def read_terms(
        self, query: SupplyConfigurationQuery
    ) -> tuple[TermsConfiguration, ...]: ...
    async def read_availability(
        self, query: SupplyConfigurationQuery
    ) -> tuple[AvailabilityConfiguration, ...]: ...
    async def read_exceptions(
        self, query: SupplyConfigurationQuery
    ) -> tuple[ExceptionConfiguration, ...]: ...
