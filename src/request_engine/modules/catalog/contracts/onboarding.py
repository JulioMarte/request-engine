from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CatalogOnboardingSupply:
    """Active locations and latest bookable versions of active Offerings.

    Structural configuration only, not resource eligibility or slot availability.
    """

    location_count: int
    bookable_offering_version_count: int


class CatalogOnboardingReadinessReader(Protocol):
    async def read_catalog_supply(self, *, organization_id: UUID) -> CatalogOnboardingSupply: ...
