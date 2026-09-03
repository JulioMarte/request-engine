from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class QueueOnboardingSupply:
    """Queue-owned facts consumed by the onboarding readiness composition."""

    active_queue_count: int


class QueueOnboardingReadinessReader(Protocol):
    async def read_queue_supply(self, *, organization_id: UUID) -> QueueOnboardingSupply: ...
