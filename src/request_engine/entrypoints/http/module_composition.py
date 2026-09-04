from uuid import UUID

from fastapi import FastAPI

import request_engine.modules.booking.api.live_capacity as booking_live_capacity
import request_engine.modules.booking.api.onboarding as booking_onboarding
import request_engine.modules.booking.api.operational_schedule as booking_operational_schedule
import request_engine.modules.booking.api.recovery_schedule as booking_recovery_schedule
import request_engine.modules.catalog.api.onboarding as catalog_onboarding
import request_engine.modules.catalog.api.recovery_schedule as catalog_recovery_schedule
import request_engine.modules.communications.api.onboarding as communications_onboarding
import request_engine.modules.operational_copilot.api as copilot_api
import request_engine.modules.queue.api as queue_api
import request_engine.modules.queue.api.onboarding as queue_onboarding
import request_engine.modules.tenancy.api as tenancy_api
from request_engine.bootstrap.recovery_catalog import CatalogRecoveryLocationAdapter
from request_engine.bootstrap.recovery_queue import QueueRecoveryIntakeAdapter
from request_engine.modules.booking.api import install_http as install_booking_http
from request_engine.modules.booking.api.copilot import build_copilot_booking_reader
from request_engine.modules.booking.api.onboarding import BookingOnboardingReadinessReader
from request_engine.modules.booking.api.recovery import build_recovery_booking_port
from request_engine.modules.catalog.api import install_http as install_catalog_http
from request_engine.modules.catalog.api.copilot import build_copilot_catalog_reader
from request_engine.modules.catalog.api.onboarding import CatalogOnboardingReadinessReader
from request_engine.modules.communications.api import install_http as install_communications_http
from request_engine.modules.communications.api.onboarding import (
    CommunicationsOnboardingReadinessReader,
)
from request_engine.modules.communications.api.recovery import build_recovery_communication_port
from request_engine.modules.delivery.api import install_http as install_delivery_http
from request_engine.modules.delivery.api.live_capacity import (
    build_live_capacity_source as build_delivery_live_capacity_source,
)
from request_engine.modules.discovery.api.publication_runtime import (
    build_discovery_publication_runtime,
)
from request_engine.modules.live_capacity.api import install_http as install_live_capacity_http
from request_engine.modules.live_capacity.api.recovery import build_recovery_capacity_source
from request_engine.modules.operational_recovery.api import install_http as install_recovery_http
from request_engine.modules.queue.api.copilot import build_copilot_queue_runtime
from request_engine.modules.queue.api.live_capacity import (
    build_live_capacity_source as build_queue_live_capacity_source,
)
from request_engine.modules.queue.api.onboarding import QueueOnboardingReadinessReader
from request_engine.modules.requests.api import install_http as install_requests_http
from request_engine.modules.tenancy.api import BusinessPartyReader, OnboardingReadinessFacts
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


class CompositeOnboardingReadinessReader(tenancy_api.OnboardingReadinessFactsReader):
    """Compose owner-backed readiness facts through each module's published surface."""

    def __init__(
        self,
        *,
        party_reader: BusinessPartyReader,
        catalog_reader: CatalogOnboardingReadinessReader,
        booking_reader: BookingOnboardingReadinessReader,
        queue_reader: QueueOnboardingReadinessReader,
        communications_reader: CommunicationsOnboardingReadinessReader,
    ) -> None:
        self._party_reader = party_reader
        self._catalog_reader = catalog_reader
        self._booking_reader = booking_reader
        self._queue_reader = queue_reader
        self._communications_reader = communications_reader

    async def read_onboarding_facts(self, *, organization_id: UUID) -> OnboardingReadinessFacts:
        has_business_party = await self._party_reader.has_active_organization_party(
            organization_id=organization_id
        )
        catalog = await self._catalog_reader.read_catalog_supply(organization_id=organization_id)
        booking = await self._booking_reader.read_booking_supply(organization_id=organization_id)
        queue = await self._queue_reader.read_queue_supply(organization_id=organization_id)
        communications = await self._communications_reader.read_communications_supply(
            organization_id=organization_id
        )
        return OnboardingReadinessFacts(
            has_business_party=has_business_party,
            location_count=catalog.location_count,
            bookable_offering_version_count=catalog.bookable_offering_version_count,
            resource_supply_count=booking.resource_supply_count,
            active_queue_count=queue.active_queue_count,
            disabled_purpose_count=communications.disabled_purpose_count,
        )


def install_business_modules(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    slot_offer_ports: queue_api.QueueSlotOfferHttpPorts | None,
    appointment_option_signing_key: bytes,
    identity_exchange_fingerprint_key: bytes | None = None,
) -> None:
    tenancy_api.install_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        identity_exchange_fingerprint_key=identity_exchange_fingerprint_key,
        onboarding_facts_reader=CompositeOnboardingReadinessReader(
            party_reader=tenancy_api.build_onboarding_business_party_reader(session_factory),
            catalog_reader=catalog_onboarding.build_onboarding_catalog_reader(session_factory),
            booking_reader=booking_onboarding.build_onboarding_booking_reader(session_factory),
            queue_reader=queue_onboarding.build_onboarding_queue_reader(session_factory),
            communications_reader=communications_onboarding.build_onboarding_communications_reader(
                session_factory
            ),
        ),
    )
    install_requests_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    install_catalog_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    install_booking_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        party_authority_reader=tenancy_api.build_party_authority_reader(session_factory),
        appointment_option_signing_key=appointment_option_signing_key,
    )
    queue_api.install_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        slot_offer_ports=slot_offer_ports,
    )
    install_delivery_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    booking_capacity = booking_live_capacity.build_live_capacity_source()
    queue_capacity = build_queue_live_capacity_source()
    delivery_capacity = build_delivery_live_capacity_source()
    install_live_capacity_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        booking_source=booking_capacity,
        queue_source=queue_capacity,
        delivery_source=delivery_capacity,
    )
    install_communications_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    recovery_capacity = build_recovery_capacity_source(
        session_factory,
        booking_source=booking_capacity,
        queue_source=queue_capacity,
        delivery_source=delivery_capacity,
    )
    queue_runtime = build_copilot_queue_runtime(session_factory)
    discovery_runtime = build_discovery_publication_runtime(session_factory)
    recovery = install_recovery_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        capacity=recovery_capacity,
        booking=build_recovery_booking_port(session_factory),
        communications=build_recovery_communication_port(session_factory),
        intake=QueueRecoveryIntakeAdapter(queue_runtime.intake),
        location_schedule=CatalogRecoveryLocationAdapter(
            catalog_recovery_schedule.build_recovery_location_schedule_port(session_factory)
        ),
        assignment_schedule=booking_recovery_schedule.build_recovery_assignment_schedule_port(
            session_factory
        ),
    )
    copilot_api.install_http(
        app,
        actor_resolver=actor_resolver,
        at_risk_reader=copilot_api.build_live_capacity_at_risk_reader(recovery_capacity),
        proposal_reader=recovery.service,
        authority_reader=tenancy_api.build_operational_authority_party_reader(session_factory),
        recovery_executor=recovery.service,
        intake_executor=recovery.workflow,
        extend_day_executor=recovery.workflow,
        operational_schedule=booking_operational_schedule.build_operational_assignment_schedule_port(
            session_factory
        ),
        discovery_executor=discovery_runtime,
        discovery_reader=discovery_runtime,
        booking_reader=build_copilot_booking_reader(session_factory),
        catalog_reader=build_copilot_catalog_reader(session_factory),
        queue_reader=queue_runtime.queues,
        queue_intake_reader=queue_runtime.intake,
        recovery_incident_reader=recovery.incidents,
    )
