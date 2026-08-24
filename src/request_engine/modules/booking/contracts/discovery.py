from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointment_options import DecodedAppointmentOption
from request_engine.modules.booking.contracts.appointments import AppointmentSlot


@dataclass(frozen=True, slots=True)
class PublishedSlotQuery:
    organization_id: UUID
    publication_id: UUID
    publication_revision: int
    mapping_id: UUID
    mapping_revision: int
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

    async def find_published_slots_batch(
        self,
        queries: tuple[PublishedSlotQuery, ...],
    ) -> tuple[tuple[AppointmentSlot, ...], ...]: ...


@dataclass(frozen=True, slots=True)
class DecodedDiscoveryHandoff:
    handoff_id: UUID
    organization_id: UUID
    option: DecodedAppointmentOption


class DiscoveryHandoffReader(Protocol):
    async def read_handoff(
        self,
        organization_id: UUID,
        token: str,
    ) -> DecodedDiscoveryHandoff: ...
