from fastapi import FastAPI

from request_engine.entrypoints.http.tenancy_composition import install_tenancy_http
from request_engine.modules.booking.api import install_http as install_booking_http
from request_engine.modules.catalog.api import install_http as install_catalog_http
from request_engine.modules.requests.api import install_http as install_requests_http
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_foundation_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    appointment_option_signing_key: bytes,
    identity_exchange_fingerprint_key: bytes | None,
) -> None:
    party_authority_reader = install_tenancy_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        identity_exchange_fingerprint_key=identity_exchange_fingerprint_key,
    )
    install_requests_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    install_catalog_http(app, session_factory=session_factory, actor_resolver=actor_resolver)
    install_booking_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        party_authority_reader=party_authority_reader,
        appointment_option_signing_key=appointment_option_signing_key,
    )
