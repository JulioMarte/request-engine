from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BookingOnboardingSupply:
    """Booking-owned facts consumed by the onboarding readiness composition."""

    resource_supply_count: int


class BookingOnboardingReadinessReader(Protocol):
    async def read_booking_supply(self, *, organization_id: UUID) -> BookingOnboardingSupply: ...
