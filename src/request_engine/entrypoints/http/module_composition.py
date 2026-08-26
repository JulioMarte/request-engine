from fastapi import FastAPI

from request_engine.modules.booking.api import install_http as install_booking_http
from request_engine.modules.catalog.api import install_http as install_catalog_http
from request_engine.modules.communications.api import install_http as install_communications_http
from request_engine.modules.delivery.api import install_http as install_delivery_http
from request_engine.modules.queue.api import QueueSlotOfferHttpPorts
from request_engine.modules.queue.api import install_http as install_queue_http
from request_engine.modules.requests.api import install_http as install_requests_http
from request_engine.modules.tenancy.api import build_party_authority_reader
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
    install_delivery_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    install_communications_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
