from fastapi import FastAPI

from request_engine.bootstrap.recovery_catalog import CatalogRecoveryLocationAdapter
from request_engine.bootstrap.recovery_queue import QueueRecoveryIntakeAdapter
from request_engine.modules.booking.api import install_http as install_booking_http
from request_engine.modules.booking.api.live_capacity import (
    build_live_capacity_source as build_booking_live_capacity_source,
)
from request_engine.modules.booking.api.recovery import build_recovery_booking_port
from request_engine.modules.booking.api.recovery_schedule import (
    build_recovery_assignment_schedule_port,
)
from request_engine.modules.catalog.api import install_http as install_catalog_http
from request_engine.modules.catalog.api.copilot import build_copilot_catalog_reader
from request_engine.modules.catalog.api.recovery_schedule import (
    build_recovery_location_schedule_port,
)
from request_engine.modules.communications.api import install_http as install_communications_http
from request_engine.modules.communications.api.recovery import (
    build_recovery_communication_port,
)
from request_engine.modules.delivery.api import install_http as install_delivery_http
from request_engine.modules.delivery.api.live_capacity import (
    build_live_capacity_source as build_delivery_live_capacity_source,
)
from request_engine.modules.discovery.api.publication_runtime import (
    build_discovery_publication_runtime,
)
from request_engine.modules.live_capacity.api import install_http as install_live_capacity_http
from request_engine.modules.live_capacity.api.recovery import build_recovery_capacity_source
from request_engine.modules.operational_copilot.api import build_live_capacity_at_risk_reader
from request_engine.modules.operational_copilot.api import install_http as install_copilot_http
from request_engine.modules.operational_recovery.api import install_http as install_recovery_http
from request_engine.modules.queue.api import QueueSlotOfferHttpPorts
from request_engine.modules.queue.api import install_http as install_queue_http
from request_engine.modules.queue.api.copilot import build_copilot_queue_runtime
from request_engine.modules.queue.api.live_capacity import (
    build_live_capacity_source as build_queue_live_capacity_source,
)
from request_engine.modules.requests.api import install_http as install_requests_http
from request_engine.modules.tenancy.api import (
    build_operational_authority_party_reader,
    build_party_authority_reader,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_business_modules(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    slot_offer_ports: QueueSlotOfferHttpPorts | None,
    appointment_option_signing_key: bytes,
) -> None:
    party_authority_reader = build_party_authority_reader(session_factory)
    install_requests_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    install_catalog_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    install_booking_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        party_authority_reader=party_authority_reader,
        appointment_option_signing_key=appointment_option_signing_key,
    )
    install_queue_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        slot_offer_ports=slot_offer_ports,
    )
    install_delivery_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    booking_capacity = build_booking_live_capacity_source()
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
    recovery = install_recovery_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        capacity=recovery_capacity,
        booking=build_recovery_booking_port(session_factory),
        communications=build_recovery_communication_port(session_factory),
        intake=QueueRecoveryIntakeAdapter(queue_runtime.intake),
        location_schedule=CatalogRecoveryLocationAdapter(
            build_recovery_location_schedule_port(session_factory)
        ),
        assignment_schedule=build_recovery_assignment_schedule_port(session_factory),
    )
    install_copilot_http(
        app,
        actor_resolver=actor_resolver,
        at_risk_reader=build_live_capacity_at_risk_reader(recovery_capacity),
        proposal_reader=recovery.service,
        authority_reader=build_operational_authority_party_reader(session_factory),
        recovery_executor=recovery.service,
        intake_executor=recovery.workflow,
        extend_day_executor=recovery.workflow,
        discovery_executor=build_discovery_publication_runtime(session_factory),
        catalog_reader=build_copilot_catalog_reader(session_factory),
        queue_reader=queue_runtime.queues,
        queue_intake_reader=queue_runtime.intake,
        recovery_incident_reader=recovery.incidents,
    )
