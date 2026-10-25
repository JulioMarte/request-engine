"""Owner edits after creation: Offering rename/supersession and closure removal."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.catalog.api.operational_schedule_router import BaseTermsAmount
from request_engine.modules.catalog.api.operational_views import LocationHoursExceptionView
from request_engine.modules.catalog.application.commands import edit_offering
from request_engine.modules.catalog.application.commands import (
    remove_location_closures as closures,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.http.errors import ErrorEnvelope
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]
_ERRORS: dict[int | str, dict[str, object]] = {
    409: {"model": ErrorEnvelope, "description": "Revision, state or idempotency conflict"},
    422: {"model": ErrorEnvelope, "description": "Invalid input"},
}


class OfferingUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(
        gt=0, description="Offering revision from the configuration read"
    )


class SupersedeTermsBody(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    amount: BaseTermsAmount = Field(
        description="Exact nonnegative decimal string (recommended) or JSON integer; "
        "fractional JSON numbers are rejected.",
        examples=["25.00", 25],
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class OfferingVersionSupersedeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    expected_current_offering_version_id: UUID = Field(
        description="Latest OfferingVersion id the caller read; a newer version fails 409"
    )
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    booking_terms: SupersedeTermsBody | None = None


class LocationHoursExceptionDeactivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    expected_operational_revision: int = Field(gt=0)


class OrganizationHolidaysRemoveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    dates: tuple[date, ...] = Field(min_length=1, max_length=366)


class OfferingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    offering_id: UUID
    offering_key: str
    display_name: str
    active: bool
    revision: int


class SupersededTermsView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    terms_id: UUID
    amount: Decimal
    currency: str


class SupersededOfferingVersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    offering_id: UUID
    offering_version_id: UUID
    version: int
    previous_offering_version_id: UUID
    duration_minutes: int | None
    booking_terms: SupersededTermsView | None
    requirement_count: int


class RemovedOrganizationHolidaysView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dates: tuple[date, ...]
    locations_examined: int
    exceptions_deactivated: int
    dates_not_found: tuple[date, ...]


def create_configuration_edit_router(
    *,
    offering_handler: edit_offering.UpdateOfferingHandler,
    version_handler: edit_offering.SupersedeOfferingVersionHandler,
    exception_handler: closures.DeactivateLocationHoursExceptionHandler,
    holidays_handler: closures.RemoveOrganizationHolidaysHandler,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/operations", tags=["operations"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def update_offering(
        offering_id: UUID,
        body: OfferingUpdateBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> OfferingView:
        """Rename an Offering (label only; no new version, Reservations unchanged)."""
        require_capability(current, "catalog.manage")
        result = await edit_offering.update_offering(
            offering_handler,
            edit_offering.UpdateOfferingCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                offering_id=offering_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )
        return OfferingView.model_validate(result)

    async def supersede_version(
        offering_id: UUID,
        body: OfferingVersionSupersedeBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> SupersededOfferingVersionView:
        """Append a new OfferingVersion with a new duration and/or base price.

        Requirements, bookable/requestable flags and the effective booking policy
        are copied; the base price is copied unless booking_terms is given. Existing
        Reservations keep their exact version. Per-assignment context terms are
        bound to the exact version and are not carried over.
        """
        require_capability(current, "catalog.manage")
        terms = body.booking_terms
        result = await edit_offering.supersede_offering_version(
            version_handler,
            edit_offering.SupersedeOfferingVersionCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                offering_id=offering_id,
                expected_current_offering_version_id=body.expected_current_offering_version_id,
                duration_minutes=body.duration_minutes,
                booking_terms=None
                if terms is None
                else edit_offering.BaseTermsInput(amount=terms.amount, currency=terms.currency),
                idempotency_key=key,
            ),
        )
        return SupersededOfferingVersionView.model_validate(result)

    async def deactivate_exception(
        location_id: UUID,
        exception_id: UUID,
        body: LocationHoursExceptionDeactivateBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> LocationHoursExceptionView:
        """Remove a saved special schedule by deactivating it (the row stays auditable)."""
        require_capability(current, "catalog.manage")
        result = await closures.deactivate_location_hours_exception(
            exception_handler,
            closures.DeactivateLocationHoursExceptionCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                location_id=location_id,
                exception_id=exception_id,
                idempotency_key=key,
                **body.model_dump(),
            ),
        )
        return LocationHoursExceptionView.model_validate(result)

    async def remove_holidays(
        body: OrganizationHolidaysRemoveBody,
        key: IdempotencyKey,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> RemovedOrganizationHolidaysView:
        """Deactivate each Location's active full-day closure for the given dates."""
        require_capability(current, "catalog.manage")
        result = await closures.remove_organization_holidays(
            holidays_handler,
            closures.RemoveOrganizationHolidaysCommand(
                organization_id=current.organization_id,
                principal_id=current.principal_id,
                authority_party_id=body.authority_party_id,
                dates=body.dates,
                idempotency_key=key,
            ),
        )
        return RemovedOrganizationHolidaysView.model_validate(result)

    add_capability_route(
        router,
        "/offerings/{offering_id}",
        update_offering,
        capability="catalog.manage",
        methods=["PATCH"],
        operation_id="catalog_offering_update",
        response_model=OfferingView,
        responses=_ERRORS,
    )
    add_capability_route(
        router,
        "/offerings/{offering_id}/versions",
        supersede_version,
        capability="catalog.manage",
        methods=["POST"],
        operation_id="catalog_offering_version_supersede",
        response_model=SupersededOfferingVersionView,
        status_code=status.HTTP_201_CREATED,
        responses=_ERRORS,
    )
    add_capability_route(
        router,
        "/locations/{location_id}/hours-exceptions/{exception_id}:deactivate",
        deactivate_exception,
        capability="catalog.manage",
        methods=["POST"],
        operation_id="catalog_location_hours_exception_deactivate",
        response_model=LocationHoursExceptionView,
        responses=_ERRORS,
    )
    add_capability_route(
        router,
        "/organization/holidays:remove",
        remove_holidays,
        capability="catalog.manage",
        methods=["POST"],
        operation_id="catalog_organization_holidays_remove",
        response_model=RemovedOrganizationHolidaysView,
        responses=_ERRORS,
    )
    return router
