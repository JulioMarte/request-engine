"""Composition root for the S0d federated identity HTTP surface."""

from fastapi import APIRouter, FastAPI

from request_engine.modules.tenancy.adapters.db.identity_exchange_adopt import (
    PostgresPortableIdentityAdopter,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_match import (
    PostgresPortableIdentityMatcher,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_publish import (
    PostgresPortableProfilePublisher,
)
from request_engine.modules.tenancy.api.identity_exchange_errors import (
    add_identity_exchange_error_handlers,
)
from request_engine.modules.tenancy.api.identity_exchange_routes import (
    add_identity_exchange_routes,
)
from request_engine.modules.tenancy.api.portable_profile_routes import add_portable_profile_routes
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_identity_exchange_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    fingerprint_key: bytes | None,
) -> None:
    add_identity_exchange_error_handlers(app)
    publisher = PostgresPortableProfilePublisher(session_factory, fingerprint_key)
    matcher = PostgresPortableIdentityMatcher(session_factory, fingerprint_key)
    adopter = PostgresPortableIdentityAdopter(session_factory, fingerprint_key)

    party_router = APIRouter(prefix="/v1/parties", tags=["parties"])
    add_portable_profile_routes(
        party_router,
        publisher=publisher,
        actor_resolver=actor_resolver,
    )
    app.include_router(party_router)

    exchange_router = APIRouter(prefix="/v1/identity-exchange", tags=["identity-exchange"])
    add_identity_exchange_routes(
        exchange_router,
        matcher=matcher,
        adopter=adopter,
        actor_resolver=actor_resolver,
    )
    app.include_router(exchange_router)
