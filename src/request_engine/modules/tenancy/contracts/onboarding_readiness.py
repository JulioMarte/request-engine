from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OnboardingReadinessFacts:
    """Owner-backed facts the onboarding readiness report is composed from."""

    has_business_party: bool
    location_count: int
    bookable_offering_version_count: int
    resource_supply_count: int
    active_queue_count: int
    disabled_purpose_count: int


class OnboardingReadinessFactsReader(Protocol):
    async def read_onboarding_facts(self, *, organization_id: UUID) -> OnboardingReadinessFacts: ...


class BusinessPartyReader(Protocol):
    async def has_active_organization_party(self, *, organization_id: UUID) -> bool: ...
