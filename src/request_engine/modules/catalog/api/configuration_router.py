import base64
from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from request_engine.modules.catalog.api.bootstrap_models import ResourceCapabilityView
from request_engine.modules.catalog.api.bootstrap_router import BookingPolicyBody
from request_engine.modules.catalog.application.errors import CatalogInvalidInput
from request_engine.modules.catalog.application.queries.read_configuration import (
    CatalogConfigurationReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class CapabilityCursorParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: UUID
    capability_id: UUID


class ResourceCapabilityPageView(BaseModel):
    items: tuple[ResourceCapabilityView, ...]
    next_cursor: str | None = None


class OfferingRequirementView(BaseModel):
    capability_id: UUID
    quantity: int


class OfferingConfigurationView(BaseModel):
    offering_id: UUID
    offering_version_id: UUID
    offering_key: str
    version: int
    active: bool
    requirements: tuple[OfferingRequirementView, ...]
    booking_policy_revision: int
    booking_policy: BookingPolicyBody


def create_configuration_router(
    reader: CatalogConfigurationReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/catalog", tags=["catalog"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def capabilities(
        request: Request,
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> ResourceCapabilityPageView:
        """List the tenant's resource-capability vocabulary before configuring supply.

        These are resource requirements, not authorization capabilities. Follow
        next_cursor as cursor without changing tenant context. Null marks the observed
        end of the collection; this is a live keyset read, not a frozen snapshot.
        """
        require_capability(current, "catalog.read_configuration")
        response.headers["Cache-Control"] = "no-store"
        if set(request.query_params) - {"limit", "cursor"}:
            raise CatalogInvalidInput("unsupported capability filter")
        after_id = None
        if cursor:
            try:
                position = CapabilityCursorParams.model_validate_json(
                    base64.b64decode(cursor, altchars=b"-_", validate=True)
                )
            except ValueError:
                raise CatalogInvalidInput("cursor is invalid") from None
            if position.organization_id != current.organization_id:
                raise CatalogInvalidInput("cursor does not match tenant context")
            after_id = position.capability_id
        rows = await reader.list_resource_capabilities(
            current.organization_id,
            principal_id=current.principal_id,
            limit=limit + 1,
            after_id=after_id,
        )
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            next_cursor = base64.urlsafe_b64encode(
                CapabilityCursorParams(
                    organization_id=current.organization_id,
                    capability_id=page[-1].capability_id,
                )
                .model_dump_json()
                .encode()
            ).decode()
        return ResourceCapabilityPageView(
            items=tuple(ResourceCapabilityView.model_validate(item) for item in page),
            next_cursor=next_cursor,
        )

    async def offering_configuration(
        offering_version_id: UUID,
        request: Request,
        response: Response,
        current: Annotated[ActorContext, Depends(actor)],
    ) -> OfferingConfigurationView:
        """Read exact OfferingVersion requirements and the effective booking policy.

        Use booking_policy_revision for a revision-sensitive policy command. Catalog
        eligibility is advisory: Booking still checks schedules and committed capacity.
        Missing and foreign versions both return 404.
        """
        require_capability(current, "catalog.read_configuration")
        response.headers["Cache-Control"] = "no-store"
        if request.query_params:
            raise CatalogInvalidInput("offering configuration does not accept filters")
        state = await reader.read_offering_configuration(
            current.organization_id,
            offering_version_id,
            principal_id=current.principal_id,
        )
        if state is None:
            raise HTTPException(status_code=404, detail="OfferingVersion not found")
        return OfferingConfigurationView.model_validate(asdict(state))

    for path, handler, operation_id, model in (
        (
            "/resource-capabilities",
            capabilities,
            "catalog_resource_capabilities_list",
            ResourceCapabilityPageView,
        ),
        (
            "/offering-versions/{offering_version_id}/configuration",
            offering_configuration,
            "catalog_offering_version_configuration_read",
            OfferingConfigurationView,
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
