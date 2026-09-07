from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.onboarding import BookingOnboardingReadinessReader
from request_engine.modules.catalog.contracts.onboarding import CatalogOnboardingReadinessReader
from request_engine.modules.communications.contracts.onboarding import (
    CommunicationsOnboardingReadinessReader,
)
from request_engine.modules.queue.contracts.onboarding import QueueOnboardingReadinessReader
from request_engine.modules.tenancy.contracts.onboarding_readiness import BusinessPartyReader


@dataclass(frozen=True, slots=True)
class OnboardingReadiness:
    has_business_party: bool
    location_count: int
    bookable_offering_version_count: int
    resource_supply_count: int
    active_queue_count: int
    disabled_purpose_count: int


class OnboardingReadinessReader(Protocol):
    async def read(self, *, organization_id: UUID) -> OnboardingReadiness: ...


class OwnerBackedOnboardingReadiness:
    """Compose readiness without taking ownership of any source module's facts."""

    def __init__(
        self,
        *,
        party_reader: BusinessPartyReader,
        catalog_reader: CatalogOnboardingReadinessReader,
        booking_reader: BookingOnboardingReadinessReader,
        queue_reader: QueueOnboardingReadinessReader,
        communications_reader: CommunicationsOnboardingReadinessReader,
    ) -> None:
        self._party_reader = party_reader
        self._catalog_reader = catalog_reader
        self._booking_reader = booking_reader
        self._queue_reader = queue_reader
        self._communications_reader = communications_reader

    async def read(self, *, organization_id: UUID) -> OnboardingReadiness:
        has_business_party = await self._party_reader.has_active_organization_party(
            organization_id=organization_id
        )
        catalog = await self._catalog_reader.read_catalog_supply(organization_id=organization_id)
        booking = await self._booking_reader.read_booking_supply(organization_id=organization_id)
        queue = await self._queue_reader.read_queue_supply(organization_id=organization_id)
        communications = await self._communications_reader.read_communications_supply(
            organization_id=organization_id
        )
        return OnboardingReadiness(
            has_business_party=has_business_party,
            location_count=catalog.location_count,
            bookable_offering_version_count=catalog.bookable_offering_version_count,
            resource_supply_count=booking.resource_supply_count,
            active_queue_count=queue.active_queue_count,
            disabled_purpose_count=communications.disabled_purpose_count,
        )
