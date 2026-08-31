from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CopilotOfferingMatch:
    offering_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class CopilotLocationClock:
    location_id: UUID
    timezone: str
    observed_at: datetime
    operational_day_end_at: datetime | None
    operational_revision: int


class CopilotCatalogReader(Protocol):
    async def find_offerings(
        self,
        *,
        organization_id: UUID,
        reference: str,
    ) -> tuple[CopilotOfferingMatch, ...]: ...

    async def read_location_clock(
        self,
        *,
        organization_id: UUID,
        location_id: UUID,
    ) -> CopilotLocationClock | None: ...
