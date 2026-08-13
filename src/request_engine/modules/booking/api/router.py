from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status

from request_engine.modules.booking.api.models import (
    AppointmentSlotView,
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
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
    RescheduleReservationHandler,
    reschedule_reservation,
)
from request_engine.modules.booking.application.errors import ReservationNotFound
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
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def create_router(
    *,
    availability_reader: AppointmentAvailabilityReader,
    book_handler: BookAppointmentHandler,
    cancel_handler: CancelReservationHandler,
    reschedule_handler: RescheduleReservationHandler,
    reservation_reader: ReservationReader,
    authority_reader: PartyAuthorityReader,
    option_codec: AppointmentOptionCodec,
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
                option_offering_version_id=option.offering_version_id,
            ),
        )
        return ReservationView.from_contract(reservation)

    router.add_api_route("/slots", slots, methods=["GET"], response_model=tuple[AppointmentSlotView, ...])
    router.add_api_route("", book, methods=["POST"], response_model=ReservationView, status_code=status.HTTP_201_CREATED)
    router.add_api_route("/{reservation_id}", reservation_status, methods=["GET"], response_model=ReservationView)
    router.add_api_route("/{reservation_id}/cancel", cancel, methods=["POST"], response_model=ReservationView)
    router.add_api_route("/{reservation_id}/reschedule", reschedule, methods=["POST"], response_model=ReservationView)
    return router
