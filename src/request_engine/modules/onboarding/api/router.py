from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from request_engine.modules.onboarding.application.readiness import (
    OnboardingReadiness,
    OnboardingReadinessReader,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver, require_capability


class ReadinessBlockerView(BaseModel):
    """Machine-readable setup blocker without transport-coupling Onboarding to another owner."""

    model_config = ConfigDict(extra="forbid")

    code: str
    owner: str
    resolution_capabilities: tuple[str, ...] = ()


class JourneyReadinessView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    blockers: tuple[ReadinessBlockerView, ...] = ()


class CountedJourneyReadinessView(JourneyReadinessView):
    count: int


class OnboardingReadinessView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_party: JourneyReadinessView
    locations: CountedJourneyReadinessView
    appointments: JourneyReadinessView
    walk_in_queue: CountedJourneyReadinessView
    communications: JourneyReadinessView


def _blocker(
    code: str,
    owner: str,
    *resolution_capabilities: str,
) -> ReadinessBlockerView:
    return ReadinessBlockerView(
        code=code,
        owner=owner,
        resolution_capabilities=resolution_capabilities,
    )


def project_readiness(facts: OnboardingReadiness) -> OnboardingReadinessView:
    """Project owner facts into actionable guidance without acquiring execution authority."""

    business_party_blockers = (
        () if facts.has_business_party else (_blocker("business_party_missing", "tenancy"),)
    )
    location_blockers = (
        ()
        if facts.location_count > 0
        else (_blocker("location_missing", "catalog", "catalog.manage"),)
    )

    appointment_blockers: list[ReadinessBlockerView] = []
    if facts.bookable_offering_version_count == 0:
        appointment_blockers.append(
            _blocker("no_bookable_offering", "catalog", "catalog.manage")
        )
    if facts.resource_supply_count == 0:
        appointment_blockers.append(
            _blocker("no_resource_supply", "booking", "booking.manage_supply")
        )

    queue_blockers = (
        ()
        if facts.active_queue_count > 0
        else (_blocker("service_queue_missing", "queue", "queue.configure"),)
    )
    communication_blockers = (
        ()
        if facts.disabled_purpose_count == 0
        else (
            _blocker(
                "channel_purpose_disabled",
                "communications",
                "communications.configure",
            ),
        )
    )

    return OnboardingReadinessView(
        business_party=JourneyReadinessView(
            ready=not business_party_blockers,
            blockers=business_party_blockers,
        ),
        locations=CountedJourneyReadinessView(
            ready=not location_blockers,
            count=facts.location_count,
            blockers=location_blockers,
        ),
        appointments=JourneyReadinessView(
            ready=not appointment_blockers,
            blockers=tuple(appointment_blockers),
        ),
        walk_in_queue=CountedJourneyReadinessView(
            ready=not queue_blockers,
            count=facts.active_queue_count,
            blockers=queue_blockers,
        ),
        communications=JourneyReadinessView(
            ready=not communication_blockers,
            blockers=communication_blockers,
        ),
    )


def create_onboarding_readiness_router(
    *,
    reader: OnboardingReadinessReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])

    async def actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    async def readiness(
        current: Annotated[ActorContext, Depends(actor)],
    ) -> OnboardingReadinessView:
        require_capability(current, "onboarding.read")
        facts = await reader.read(organization_id=current.organization_id)
        return project_readiness(facts)

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
