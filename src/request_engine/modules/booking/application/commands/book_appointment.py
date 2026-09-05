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
    location_id: UUID | None = None
    origin_request_id: UUID | None = None
    allow_subject_override: bool = False
    expected_planned_duration_minutes: int | None = None
    expected_amount: Decimal | None = None
    expected_currency: str | None = None
    expected_location_operational_revision: int | None = None
    expected_configuration_fingerprint: str | None = None

    @property
    def is_contextual(self) -> bool:
        return self.expected_configuration_fingerprint is not None


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
    if command.is_contextual:
        if command.location_id is None:
            raise ValueError("contextual booking requires location_id")
        if (
            command.expected_planned_duration_minutes is None
            or command.expected_planned_duration_minutes <= 0
        ):
            raise ValueError("contextual booking requires expected planned duration")
        if command.expected_amount is None or command.expected_amount < 0:
            raise ValueError("contextual booking requires expected amount")
        if command.expected_currency is None:
            raise ValueError("contextual booking requires expected currency")
        if (
            command.expected_location_operational_revision is None
            or command.expected_location_operational_revision <= 0
        ):
            raise ValueError("contextual booking requires expected Location revision")
    try:
        return await handler.book_appointment(command)
    except (OfferingVersionNotFound, OfferingVersionNotBookable) as exc:
        if not command.is_contextual:
            raise
        raise AppointmentOptionStale("OfferingVersion availability changed") from exc
