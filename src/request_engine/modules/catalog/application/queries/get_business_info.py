from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BusinessLocation:
    id: UUID
    location_key: str
    display_name: str
    timezone: str
    public_data: dict[str, object]


@dataclass(frozen=True, slots=True)
class BusinessInfo:
    organization_id: UUID
    organization_key: str
    display_name: str
    public_profile: dict[str, object]
    locations: tuple[BusinessLocation, ...]


class BusinessInfoReader(Protocol):
    async def get_business_info(self, organization_id: UUID) -> BusinessInfo: ...


async def get_business_info(
    reader: BusinessInfoReader,
    organization_id: UUID,
) -> BusinessInfo:
    """Return the tenant-scoped structured business information capability."""

    return await reader.get_business_info(organization_id)
