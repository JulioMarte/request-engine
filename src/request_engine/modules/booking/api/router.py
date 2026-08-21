from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from request_engine.modules.booking.api.models import (
    AppointmentSlotView,
    AttendanceResponseBody,
    AttendanceStateView,
    BookAppointmentBody,
    CancelReservationBody,
    RescheduleReservationBody,
    ReservationView,
)
from request_engine.modules.booking.application.authority import SUBJECT_OVERRIDE_PERMISSION
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    BookAppointmentHandler,
    book_appointment,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    CancelReservationHandler,
    cancel_reservation,
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
from request_engine.modules.booking.application.errors import (
    ContextualCommitmentUnsupported,
    ReservationNotFound,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    AppointmentAvailabilityReader,
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.application.queries.get_reservation_status import (
    ReservationReader,
    get_reservation_status,
)
from request_engine.modules.booking.contracts.appointment_options import AppointmentOptionCodec
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_router(
    *,
    availability_reader: AppointmentAvailabilityReader,
    option_codec: AppointmentOptionCodec,
    book_handler: BookAppointmentHandler,
    cancel_handler: CancelReservationHandler,
    reschedule_handler: RescheduleReservationHandler,
    attendance_handler: RecordAttendanceResponseHandler,
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
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> tuple[AppointmentSlotView, ...]:
        require_capability(actor, "appointments.find_slots")
        result = await find_appointment_slots(
            availability_reader,
            FindAppointmentSlotsQuery(
                organization_id=actor.organization_id,
                offering_version_id=offering_version_id,
                window_start=window_start,
                window_end=window_end,
                location_id=location_id,
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
        option = option_codec.decode(actor.organization_id, body.option_id)
        reservation = await book_appointment(
            book_handler,
            BookAppointmentCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                offering_version_id=option.offering_version_id,
                subject_party_id=body.subject_party_id,
                start_at=option.start_at,
                resources=option.resources,
                location_id=option.location_id,
                origin_request_id=body.origin_request_id,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
                expected_planned_duration_minutes=option.planned_duration_minutes,
                expected_amount=option.amount,
                expected_currency=option.currency,
                expected_location_operational_revision=option.location_operational_revision,
                expected_configuration_fingerprint=option.configuration_fingerprint,
            ),
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
            raise ReservationNotFound(reservation_id)
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
        if option.is_contextual:
            raise ContextualCommitmentUnsupported("reschedule")
        reservation = await reschedule_reservation(
            reschedule_handler,
            RescheduleReservationCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                start_at=option.start_at,
                resources=option.resources,
                location_id=option.location_id,
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
        # F1 enriches contextual options with price/duration. Legacy V3 options
        # deliberately leave those fields unset; omitting None preserves the
        # released V3 JSON shape while still exposing real F1 observations.
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
    return router