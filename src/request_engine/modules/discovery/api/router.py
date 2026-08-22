from typing import Annotated

from fastapi import APIRouter, Depends, Request

from request_engine.modules.booking.contracts.appointment_options import (
    AppointmentOptionCodec,
)
from request_engine.modules.booking.contracts.discovery import PublishedSlotReader
from request_engine.modules.discovery.api.models import (
    DiscoveryOptionView,
    SearchPublishedSupplyBody,
)
from request_engine.modules.discovery.application.queries.search_supply import (
    DiscoveryCandidateReader,
    SearchPublishedSupplyQuery,
    search_published_supply,
)
from request_engine.platform.security.platform_discovery import (
    PlatformDiscoveryActor,
    PlatformDiscoveryActorResolver,
    require_platform_discovery_capability,
)


def create_router(
    *,
    candidate_reader: DiscoveryCandidateReader,
    slot_reader: PublishedSlotReader,
    option_codec: AppointmentOptionCodec,
    actor_resolver: PlatformDiscoveryActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/discovery", tags=["discovery"])

    async def authenticated_actor(request: Request) -> PlatformDiscoveryActor:
        return await actor_resolver.resolve_actor(request)

    @router.post("/supply/search", response_model=tuple[DiscoveryOptionView, ...])
    async def search_supply(
        body: SearchPublishedSupplyBody,
        actor: Annotated[PlatformDiscoveryActor, Depends(authenticated_actor)],
    ) -> tuple[DiscoveryOptionView, ...]:
        require_platform_discovery_capability(actor)
        options = await search_published_supply(
            candidate_reader,
            slot_reader,
            SearchPublishedSupplyQuery(
                service_classification_key=body.service_classification_key,
                origin_latitude=body.origin_latitude,
                origin_longitude=body.origin_longitude,
                radius_meters=body.radius_meters,
                window_start=body.window_start,
                window_end=body.window_end,
                limit=body.limit,
            ),
        )
        return tuple(
            DiscoveryOptionView.from_option(
                item,
                option_codec.issue(item.candidate.organization_id, item.slot),
            )
            for item in options
        )

    return router
