from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
)
from request_engine.modules.booking.application.errors import ContextualCommitmentUnsupported
from request_engine.modules.booking.contracts.appointments import ResourceChoice


def _contextual_choice() -> ResourceChoice:
    return ResourceChoice(
        requirement_id=uuid4(),
        resource_id=uuid4(),
        resource_location_assignment_id=uuid4(),
        assignment_revision=1,
        availability_revision=1,
    )


def _handler() -> CapacitySafeBookingCommitmentCommands:
    session_factory = async_sessionmaker(
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return CapacitySafeBookingCommitmentCommands(session_factory)


@pytest.mark.asyncio
async def test_contextual_hold_fails_closed_before_legacy_commitment_adapter() -> None:
    handler = _handler()
    now = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)

    with pytest.raises(ContextualCommitmentUnsupported, match="capacity hold"):
        await handler.acquire_capacity_hold(
            AcquireCapacityHoldCommand(
                organization_id=uuid4(),
                principal_id=uuid4(),
                offering_version_id=uuid4(),
                subject_party_id=uuid4(),
                start_at=now,
                expires_at=datetime(2026, 8, 21, 14, 15, tzinfo=UTC),
                resources=(_contextual_choice(),),
                idempotency_key="contextual-hold-fail-closed",
                location_id=uuid4(),
            )
        )


@pytest.mark.asyncio
async def test_contextual_reschedule_fails_closed_before_legacy_commitment_adapter() -> None:
    handler = _handler()

    with pytest.raises(ContextualCommitmentUnsupported, match="reschedule"):
        await handler.reschedule_reservation(
            RescheduleReservationCommand(
                organization_id=uuid4(),
                principal_id=uuid4(),
                reservation_id=uuid4(),
                start_at=datetime(2026, 8, 21, 14, 0, tzinfo=UTC),
                resources=(_contextual_choice(),),
                idempotency_key="contextual-reschedule-fail-closed",
                expected_revision=1,
                location_id=uuid4(),
            )
        )
