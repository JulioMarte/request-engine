from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel

from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    ConfigureBookingContextTermsCommand,
    ConfigureBookingContextTermsHandler,
    configure_booking_context_terms,
)
from request_engine.modules.booking.application.commands.supersede_booking_context_terms import (
    SupersedeBookingContextTermsCommand,
    SupersedeBookingContextTermsHandler,
    supersede_booking_context_terms,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=250)]


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
    configure_handler: ConfigureBookingContextTermsHandler,
    supersede_handler: SupersedeBookingContextTermsHandler,
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
        return await configure_booking_context_terms(
            configure_handler,
            ConfigureBookingContextTermsCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    @router.post("/{current_context_terms_id}/supersede")
    async def supersede(
        current_context_terms_id: UUID,
        body: SupersedeTermsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> object:
        return await supersede_booking_context_terms(
            supersede_handler,
            SupersedeBookingContextTermsCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                current_context_terms_id=current_context_terms_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )

    return router
