from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from request_engine.modules.catalog.api.models import BusinessInfoView
from request_engine.modules.catalog.api.offering_models import OfferingView
from request_engine.modules.catalog.application.queries.get_business_info import (
    BusinessInfoReader,
    get_business_info,
)
from request_engine.modules.catalog.application.queries.search_offerings import (
    OfferingCatalogReader,
    SearchOfferingsQuery,
    get_offering_details,
    search_offerings,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


def create_router(
    *,
    business_reader: BusinessInfoReader,
    offering_reader: OfferingCatalogReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(tags=["catalog"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def business_info(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> BusinessInfoView:
        require_capability(actor, "business.get_info")
        info = await get_business_info(business_reader, actor.organization_id)
        return BusinessInfoView.from_contract(info)

    async def offerings(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        search_text: Annotated[str | None, Query(max_length=200)] = None,
        bookable: bool | None = None,
        requestable: bool | None = None,
        location_id: UUID | None = None,
        effective_at: datetime | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> tuple[OfferingView, ...]:
        require_capability(actor, "catalog.search_offerings")
        result = await search_offerings(
            offering_reader,
            SearchOfferingsQuery(
                organization_id=actor.organization_id,
                search_text=search_text,
                bookable=bookable,
                requestable=requestable,
                location_id=location_id,
                effective_at=effective_at,
                limit=limit,
            ),
        )
        return tuple(OfferingView.from_contract(item) for item in result)

    async def offering_details(
        offering_key: str,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> OfferingView:
        require_capability(actor, "catalog.get_offering_details")
        offering = await get_offering_details(
            offering_reader,
            organization_id=actor.organization_id,
            offering_key=offering_key,
        )
        if offering is None:
            raise HTTPException(status_code=404, detail="Offering not found")
        return OfferingView.from_contract(offering)

    add_capability_route(
        router,
        "/v1/business",
        business_info,
        capability="business.get_info",
        methods=["GET"],
        response_model=BusinessInfoView,
    )
    add_capability_route(
        router,
        "/v1/catalog/offerings",
        offerings,
        capability="catalog.search_offerings",
        methods=["GET"],
        response_model=tuple[OfferingView, ...],
        response_model_exclude_none=True,
    )
    add_capability_route(
        router,
        "/v1/catalog/offerings/{offering_key}",
        offering_details,
        capability="catalog.get_offering_details",
        methods=["GET"],
        response_model=OfferingView,
        response_model_exclude_none=True,
    )
    return router
