from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute

from request_engine.modules.booking.adapters.appointment_options import (
    SignedAppointmentOptionCodec,
)
from request_engine.modules.booking.api.models import RescheduleReservationBody, ReservationView
from request_engine.modules.booking.api.router import create_router
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
)
from request_engine.modules.booking.application.errors import InvalidResourceSelection
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
            end_at=command.start_at + timedelta(minutes=30),
            status=ReservationStatus.CONFIRMED,
            revision=command.expected_revision + 1,
        )


def _codec() -> SignedAppointmentOptionCodec:
    return SignedAppointmentOptionCodec(
        b"request-engine-contextual-reschedule-router-test-key",
        ttl=timedelta(minutes=10),
        now=lambda: _NOW,
    )


def _actor(organization_id: UUID) -> ActorContext:
    return ActorContext(
        organization_id=organization_id,
        principal_id=uuid4(),
        capabilities=frozenset({"appointments.reschedule"}),
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
    routes = [item for item in router.routes if isinstance(item, APIRoute)]
    route = next(item for item in routes if item.operation_id == "appointments_reschedule")
    return cast(Callable[..., Awaitable[ReservationView]], route.endpoint)


def _noncontextual_slot() -> AppointmentSlot:
    return AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=30),
        location_id=uuid4(),
        resources=(ResourceChoice(uuid4(), uuid4()),),
    )


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
        configuration_fingerprint="sha256:contextual-reschedule-router",
    )


@pytest.mark.asyncio
async def test_contextual_reschedule_routes_full_provenance_to_current_handler() -> None:
    organization_id = uuid4()
    codec = _codec()
    handler = _RecordingRescheduleHandler()
    endpoint = _reschedule_endpoint(codec, handler)
    slot = _contextual_slot()
    token = codec.issue(organization_id, slot)
    assert token.startswith("aptopt_v2.")
    reservation_id = uuid4()

    result = await endpoint(
        reservation_id=reservation_id,
        body=RescheduleReservationBody(option_id=token, expected_revision=7),
        actor=_actor(organization_id),
        idempotency_key="contextual-reschedule-router",
    )

    assert result.id == reservation_id
    assert result.start_at == slot.start_at
    assert result.location_id == slot.location_id
    assert len(handler.commands) == 1
    command = handler.commands[0]
    assert command.start_at == slot.start_at
    assert command.resources == slot.resources
    assert command.location_id == slot.location_id
    assert command.expected_planned_duration_minutes == slot.planned_duration_minutes
    assert command.expected_amount == slot.amount
    assert command.expected_currency == slot.currency
    assert command.expected_location_operational_revision == slot.location_operational_revision
    assert command.expected_configuration_fingerprint == slot.configuration_fingerprint
    assert command.expected_revision == 7


@pytest.mark.asyncio
async def test_noncontextual_reschedule_option_fails_closed_without_mutation() -> None:
    organization_id = uuid4()
    codec = _codec()
    handler = _RecordingRescheduleHandler()
    endpoint = _reschedule_endpoint(codec, handler)
    token = codec.issue(organization_id, _noncontextual_slot())
    assert token.startswith("aptopt_v1.")

    with pytest.raises(
        InvalidResourceSelection,
        match="reschedule requires a contextual appointment option",
    ):
        await endpoint(
            reservation_id=uuid4(),
            body=RescheduleReservationBody(option_id=token, expected_revision=1),
            actor=_actor(organization_id),
            idempotency_key="noncontextual-reschedule-router",
        )

    assert handler.commands == []
