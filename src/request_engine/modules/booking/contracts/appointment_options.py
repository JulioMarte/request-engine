from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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
    planned_duration_minutes: int | None = None
    amount: Decimal | None = None
    currency: str | None = None
    location_operational_revision: int | None = None
    configuration_fingerprint: str | None = None

    @property
    def is_contextual(self) -> bool:
        return self.configuration_fingerprint is not None


class AppointmentOptionCodec(Protocol):
    """Issue and verify opaque, tamper-evident appointment selection tokens."""

    def issue(self, organization_id: UUID, slot: AppointmentSlot) -> str: ...

    def decode(self, organization_id: UUID, token: str) -> DecodedAppointmentOption: ...
