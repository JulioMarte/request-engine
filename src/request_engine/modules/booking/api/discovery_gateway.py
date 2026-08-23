from typing import Annotated

from fastapi import APIRouter, Depends, Request

from request_engine.modules.booking.api.discovery_gateway_models import (
    PublishedSlotQueryBody,
    PublishedSlotWire,
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

    @router.post("/published-slots", response_model=tuple[PublishedSlotWire, ...])
    async def published_slots(
        body: PublishedSlotQueryBody,
        actor: Annotated[PlatformDiscoveryActor, Depends(authenticated_actor)],
    ) -> tuple[PublishedSlotWire, ...]:
        require_platform_discovery_capability(actor, DISCOVERY_SLOT_READ_CAPABILITY)
        slots = await slot_reader.find_published_slots(body.to_contract())
        return tuple(PublishedSlotWire.from_contract(slot) for slot in slots)

    return router
