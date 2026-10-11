from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from request_engine.modules.booking.api.configuration_models import BookingContextTermsView
from request_engine.modules.booking.application.commands import (
    configure_booking_context_terms as configure_command,
)
from request_engine.modules.booking.application.commands import (
    supersede_booking_context_terms as supersede_command,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.http.exact_decimal import admit_exact_decimal
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]
ContextTermsAmount = Annotated[
    Decimal,
    Field(ge=0, max_digits=20, decimal_places=6),
    BeforeValidator(admit_exact_decimal, json_schema_input_type=str | int),
]


class ContextTermsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    authority_party_id: UUID
    resource_location_assignment_id: UUID
    offering_version_id: UUID
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None = None
    amount: ContextTermsAmount | None = Field(
        default=None,
        description="Exact nonnegative decimal string (recommended) or JSON integer; "
        "at most 14 integer digits and 6 significant fractional digits. "
        "Fractional JSON numbers, including 1.0, are rejected. Null means no price override.",
        examples=["19.90", 19, None],
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    planned_duration_minutes: int | None = Field(default=None, gt=0)
    bookable: bool = True

    @field_validator("amount")
    @classmethod
    def exact_storage_amount(cls, value: Decimal | None) -> Decimal | None:
        configure_command.validate_context_terms_amount(value)
        return value

    @model_validator(mode="after")
    def terms_contract(self) -> Self:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be present together")
        if self.amount is None and self.planned_duration_minutes is None and self.bookable:
            raise ValueError("bookable context terms require a material override")
        return self


class SupersedeTermsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    authority_party_id: UUID
    expected_current_revision: int = Field(gt=0)
    effective_from: AwareDatetime
    amount: ContextTermsAmount | None = Field(
        default=None,
        description="Exact nonnegative decimal string (recommended) or JSON integer; "
        "at most 14 integer digits and 6 significant fractional digits. "
        "Fractional JSON numbers, including 1.0, are rejected. Null means no price override.",
        examples=["19.90", 19, None],
    )
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    planned_duration_minutes: int | None = Field(default=None, gt=0)
    bookable: bool = True

    @field_validator("amount")
    @classmethod
    def exact_storage_amount(cls, value: Decimal | None) -> Decimal | None:
        configure_command.validate_context_terms_amount(value)
        return value

    @model_validator(mode="after")
    def terms_contract(self) -> Self:
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be present together")
        if self.amount is None and self.planned_duration_minutes is None and self.bookable:
            raise ValueError("bookable context terms require a material override")
        return self


def create_operational_terms_router(
    *,
    configure_handler: configure_command.ConfigureBookingContextTermsHandler,
    supersede_handler: supersede_command.SupersedeBookingContextTermsHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations/context-terms", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def configure(
        body: ContextTermsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> BookingContextTermsView:
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
        result = await configure_command.configure_booking_context_terms(
            configure_handler,
            command,
        )
        return BookingContextTermsView.model_validate(result)

    async def supersede(
        current_context_terms_id: UUID,
        body: SupersedeTermsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> BookingContextTermsView:
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
        result = await supersede_command.supersede_booking_context_terms(
            supersede_handler,
            command,
        )
        return BookingContextTermsView.model_validate(result)

    add_capability_route(
        router,
        "",
        configure,
        methods=["POST"],
        capability="catalog.manage",
        operation_id="booking_context_terms_configure",
        owner="booking",
        response_model=BookingContextTermsView,
        responses={422: {"model": ErrorEnvelope, "description": "Invalid contextual terms input"}},
    )
    add_capability_route(
        router,
        "/{current_context_terms_id}/supersede",
        supersede,
        methods=["POST"],
        capability="catalog.manage",
        operation_id="booking_context_terms_supersede",
        owner="booking",
        response_model=BookingContextTermsView,
        responses={422: {"model": ErrorEnvelope, "description": "Invalid contextual terms input"}},
    )
    return router
