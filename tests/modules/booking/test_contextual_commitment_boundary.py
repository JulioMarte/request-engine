from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
    acquire_capacity_hold,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
    reschedule_reservation,
)
from request_engine.modules.booking.application.errors import InvalidResourceSelection
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.platform.db.session import SessionFactory


def _handler() -> CapacitySafeBookingCommitmentCommands:
    # Contextual requests are rejected before the legacy delegate can touch DB.
    return CapacitySafeBookingCommitmentCommands(cast(SessionFactory, object()))


def _contextual_choice() -> tuple[ResourceChoice, ...]:
    return (
        ResourceChoice(
            requirement_id=uuid4(),
            resource_id=uuid4(),
            resource_location_assignment_id=uuid4(),
            assignment_revision=1,
            availability_revision=1,
        ),
    )


@pytest.mark.asyncio
async def test_contextual_capacity_hold_is_rejected_before_legacy_adapter() -> None:
    now = datetime.now(UTC)
    with pytest.raises(InvalidResourceSelection, match="CapacityHold"):
        await acquire_capacity_hold(
            _handler(),
            AcquireCapacityHoldCommand(
                organization_id=uuid4(),
                principal_id=uuid4(),
                offering_version_id=uuid4(),
                subject_party_id=uuid4(),
                start_at=now + timedelta(days=1),
                expires_at=now + timedelta(minutes=10),
                resources=_contextual_choice(),
                idempotency_key="contextual-hold",
                location_id=uuid4(),
                allow_subject_override=True,
            ),
        )


@pytest.mark.asyncio
async def test_contextual_reschedule_is_rejected_before_legacy_adapter() -> None:
    with pytest.raises(InvalidResourceSelection, match="reschedule"):
        await reschedule_reservation(
            _handler(),
            RescheduleReservationCommand(
                organization_id=uuid4(),
                principal_id=uuid4(),
                reservation_id=uuid4(),
                start_at=datetime.now(UTC) + timedelta(days=1),
                resources=_contextual_choice(),
                idempotency_key="contextual-reschedule",
                expected_revision=1,
                location_id=uuid4(),
                allow_subject_override=True,
            ),
        )
