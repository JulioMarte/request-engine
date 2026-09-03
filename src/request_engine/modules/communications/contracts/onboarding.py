from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CommunicationsOnboardingSupply:
    """Communications-owned facts consumed by the onboarding readiness composition."""

    disabled_purpose_count: int


class CommunicationsOnboardingReadinessReader(Protocol):
    async def read_communications_supply(
        self, *, organization_id: UUID
    ) -> CommunicationsOnboardingSupply: ...
