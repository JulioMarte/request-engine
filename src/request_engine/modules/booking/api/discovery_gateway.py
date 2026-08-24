from typing import Annotated

from fastapi import APIRouter, Depends, Request

from request_engine.modules.booking.api.discovery_gateway_models import (
    PublishedSlotBatchBody,
    PublishedSlotQueryBody,
    PublishedSlotView,
)
from request_engine.modules.booking.contracts.discovery import PublishedSlotReader
from request_engine.platform.security.platform_discovery import (
    DISCOVERY_SLOT_READ_CAPABILITY,
    PlatformDiscoveryActor,
    PlatformDiscoveryActorResolver,
    require_platform_discovery_capability,
)


def create_discovery_availability_router(
    *,
    slot_reader: PublishedSlotReader,
    actor_resolver: PlatformDiscoveryActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/discovery", tags=["discovery-internal"])

    async def authenticated_actor(request: Request) -> PlatformDiscoveryActor:
        return await actor_resolver.resolve_actor(request)

    async def published_slots(
        body: PublishedSlotQueryBody,
        actor: Annotated[PlatformDiscoveryActor, Depends(authenticated_actor)],
    ) -> tuple[PublishedSlotView, ...]:
        require_platform_discovery_capability(actor, DISCOVERY_SLOT_READ_CAPABILITY)
        slots = await slot_reader.find_published_slots(body.to_contract())
        return tuple(PublishedSlotView.from_contract(slot) for slot in slots)

    async def published_slots_batch(
        body: PublishedSlotBatchBody,
        actor: Annotated[PlatformDiscoveryActor, Depends(authenticated_actor)],
    ) -> tuple[tuple[PublishedSlotView, ...], ...]:
        require_platform_discovery_capability(actor, DISCOVERY_SLOT_READ_CAPABILITY)
        groups = await slot_reader.find_published_slots_batch(
            tuple(query.to_contract() for query in body.queries)
        )
        return tuple(
            tuple(PublishedSlotView.from_contract(slot) for slot in slots) for slots in groups
        )

    router.add_api_route(
        "/published-slots",
        published_slots,
        methods=["POST"],
        response_model=tuple[PublishedSlotView, ...],
    )
    router.add_api_route(
        "/published-slots/batch",
        published_slots_batch,
        methods=["POST"],
        response_model=tuple[tuple[PublishedSlotView, ...], ...],
    )
    return router
