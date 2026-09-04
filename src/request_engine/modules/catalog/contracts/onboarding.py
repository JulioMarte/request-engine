from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CatalogOnboardingSupply:
    """Catalog-owned facts consumed by the onboarding readiness composition."""

    location_count: int
    bookable_offering_version_count: int


class CatalogOnboardingReadinessReader(Protocol):
    async def read_catalog_supply(self, *, organization_id: UUID) -> CatalogOnboardingSupply: ...
