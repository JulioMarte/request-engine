from fastapi import FastAPI

from request_engine.modules.booking.api.copilot import build_copilot_booking_reader
from request_engine.modules.booking.api.live_capacity import build_live_capacity_booking_reader
from request_engine.modules.booking.api.recovery import build_recovery_booking_port
from request_engine.modules.booking.api.recovery_schedule import (
    build_recovery_assignment_schedule_port,
)
from request_engine.modules.catalog.api.copilot import build_copilot_catalog_reader
from request_engine.modules.catalog.api.recovery_schedule import (
    build_recovery_location_extension_port,
)
from request_engine.modules.communications.api.recovery import build_recovery_communication_port
from request_engine.modules.delivery.api.live_capacity import build_live_capacity_delivery_reader
from request_engine.modules.discovery.api.publication_runtime import (
    build_discovery_publication_executor,
)
from request_engine.modules.live_capacity.api import install_http as install_live_capacity_http
from request_engine.modules.operational_copilot.api import (
    build_live_capacity_at_risk_reader,
    install_http as install_operational_copilot_http,
)
from request_engine.modules.operational_recovery.api import install_http as install_recovery_http
from request_engine.modules.queue.api import install_http as install_queue_http
from request_engine.modules.queue.api.copilot import build_copilot_queue_reader
from request_engine.modules.queue.api.intake import build_queue_intake_control
from request_engine.modules.queue.api.live_capacity import build_live_capacity_queue_reader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_composed_http_modules(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    queue_reader = build_live_capacity_queue_reader(session_factory)
    queue_intake = build_queue_intake_control(session_factory)
    booking_reader = build_live_capacity_booking_reader(session_factory)
    delivery_reader = build_live_capacity_delivery_reader(session_factory)
    recovery_booking = build_recovery_booking_port(session_factory)
    recovery_communications = build_recovery_communication_port(session_factory)
    recovery_location_schedule = build_recovery_location_extension_port(session_factory)
    recovery_assignment_schedule = build_recovery_assignment_schedule_port(session_factory)
    copilot_booking = build_copilot_booking_reader(session_factory)
    copilot_catalog = build_copilot_catalog_reader(session_factory)
    copilot_queues = build_copilot_queue_reader(session_factory)
    discovery_publications = build_discovery_publication_executor(session_factory)

    live_capacity = install_live_capacity_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        queue_reader=queue_reader,
        booking_reader=booking_reader,
        delivery_reader=delivery_reader,
    )

    recovery = install_recovery_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        capacity=live_capacity.projector,
        booking=recovery_booking,
        communications=recovery_communications,
        intake=queue_intake,
        location_schedule=recovery_location_schedule,
        assignment_schedule=recovery_assignment_schedule,
    )
    install_operational_copilot_http(
        app,
        actor_resolver=actor_resolver,
        at_risk_reader=build_live_capacity_at_risk_reader(live_capacity.projector),
        proposal_reader=recovery.service,
        authority_reader=None,
        recovery_executor=recovery.service,
        intake_executor=recovery.workflow,
        extend_day_executor=recovery.workflow,
        discovery_executor=discovery_publications,
        booking_reader=copilot_booking,
        catalog_reader=copilot_catalog,
        queue_reader=copilot_queues,
        queue_intake_reader=queue_intake,
        recovery_incident_reader=recovery.incidents,
    )

    install_queue_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        live_capacity_admission=live_capacity.projector,
    )
