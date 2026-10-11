from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from request_engine.modules.catalog.api.operational_views import (
    DeclaredOrganizationHolidaysView,
    LocationHoursExceptionView,
    LocationOperationalHoursView,
    OfferingVersionBookingTermsView,
)
from request_engine.modules.catalog.application.commands import (
    configure_offering_version_booking_terms as base_terms_command,
)
from request_engine.modules.catalog.application.commands.declare_organization_holidays import (
    DeclareOrganizationHolidaysCommand,
    DeclareOrganizationHolidaysHandler,
    OrganizationHolidayInput,
    declare_organization_holidays,
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
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.http.exact_decimal import admit_exact_decimal
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]
BaseTermsAmount = Annotated[
    Decimal,
    Field(ge=0, max_digits=20, decimal_places=6),
    BeforeValidator(admit_exact_decimal, json_schema_input_type=str | int),
]


class HoursWindowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekday: int = Field(ge=0, le=6)
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode="after")
    def local_window(self) -> Self:
        if self.local_start.tzinfo is not None or self.local_end.tzinfo is not None:
            raise ValueError("hours require local wall-clock time without an offset")
        if self.local_start >= self.local_end:
            raise ValueError("local_start must be before local_end")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until cannot be before valid_from")
        return self


class HoursBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    expected_operational_revision: int = Field(gt=0)
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
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    authority_party_id: UUID
    amount: BaseTermsAmount = Field(
        description="Exact nonnegative decimal string (recommended) or JSON integer; "
        "at most 14 integer digits and 6 significant fractional digits. "
        "Fractional JSON numbers, including 1.0, are rejected.",
        examples=["19.90", 19],
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("amount", mode="before")
    @classmethod
    def bounded_decimal_representation(cls, value: object) -> object:
        if isinstance(value, (str, Decimal)):
            try:
                decimal = Decimal(value)
            except ArithmeticError:
                return value
            exponent = decimal.as_tuple().exponent
            if isinstance(exponent, int) and not -16383 <= exponent <= 131071:
                raise ValueError("amount exponent exceeds PostgreSQL numeric representation limits")
        return value


class OrganizationHolidayBody(BaseModel):
    date: date
    reason: str | None = None


class OrganizationHolidaysBody(BaseModel):
    authority_party_id: UUID
    holidays: tuple[OrganizationHolidayBody, ...]


def create_operational_schedule_router(
    *,
    hours_handler: SetLocationOperationalHoursHandler,
    exception_handler: SetLocationHoursExceptionHandler,
    terms_handler: base_terms_command.ConfigureOfferingVersionBookingTermsHandler,
    holidays_handler: DeclareOrganizationHolidaysHandler,
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
    ) -> LocationOperationalHoursView:
        require_capability(current, "catalog.manage")
        windows = tuple(LocationOperationalHoursInput(**item.model_dump()) for item in body.windows)
        result = await set_location_operational_hours(
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
        return LocationOperationalHoursView.model_validate(result)

    async def exception(
        location_id: UUID,
        body: HoursExceptionBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> LocationHoursExceptionView:
        require_capability(current, "catalog.manage")
        result = await set_location_hours_exception(
            exception_handler,
            SetLocationHoursExceptionCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                location_id=location_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )
        return LocationHoursExceptionView.model_validate(result)

    async def base_terms(
        offering_version_id: UUID,
        body: BaseTermsBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> OfferingVersionBookingTermsView:
        require_capability(current, "catalog.manage")
        command = base_terms_command.ConfigureOfferingVersionBookingTermsCommand(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            authority_party_id=body.authority_party_id,
            offering_version_id=offering_version_id,
            amount=body.amount,
            currency=body.currency,
            idempotency_key=key,
        )
        result = await base_terms_command.configure_offering_version_booking_terms(
            terms_handler,
            command,
        )
        return OfferingVersionBookingTermsView.model_validate(result)

    async def holidays(
        body: OrganizationHolidaysBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> DeclaredOrganizationHolidaysView:
        require_capability(current, "catalog.manage")
        result = await declare_organization_holidays(
            holidays_handler,
            DeclareOrganizationHolidaysCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                holidays=tuple(
                    OrganizationHolidayInput(date=item.date, reason=item.reason)
                    for item in body.holidays
                ),
                idempotency_key=key,
            ),
        )
        return DeclaredOrganizationHolidaysView.model_validate(result)

    add_capability_route(
        router,
        "/locations/{location_id}/hours",
        hours,
        capability="catalog.manage",
        methods=["PUT"],
        operation_id="catalog_location_hours_replace",
        response_model=LocationOperationalHoursView,
        responses={
            409: {"model": ErrorEnvelope, "description": "Configuration or revision conflict"},
            422: {"model": ErrorEnvelope, "description": "Invalid schedule input"},
        },
    )
    add_capability_route(
        router,
        "/locations/{location_id}/hours-exceptions",
        exception,
        capability="catalog.manage",
        methods=["PUT"],
        operation_id="catalog_location_hours_exception_upsert",
        response_model=LocationHoursExceptionView,
    )
    add_capability_route(
        router,
        "/offering-versions/{offering_version_id}/booking-terms",
        base_terms,
        capability="catalog.manage",
        methods=["PUT"],
        operation_id="catalog_offering_booking_terms_configure",
        response_model=OfferingVersionBookingTermsView,
        responses={
            409: {"model": ErrorEnvelope, "description": "Configuration or idempotency conflict"},
            422: {"model": ErrorEnvelope, "description": "Invalid exact price or currency input"},
        },
    )
    add_capability_route(
        router,
        "/organization/holidays",
        holidays,
        capability="catalog.manage",
        methods=["PUT"],
        operation_id="catalog_organization_holidays_replace",
        response_model=DeclaredOrganizationHolidaysView,
    )
    return router
