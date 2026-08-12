from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from request_engine.modules.catalog.adapters.db.business_info_reader import PostgresBusinessInfoReader
from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.api.models import BusinessInfoView, OfferingView
from request_engine.modules.catalog.application.queries.get_business_info import get_business_info
from request_engine.modules.catalog.application.queries.search_offerings import (
    SearchOfferingsQuery,
    get_offering_details,
    search_offerings,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, AuthenticationRequired


def create_router(
    *,
    business_reader: PostgresBusinessInfoReader,
    offering_reader: PostgresOfferingCatalogReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(tags=["catalog"])

    async def authenticated_actor(request: Request) -> ActorContext:
        try:
            return await actor_resolver.resolve_actor(request)
        except AuthenticationRequired as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
            ) from exc

    async def business_info(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> BusinessInfoView:
        _require(actor, "business.read")
        info = await get_business_info(business_reader, actor.organization_id)
        return BusinessInfoView.from_contract(info)

    async def offerings(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        search_text: Annotated[str | None, Query(max_length=200)] = None,
        bookable: bool | None = None,
        requestable: bool | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> tuple[OfferingView, ...]:
        _require(actor, "catalog.read")
        result = await search_offerings(
            offering_reader,
            SearchOfferingsQuery(
                organization_id=actor.organization_id,
                search_text=search_text,
                bookable=bookable,
                requestable=requestable,
                limit=limit,
            ),
        )
        return tuple(OfferingView.from_contract(item) for item in result)

    async def offering_details(
        offering_key: str,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> OfferingView:
        _require(actor, "catalog.read")
        offering = await get_offering_details(
            offering_reader,
            organization_id=actor.organization_id,
            offering_key=offering_key,
        )
        if offering is None:
            raise HTTPException(status_code=404, detail="Offering not found")
        return OfferingView.from_contract(offering)

    router.add_api_route(
        "/v1/business", business_info, methods=["GET"], response_model=BusinessInfoView
    )
    router.add_api_route(
        "/v1/catalog/offerings",
        offerings,
        methods=["GET"],
        response_model=tuple[OfferingView, ...],
    )
    router.add_api_route(
        "/v1/catalog/offerings/{offering_key}",
        offering_details,
        methods=["GET"],
        response_model=OfferingView,
    )
    return router


def _require(actor: ActorContext, capability: str) -> None:
    if not actor.allows(capability):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"capability {capability!r} is required",
        )
