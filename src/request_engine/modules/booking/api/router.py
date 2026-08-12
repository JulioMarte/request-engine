from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

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
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    AppointmentAvailabilityReader,
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.application.queries.get_reservation_status import (
    ReservationReader,
    get_reservation_status,
)
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, AuthenticationRequired

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
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/appointments", tags=["appointments"])

    async def authenticated_actor(request: Request) -> ActorContext:
        try:
            return await actor_resolver.resolve_actor(request)
        except AuthenticationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            ) from exc

    async def slots(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        offering_version_id: UUID,
        window_start: datetime,
        window_end: datetime,
        location_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> tuple[AppointmentSlotView, ...]:
        _require(actor, "appointments.find_slots")
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
        return tuple(AppointmentSlotView.from_contract(item) for item in result)

    async def book(
        body: BookAppointmentBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ReservationView:
        _require(actor, "appointments.book")
        reservation = await book_appointment(
            book_handler,
            BookAppointmentCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                offering_version_id=body.offering_version_id,
                subject_party_id=body.subject_party_id,
                start_at=body.start_at,
                resources=tuple(item.to_contract() for item in body.resources),
                location_id=body.location_id,
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
        _require(actor, "appointments.read")
        reservation = await get_reservation_status(
            reservation_reader,
            authority_reader,
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
            reservation_id=reservation_id,
            allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
        )
        if reservation is None:
            raise HTTPException(status_code=404, detail="Reservation not found")
        return ReservationView.from_contract(reservation)

    async def cancel(
        reservation_id: UUID,
        body: CancelReservationBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> ReservationView:
        _require(actor, "appointments.cancel")
        reservation = await cancel_reservation(
            cancel_handler,
            CancelReservationCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                reason=body.reason,
                idempotency_key=idempotency_key,
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
        _require(actor, "appointments.reschedule")
        reservation = await reschedule_reservation(
            reschedule_handler,
            RescheduleReservationCommand(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                reservation_id=reservation_id,
                start_at=body.start_at,
                resources=tuple(item.to_contract() for item in body.resources),
                location_id=body.location_id,
                idempotency_key=idempotency_key,
                allow_subject_override=actor.allows(SUBJECT_OVERRIDE_PERMISSION),
            ),
        )
        return ReservationView.from_contract(reservation)

    router.add_api_route(
        "/slots",
        slots,
        methods=["GET"],
        response_model=tuple[AppointmentSlotView, ...],
    )
    router.add_api_route(
        "",
        book,
        methods=["POST"],
        response_model=ReservationView,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/{reservation_id}",
        reservation_status,
        methods=["GET"],
        response_model=ReservationView,
    )
    router.add_api_route(
        "/{reservation_id}/cancel",
        cancel,
        methods=["POST"],
        response_model=ReservationView,
    )
    router.add_api_route(
        "/{reservation_id}/reschedule",
        reschedule,
        methods=["POST"],
        response_model=ReservationView,
    )
    return router


def _require(actor: ActorContext, capability: str) -> None:
    if not actor.allows(capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"capability {capability!r} is required",
        )
