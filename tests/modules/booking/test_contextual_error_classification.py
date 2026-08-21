from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status

from request_engine.modules.booking.api.errors import _booking_error
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.errors import (
    AppointmentOptionStale,
    ContextualCommitmentUnsupported,
    OfferingVersionNotBookable,
)
from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice


class _NotBookableHandler:
    async def book_appointment(self, command: BookAppointmentCommand) -> Reservation:
        raise OfferingVersionNotBookable(command.offering_version_id)


def _choice() -> tuple[ResourceChoice, ...]:
    return (
        ResourceChoice(
            requirement_id=uuid4(),
            resource_id=uuid4(),
            availability_revision=1,
        ),
    )


def _base_command(offering_version_id: UUID) -> dict[str, object]:
    return {
        "organization_id": uuid4(),
        "principal_id": uuid4(),
        "offering_version_id": offering_version_id,
        "subject_party_id": uuid4(),
        "start_at": datetime.now(UTC),
        "resources": _choice(),
        "idempotency_key": f"error-classification-{uuid4().hex}",
    }


@pytest.mark.asyncio
async def test_contextual_bookable_change_is_classified_as_stale() -> None:
    offering_version_id = uuid4()
    command = BookAppointmentCommand(
        **_base_command(offering_version_id),
        location_id=uuid4(),
        expected_planned_duration_minutes=30,
        expected_amount=Decimal("3500"),
        expected_currency="DOP",
        expected_location_operational_revision=1,
        expected_configuration_fingerprint="observed-context",
    )

    with pytest.raises(AppointmentOptionStale):
        await book_appointment(_NotBookableHandler(), command)


@pytest.mark.asyncio
async def test_legacy_bookable_change_preserves_released_error() -> None:
    offering_version_id = uuid4()
    command = BookAppointmentCommand(**_base_command(offering_version_id))

    with pytest.raises(OfferingVersionNotBookable):
        await book_appointment(_NotBookableHandler(), command)


def test_contextual_commitment_unsupported_has_machine_readable_http_error() -> None:
    status_code, body = _booking_error(ContextualCommitmentUnsupported("reschedule"))

    assert status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert body.code == "contextual_commitment_unsupported"
    assert body.details == {"operation": "reschedule"}
