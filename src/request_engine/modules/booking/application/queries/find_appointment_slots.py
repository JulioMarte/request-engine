from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot


@dataclass(frozen=True, slots=True)
class FindAppointmentSlotsQuery:
    organization_id: UUID
    offering_version_id: UUID
    window_start: datetime
    window_end: datetime
    location_id: UUID | None = None
    limit: int = 50


class AppointmentAvailabilityReader(Protocol):
    async def find_slots(self, query: FindAppointmentSlotsQuery) -> tuple[AppointmentSlot, ...]: ...


async def find_appointment_slots(
    reader: AppointmentAvailabilityReader,
    query: FindAppointmentSlotsQuery,
) -> tuple[AppointmentSlot, ...]:
    if query.limit <= 0 or query.limit > 200:
        raise ValueError("limit must be between 1 and 200")
    return await reader.find_slots(query)
