from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.errors import AppointmentOptionStale, OfferingVersionNotBookable
from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice


class _NotBookableHandler:
    async def book_appointment(self, command: BookAppointmentCommand) -> Reservation:
        raise OfferingVersionNotBookable(command.offering_version_id)


def _contextual_command(offering_version_id: UUID) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        offering_version_id=offering_version_id,
        subject_party_id=uuid4(),
        start_at=datetime.now(UTC),
        resources=(
            ResourceChoice(
                requirement_id=uuid4(),
                resource_id=uuid4(),
                resource_location_assignment_id=uuid4(),
                assignment_revision=1,
                availability_revision=1,
            ),
        ),
        idempotency_key=f"contextual-error-classification-{uuid4().hex}",
        location_id=uuid4(),
        expected_planned_duration_minutes=30,
        expected_amount=Decimal("3500"),
        expected_currency="DOP",
        expected_location_operational_revision=1,
        expected_configuration_fingerprint="observed-context",
    )


@pytest.mark.asyncio
async def test_bookable_change_is_classified_as_stale() -> None:
    with pytest.raises(AppointmentOptionStale):
        await book_appointment(_NotBookableHandler(), _contextual_command(uuid4()))
