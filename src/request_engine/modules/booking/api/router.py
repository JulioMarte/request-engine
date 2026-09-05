from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from request_engine.modules.booking.api.arrival_estimate_routes import add_arrival_estimate_routes
from request_engine.modules.booking.api.dependencies import IdempotencyKey
from request_engine.modules.booking.api.discovery_booking import book_selected_option
from request_engine.modules.booking.api.models import (
    AppointmentSlotView,
    AttendanceResponseBody,
    AttendanceStateView,
    BookAppointmentBody,
    CancelReservationBody,
    RescheduleReservationBody,
    ReservationView,
)
from request_engine.modules.booking.application import errors as booking_errors
from request_engine.modules.booking.application.authority import SUBJECT_OVERRIDE_PERMISSION
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentHandler,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    CancelReservationHandler,
    cancel_reservation,
)
from request_engine.modules.booking.application.commands.record_arrival_estimate import (
    RecordArrivalEstimateHandler,
)
from request_engine.modules.booking.application.commands.record_attendance import (
    RecordAttendanceResponseCommand,
    RecordAttendanceResponseHandler,
    record_attendance_response,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
    RescheduleReservationHandler,
    reschedule_reservation,
)
from request_engine.modules.booking.application.queries import find_appointment_slots
from request_engine.modules.booking.application.queries.get_reservation_status import (
    ReservationReader,
    get_reservation_status,
)
from request_engine.modules.booking.contracts.appointment_options import AppointmentOptionCodec
from request_engine.modules.booking.contracts.discovery import DiscoveryHandoffReader
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_router(
    *,
    availability_reader: find_appointment_slots.AppointmentAvailabilityReader,
    option_codec: AppointmentOptionCodec,
    discovery_handoff_reader: DiscoveryHandoffReader,
    book_handler: BookAppointmentHandler,
    cancel_handler: CancelReservationHandler,
    reschedule_handler: RescheduleReservationHandler,
    attendance_handler: RecordAttendanceResponseHandler,
    arrival_estimate_handler: RecordArrivalEstimateHandler,
    reservation_reader: ReservationReader,
    authority_reader: PartyAuthorityReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/appointments", tags=["appointments"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def slots(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        offering_version_id: UUID,
        window_start: datetime,
        window_end: datetime,
        location_id: UUID | None = None,
        resource_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> tuple[AppointmentSlotView, ...]:
        require_capability(actor, "appointments.find_slots")
        result = await find_appointment_slots.find_appointment_slots(
            availability_reader,
            find_appointment_slots.FindAppointmentSlotsQuery(
                organization_id=actor.organization_id,
                offering_version_id=offering_version_id,
                window_start=window_start,
                window_end=window_end,
                location_id=location_id,
                resource_id=resource_id,
                limit=limit,
            ),
        )
        return tuple(
            AppointmentSlotView.from_contract(
                item,
                option_id=option_codec.issue(actor.organization_id, item),
            )
            for item in result
        )

    async def book(
        body: BookAppointmentBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ReservationView:
        require_capability(actor, "appointments.book")
        reservation = await book_selected_option(
            body=body,
            actor=actor,
            idempotency_key=idempotency_key,
            option_codec=option_codec,
            handoff_reader=discovery_handoff_reader,
            handler=book_handler,
        )
        return ReservationView.from_contract(reservation)

    async def reservation_status(
        reservation_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> ReservationView:
        require_capability(actor, "appointments.read")
        reservation = await get_reservation_status(
            reservation_reader,
            authority_reader,
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            reservation_id=reservation_id,
            allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
        )
        if reservation is None:
            raise booking_errors.ReservationNotFound(reservation_id)
        return ReservationView.from_contract(reservation)

    async def cancel(
        reservation_id: UUID,
        body: CancelReservationBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ReservationView:
        require_capability(actor, "appointments.cancel")
        reservation = await cancel_reservation(
            cancel_handler,
            CancelReservationCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                reason=body.reason,
                idempotency_key=idempotency_key,
                expected_revision=body.expected_revision,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return ReservationView.from_contract(reservation)

    async def reschedule(
        reservation_id: UUID,
        body: RescheduleReservationBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ReservationView:
        require_capability(actor, "appointments.reschedule")
        option = option_codec.decode(actor.organization_id, body.option_id)
        if not option.is_contextual:
            raise booking_errors.InvalidResourceSelection(
                "reschedule requires a contextual appointment option"
            )
        if (
            option.location_id is None
            or option.planned_duration_minutes is None
            or option.amount is None
            or option.currency is None
            or option.location_operational_revision is None
            or option.configuration_fingerprint is None
        ):
            raise booking_errors.InvalidResourceSelection(
                "reschedule option is missing contextual provenance"
            )
        reservation = await reschedule_reservation(
            reschedule_handler,
            RescheduleReservationCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                start_at=option.start_at,
                resources=option.resources,
                location_id=option.location_id,
                expected_planned_duration_minutes=option.planned_duration_minutes,
                expected_amount=option.amount,
                expected_currency=option.currency,
                expected_location_operational_revision=option.location_operational_revision,
                expected_configuration_fingerprint=option.configuration_fingerprint,
                idempotency_key=idempotency_key,
                expected_revision=body.expected_revision,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return ReservationView.from_contract(reservation)

    async def attendance_response(
        reservation_id: UUID,
        body: AttendanceResponseBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> AttendanceStateView:
        require_capability(actor, "appointments.confirm_attendance")
        attendance = await record_attendance_response(
            attendance_handler,
            RecordAttendanceResponseCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                response=body.response,
                source_key="http",
                idempotency_key=idempotency_key,
                expected_revision=body.expected_revision,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return AttendanceStateView.from_contract(attendance)

    add_capability_route(
        router,
        "/slots",
        slots,
        capability="appointments.find_slots",
        methods=["GET"],
        response_model=tuple[AppointmentSlotView, ...],
        response_model_exclude_none=True,
    )
    add_capability_route(
        router,
        "",
        book,
        capability="appointments.book",
        methods=["POST"],
        response_model=ReservationView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{reservation_id}",
        reservation_status,
        capability="appointments.read",
        methods=["GET"],
        response_model=ReservationView,
    )
    add_capability_route(
        router,
        "/{reservation_id}/cancel",
        cancel,
        capability="appointments.cancel",
        methods=["POST"],
        response_model=ReservationView,
    )
    add_capability_route(
        router,
        "/{reservation_id}/reschedule",
        reschedule,
        capability="appointments.reschedule",
        methods=["POST"],
        response_model=ReservationView,
    )
    add_capability_route(
        router,
        "/{reservation_id}/attendance",
        attendance_response,
        capability="appointments.confirm_attendance",
        methods=["POST"],
        response_model=AttendanceStateView,
    )
    add_arrival_estimate_routes(router, arrival_estimate_handler, actor_resolver)
    return router
