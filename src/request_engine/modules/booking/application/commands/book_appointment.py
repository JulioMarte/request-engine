from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

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
    return await handler.book_appointment(command)
