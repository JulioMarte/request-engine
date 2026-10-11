from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.platform_context import PlatformActorContext

PLATFORM_ORGANIZATION_READ_CAPABILITY = "platform.organization.read"


class PlatformOrganizationReadError(RuntimeError):
    """Bounded failure while inspecting organizations from the platform plane."""


class PlatformOrganizationReadForbidden(PlatformOrganizationReadError):
    pass


class PlatformOrganizationReadNotFound(PlatformOrganizationReadError):
    pass


class PlatformOrganizationReadInvalid(PlatformOrganizationReadError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformOrganizationSummary:
    organization_id: UUID
    organization_key: str
    display_name: str
    operational_status: str
    default_timezone: str | None
    default_locale: str | None
    default_currency: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ListPlatformOrganizationsQuery:
    after: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class GetPlatformOrganizationQuery:
    organization_id: UUID


class PlatformOrganizationReader(Protocol):
    async def list_organizations(
        self,
        actor: PlatformActorContext,
        query: ListPlatformOrganizationsQuery,
    ) -> tuple[PlatformOrganizationSummary, ...]: ...

    async def get_organization(
        self,
        actor: PlatformActorContext,
        query: GetPlatformOrganizationQuery,
    ) -> PlatformOrganizationSummary: ...
