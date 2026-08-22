from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot


@dataclass(frozen=True, slots=True)
class PublishedSlotQuery:
    organization_id: UUID
    offering_version_id: UUID
    window_start: datetime
    window_end: datetime
    location_id: UUID
    resource_id: UUID | None = None
    limit: int = 20


class PublishedSlotReader(Protocol):
    async def find_published_slots(
        self,
        query: PublishedSlotQuery,
    ) -> tuple[AppointmentSlot, ...]: ...
