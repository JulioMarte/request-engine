from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute

from request_engine.modules.booking.adapters.appointment_options import (
    SignedAppointmentOptionCodec,
)
from request_engine.modules.booking.api.models import ReservationView, RescheduleReservationBody
from request_engine.modules.booking.api.router import create_router
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
)
from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    Reservation,
    ReservationStatus,
    ResourceChoice,
)
from request_engine.platform.security.context import ActorContext

_NOW = datetime(2030, 1, 7, 12, 0, tzinfo=UTC)


class _RecordingRescheduleHandler:
    def __init__(self) -> None:
        self.commands: list[RescheduleReservationCommand] = []

    async def reschedule_reservation(
        self,
        command: RescheduleReservationCommand,
    ) -> Reservation:
        self.commands.append(command)
        return Reservation(
            id=command.reservation_id,
            offering_version_id=uuid4(),
            subject_party_id=uuid4(),
            location_id=command.location_id,
            start_at=command.start_at,
            end_at=command.start_at + timedelta(minutes=45),
            status=ReservationStatus.CONFIRMED,
            revision=command.expected_revision + 1,
        )


def _reschedule_endpoint(
    codec: SignedAppointmentOptionCodec,
    handler: _RecordingRescheduleHandler,
) -> Callable[..., Awaitable[ReservationView]]:
    unused: Any = object()
    router = create_router(
        availability_reader=unused,
        option_codec=codec,
        discovery_handoff_reader=unused,
        book_handler=unused,
        cancel_handler=unused,
        reschedule_handler=handler,
        attendance_handler=unused,
        arrival_estimate_handler=unused,
        reservation_reader=unused,
        authority_reader=unused,
        actor_resolver=unused,
    )
    route = next(
        item
        for item in router.routes
        if isinstance(item, APIRoute) and item.operation_id == "appointments_reschedule"
    )
    return cast(Callable[..., Awaitable[ReservationView]], route.endpoint)


def _contextual_slot() -> AppointmentSlot:
    return AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=2),
        end_at=_NOW + timedelta(hours=2, minutes=45),
        location_id=uuid4(),
        resources=(
            ResourceChoice(
                requirement_id=uuid4(),
                resource_id=uuid4(),
                resource_location_assignment_id=uuid4(),
                assignment_revision=2,
                availability_revision=4,
            ),
        ),
        planned_duration_minutes=45,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=3,
        configuration_fingerprint="sha256:pilot-readiness-contextual-reschedule",
    )


@pytest.mark.asyncio
@pytest.mark.adversarial
@pytest.mark.contract
async def test_public_reschedule_accepts_contextual_appointment_option() -> None:
    """A normal consumer must not need a second recovery-only path to move contextual bookings."""
    organization_id = uuid4()
    codec = SignedAppointmentOptionCodec(
        b"request-engine-pilot-readiness-contextual-reschedule-key",
        ttl=timedelta(minutes=10),
        now=lambda: _NOW,
    )
    handler = _RecordingRescheduleHandler()
    endpoint = _reschedule_endpoint(codec, handler)
    slot = _contextual_slot()
    token = codec.issue(organization_id, slot)
    reservation_id = uuid4()

    result = await endpoint(
        reservation_id=reservation_id,
        body=RescheduleReservationBody(option_id=token, expected_revision=3),
        actor=ActorContext(
            organization_id=organization_id,
            principal_id=uuid4(),
            capabilities=frozenset({"appointments.reschedule"}),
        ),
        idempotency_key="pilot-readiness-contextual-reschedule",
    )

    assert result.id == reservation_id
    assert len(handler.commands) == 1
    command = handler.commands[0]
    assert command.start_at == slot.start_at
    assert command.location_id == slot.location_id
    assert command.resources == slot.resources
