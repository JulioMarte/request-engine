from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from request_engine.modules.tenancy.contracts.onboarding_readiness import (
    OnboardingReadinessFactsReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class OnboardingReadinessView(BaseModel):
    business_party: dict[str, bool]
    locations: dict[str, object]
    appointments: dict[str, object]
    walk_in_queue: dict[str, object]
    communications: dict[str, object]


def create_onboarding_readiness_router(
    *,
    reader: OnboardingReadinessFactsReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def readiness(
        current: Annotated[ActorContext, Depends(actor)],
    ) -> OnboardingReadinessView:
        require_capability(current, "onboarding.read")
        facts = await reader.read_onboarding_facts(organization_id=current.organization_id)
        appointment_blockers: list[str] = []
        if facts.bookable_offering_version_count == 0:
            appointment_blockers.append("no_bookable_offering")
        if facts.resource_supply_count == 0:
            appointment_blockers.append("no_resource_supply")
        communication_blockers: list[str] = (
            ["channel_purpose_disabled"] if facts.disabled_purpose_count > 0 else []
        )
        return OnboardingReadinessView(
            business_party={"ready": facts.has_business_party},
            locations={"ready": facts.location_count > 0, "count": facts.location_count},
            appointments={"ready": not appointment_blockers, "blockers": appointment_blockers},
            walk_in_queue={
                "ready": facts.active_queue_count > 0,
                "queue_count": facts.active_queue_count,
            },
            communications={
                "ready": not communication_blockers,
                "blockers": communication_blockers,
            },
        )

    add_capability_route(
        router,
        "/readiness",
        readiness,
        capability="onboarding.read",
        methods=["GET"],
        operation_id="onboarding_read",
        response_model=OnboardingReadinessView,
    )
    return router
