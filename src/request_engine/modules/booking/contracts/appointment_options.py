from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice


@dataclass(frozen=True, slots=True)
class DecodedAppointmentOption:
    """Verified concrete booking selection recovered from an opaque option token."""

    organization_id: UUID
    offering_version_id: UUID
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoice, ...]
    expires_at: datetime


class AppointmentOptionCodec(Protocol):
    """Issue and verify opaque, tamper-evident appointment selection tokens."""

    def issue(self, organization_id: UUID, slot: AppointmentSlot) -> str: ...

    def decode(self, organization_id: UUID, token: str) -> DecodedAppointmentOption: ...
