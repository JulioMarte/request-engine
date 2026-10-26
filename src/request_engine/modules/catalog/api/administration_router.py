"""Administrative inventory: owner-authorized live reads, never public discovery."""

from dataclasses import asdict, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.catalog.application.queries.administration import (
    CatalogAdministrationQuery,
    CatalogAdministrationReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class CatalogAdministrationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID = Field(description="Party currently represented; not a grant")
    limit: int = Field(default=50, ge=1, le=100)
    after: UUID | None = None


class LocationAdministrationView(BaseModel):
    location_id: UUID
    location_key: str
    display_name: str
    timezone: str
    active: bool
    operational_revision: int
    address_line1: str | None
    address_line2: str | None
    locality: str | None
    administrative_area: str | None
    postal_code: str | None
    country_code: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    geocoding_source: str | None
    geocoded_at: datetime | None


class LocationHoursWindowView(BaseModel):
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None
    valid_until: date | None


class LocationPublicContactConfigurationView(BaseModel):
    channel: Literal["phone", "whatsapp", "email"]
    value: str
    label: str | None


class LocationAdministrationDetailView(LocationAdministrationView):
    hours_windows: tuple[LocationHoursWindowView, ...]
    public_contacts: tuple[LocationPublicContactConfigurationView, ...]


class OfferingAdministrationView(BaseModel):
    offering_id: UUID
    offering_key: str
    display_name: str
    description: str | None
    active: bool
    offering_version_id: UUID
    version: int
    duration_minutes: int | None
    bookable: bool
    requestable: bool
    booking_policy_revision: int
    revision: int = Field(
        description="Offering revision; expected_revision for catalog_offering_update"
    )


class LocationAdministrationPageView(BaseModel):
    items: tuple[LocationAdministrationView, ...]
    next_cursor: UUID | None


class OfferingAdministrationPageView(BaseModel):
    items: tuple[OfferingAdministrationView, ...]
    next_cursor: UUID | None


def create_administration_router(
    reader: CatalogAdministrationReader, actor_resolver: ActorResolver
) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    def query(
        params: CatalogAdministrationParams, current: ActorContext
    ) -> CatalogAdministrationQuery:
        require_capability(current, "catalog.read_configuration")
        return CatalogAdministrationQuery(
            organization_id=current.organization_id,
            principal_id=current.principal_id,
            **params.model_dump(),
        )

    async def locations(
        params: Annotated[CatalogAdministrationParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> LocationAdministrationPageView:
        """List active and inactive locations with current configuration revisions.

        Follow next_cursor as after with the same Party and tenant. The owner requires
        current operations.manage_profile authority. This is not a frozen snapshot.
        """
        rows = await reader.locations(query(params, current))
        response.headers["Cache-Control"] = "no-store"
        return LocationAdministrationPageView(
            items=tuple(LocationAdministrationView(**asdict(row)) for row in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].location_id if len(rows) > params.limit else None,
        )

    async def location(
        location_id: UUID,
        authority_party_id: UUID,
        request: Request,
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> LocationAdministrationDetailView:
        if set(request.query_params) - {"authority_party_id"}:
            raise HTTPException(422, detail="unsupported configuration filter")
        command = query(CatalogAdministrationParams(authority_party_id=authority_party_id), current)
        rows = await reader.locations(replace(command, target_id=location_id, limit=1))
        if not rows:
            raise HTTPException(404, detail="Location not found")
        response.headers["Cache-Control"] = "no-store"
        return LocationAdministrationDetailView(**asdict(rows[0]))

    async def offerings(
        params: Annotated[CatalogAdministrationParams, Query()],
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> OfferingAdministrationPageView:
        """List active/inactive offerings and each latest version's policy revision.

        Requires operations.manage_terms. The latest version reference can be passed
        to the exact-version configuration read. Historical versions are not enumerated.
        Follow next_cursor as after with the same Party and tenant; this is a live read.
        """
        rows = await reader.offerings(query(params, current))
        response.headers["Cache-Control"] = "no-store"
        return OfferingAdministrationPageView(
            items=tuple(OfferingAdministrationView(**asdict(row)) for row in rows[: params.limit]),
            next_cursor=rows[params.limit - 1].offering_id if len(rows) > params.limit else None,
        )

    async def offering(
        offering_id: UUID,
        authority_party_id: UUID,
        request: Request,
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> OfferingAdministrationView:
        if set(request.query_params) - {"authority_party_id"}:
            raise HTTPException(422, detail="unsupported configuration filter")
        command = query(CatalogAdministrationParams(authority_party_id=authority_party_id), current)
        rows = await reader.offerings(replace(command, target_id=offering_id, limit=1))
        if not rows:
            raise HTTPException(404, detail="Offering not found")
        response.headers["Cache-Control"] = "no-store"
        return OfferingAdministrationView(**asdict(rows[0]))

    for path, handler, operation_id, model in (
        (
            "/locations/configuration",
            locations,
            "catalog_location_configuration_list",
            LocationAdministrationPageView,
        ),
        (
            "/locations/{location_id}/configuration",
            location,
            "catalog_location_configuration_read",
            LocationAdministrationDetailView,
        ),
        (
            "/offerings/configuration",
            offerings,
            "catalog_offering_configuration_list",
            OfferingAdministrationPageView,
        ),
        (
            "/offerings/{offering_id}/configuration",
            offering,
            "catalog_offering_configuration_read",
            OfferingAdministrationView,
        ),
    ):
        add_capability_route(
            router,
            path,
            handler,
            capability="catalog.read_configuration",
            methods=["GET"],
            operation_id=operation_id,
            response_model=model,
        )
    return router
