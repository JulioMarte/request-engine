from fastapi import FastAPI

from request_engine.modules.booking.contracts.onboarding import (
    BookingOnboardingReadinessReader,
)
from request_engine.modules.catalog.contracts.onboarding import CatalogOnboardingReadinessReader
from request_engine.modules.communications.contracts.onboarding import (
    CommunicationsOnboardingReadinessReader,
)
from request_engine.modules.onboarding.api.router import create_onboarding_readiness_router
from request_engine.modules.onboarding.application.readiness import OwnerBackedOnboardingReadiness
from request_engine.modules.queue.contracts.onboarding import QueueOnboardingReadinessReader
from request_engine.modules.tenancy.contracts.onboarding_readiness import BusinessPartyReader
from request_engine.platform.security.http import ActorResolver

__all__ = ["install_http"]


def install_http(
    app: FastAPI,
    *,
    actor_resolver: ActorResolver,
    party_reader: BusinessPartyReader,
    catalog_reader: CatalogOnboardingReadinessReader,
    booking_reader: BookingOnboardingReadinessReader,
    queue_reader: QueueOnboardingReadinessReader,
    communications_reader: CommunicationsOnboardingReadinessReader,
) -> None:
    reader = OwnerBackedOnboardingReadiness(
        party_reader=party_reader,
        catalog_reader=catalog_reader,
        booking_reader=booking_reader,
        queue_reader=queue_reader,
        communications_reader=communications_reader,
    )
    app.include_router(
        create_onboarding_readiness_router(
            reader=reader,
            actor_resolver=actor_resolver,
        )
    )
