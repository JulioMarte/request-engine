from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice


@dataclass(frozen=True, slots=True)
class RescheduleReservationCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    start_at: datetime
    resources: tuple[ResourceChoice, ...]
    idempotency_key: str
    expected_revision: int
    location_id: UUID
    expected_planned_duration_minutes: int
    expected_amount: Decimal
    expected_currency: str
    expected_location_operational_revision: int
    expected_configuration_fingerprint: str
    allow_subject_override: bool = False


class RescheduleReservationHandler(Protocol):
    async def reschedule_reservation(
        self, command: RescheduleReservationCommand
    ) -> Reservation: ...


async def reschedule_reservation(
    handler: RescheduleReservationHandler,
    command: RescheduleReservationCommand,
) -> Reservation:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.resources:
        raise ValueError("at least one ResourceChoice is required")
    if command.expected_planned_duration_minutes <= 0:
        raise ValueError("expected_planned_duration_minutes must be positive")
    if command.expected_amount < 0:
        raise ValueError("expected_amount must be non-negative")
    if not command.expected_currency:
        raise ValueError("expected_currency is required")
    if command.expected_location_operational_revision <= 0:
        raise ValueError("expected_location_operational_revision must be positive")
    if not command.expected_configuration_fingerprint:
        raise ValueError("expected_configuration_fingerprint is required")
    if any(
        choice.resource_location_assignment_id is None
        or choice.assignment_revision is None
        or choice.availability_revision is None
        for choice in command.resources
    ):
        raise ValueError("reschedule ResourceChoices require contextual provenance")
    return await handler.reschedule_reservation(command)
