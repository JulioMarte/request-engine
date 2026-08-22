from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from request_engine.modules.catalog.application.commands import (
    configure_offering_version_booking_terms as base_terms_command,
)
from request_engine.modules.catalog.application.commands.set_location_hours_exception import (
    SetLocationHoursExceptionCommand,
    SetLocationHoursExceptionHandler,
    set_location_hours_exception,
)
from request_engine.modules.catalog.application.commands.set_location_operational_hours import (
    LocationOperationalHoursInput,
    SetLocationOperationalHoursCommand,
    SetLocationOperationalHoursHandler,
    set_location_operational_hours,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class HoursWindowBody(BaseModel):
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


class HoursBody(BaseModel):
    authority_party_id: UUID
    expected_operational_revision: int
    windows: tuple[HoursWindowBody, ...]


class HoursExceptionBody(BaseModel):
    authority_party_id: UUID
    expected_operational_revision: int
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    exception_id: UUID | None = None
    reason: str | None = None
    active: bool = True


class BaseTermsBody(BaseModel):
    authority_party_id: UUID
    amount: Decimal
    currency: str


def create_operational_schedule_router(
    *,
    hours_handler: SetLocationOperationalHoursHandler,
    exception_handler: SetLocationHoursExceptionHandler,
    terms_handler: base_terms_command.ConfigureOfferingVersionBookingTermsHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def hours(
        location_id: UUID,
        body: HoursBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        windows = tuple(LocationOperationalHoursInput(**item.model_dump()) for item in body.windows)
        return await set_location_operational_hours(
            hours_handler,
            SetLocationOperationalHoursCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                location_id=location_id,
                expected_operational_revision=body.expected_operational_revision,
                windows=windows,
                idempotency_key=key,
            ),
        )

    async def exception(
        location_id: UUID,
        body: HoursExceptionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await set_location_hours_exception(
            exception_handler,
            SetLocationHoursExceptionCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                location_id=location_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    async def base_terms(
        offering_version_id: UUID,
        body: BaseTermsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        command = base_terms_command.ConfigureOfferingVersionBookingTermsCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            offering_version_id=offering_version_id,
            amount=body.amount,
            currency=body.currency,
            idempotency_key=key,
        )
        return await base_terms_command.configure_offering_version_booking_terms(
            terms_handler,
            command,
        )

    router.add_api_route("/locations/{location_id}/hours", hours, methods=["PUT"])
    router.add_api_route("/locations/{location_id}/hours-exceptions", exception, methods=["PUT"])
    router.add_api_route(
        "/offering-versions/{offering_version_id}/booking-terms", base_terms, methods=["PUT"]
    )
    return router
