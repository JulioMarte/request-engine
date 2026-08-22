from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from request_engine.modules.booking.application.commands import (
    configure_booking_context_terms as configure_command,
)
from request_engine.modules.booking.application.commands import (
    supersede_booking_context_terms as supersede_command,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


class ContextTermsBody(BaseModel):
    authority_party_id: UUID
    resource_location_assignment_id: UUID
    offering_version_id: UUID
    effective_from: datetime
    effective_until: datetime | None = None
    amount: Decimal | None = None
    currency: str | None = None
    planned_duration_minutes: int | None = None
    bookable: bool = True


class SupersedeTermsBody(BaseModel):
    authority_party_id: UUID
    expected_current_revision: int
    effective_from: datetime
    amount: Decimal | None = None
    currency: str | None = None
    planned_duration_minutes: int | None = None
    bookable: bool = True


def create_operational_terms_router(
    *,
    configure_handler: configure_command.ConfigureBookingContextTermsHandler,
    supersede_handler: supersede_command.SupersedeBookingContextTermsHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/context-terms", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    @router.post("")
    async def configure(
        body: ContextTermsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        command = configure_command.ConfigureBookingContextTermsCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            resource_location_assignment_id=body.resource_location_assignment_id,
            offering_version_id=body.offering_version_id,
            effective_from=body.effective_from,
            effective_until=body.effective_until,
            amount=body.amount,
            currency=body.currency,
            planned_duration_minutes=body.planned_duration_minutes,
            bookable=body.bookable,
            idempotency_key=key,
        )
        return await configure_command.configure_booking_context_terms(
            configure_handler,
            command,
        )

    @router.post("/{current_context_terms_id}/supersede")
    async def supersede(
        current_context_terms_id: UUID,
        body: SupersedeTermsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        command = supersede_command.SupersedeBookingContextTermsCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            current_context_terms_id=current_context_terms_id,
            expected_current_revision=body.expected_current_revision,
            effective_from=body.effective_from,
            amount=body.amount,
            currency=body.currency,
            planned_duration_minutes=body.planned_duration_minutes,
            bookable=body.bookable,
            idempotency_key=key,
        )
        return await supersede_command.supersede_booking_context_terms(
            supersede_handler,
            command,
        )

    return router
