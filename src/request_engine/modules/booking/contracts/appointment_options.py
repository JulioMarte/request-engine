from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice


@dataclass(frozen=True, slots=True)
class DecodedAppointmentOption:
    """Verified contextual booking selection recovered from an opaque option token."""

    organization_id: UUID
    offering_version_id: UUID
    start_at: datetime
    end_at: datetime
    location_id: UUID
    resources: tuple[ResourceChoice, ...]
    expires_at: datetime
    planned_duration_minutes: int
    amount: Decimal
    currency: str
    location_operational_revision: int
    configuration_fingerprint: str


class AppointmentOptionCodec(Protocol):
    """Issue and verify opaque, tamper-evident contextual appointment selections."""

    def issue(self, organization_id: UUID, slot: AppointmentSlot) -> str: ...

    def decode(self, organization_id: UUID, token: str) -> DecodedAppointmentOption: ...
