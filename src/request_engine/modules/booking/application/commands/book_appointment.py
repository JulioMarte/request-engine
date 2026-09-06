from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.application.errors import (
    AppointmentOptionStale,
    OfferingVersionNotBookable,
    OfferingVersionNotFound,
)
from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice


@dataclass(frozen=True, slots=True)
class BookAppointmentCommand:
    organization_id: UUID
    principal_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    start_at: datetime
    resources: tuple[ResourceChoice, ...]
    idempotency_key: str
    location_id: UUID
    expected_planned_duration_minutes: int
    expected_amount: Decimal
    expected_currency: str
    expected_location_operational_revision: int
    expected_configuration_fingerprint: str
    origin_request_id: UUID | None = None
    allow_subject_override: bool = False


class BookAppointmentHandler(Protocol):
    async def book_appointment(self, command: BookAppointmentCommand) -> Reservation: ...


async def book_appointment(
    handler: BookAppointmentHandler,
    command: BookAppointmentCommand,
) -> Reservation:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.resources:
        raise ValueError("at least one ResourceChoice is required")
    if command.expected_planned_duration_minutes <= 0:
        raise ValueError("booking requires expected planned duration")
    if command.expected_amount < 0:
        raise ValueError("booking requires expected amount")
    if not command.expected_currency:
        raise ValueError("booking requires expected currency")
    if command.expected_location_operational_revision <= 0:
        raise ValueError("booking requires expected Location revision")
    if not command.expected_configuration_fingerprint:
        raise ValueError("booking requires expected configuration fingerprint")
    try:
        return await handler.book_appointment(command)
    except (OfferingVersionNotFound, OfferingVersionNotBookable) as exc:
        raise AppointmentOptionStale("OfferingVersion availability changed") from exc
