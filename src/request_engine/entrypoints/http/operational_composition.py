from fastapi import FastAPI

from request_engine.modules.booking.api import (
    install_operational_http as install_booking_operational_http,
)
from request_engine.modules.catalog.api import (
    install_operational_http as install_catalog_operational_http,
)
from request_engine.modules.tenancy.api import (
    install_operational_http as install_tenancy_operational_http,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_operational_modules(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Compose authenticated operator-only configuration surfaces."""

    install_tenancy_operational_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    install_catalog_operational_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    install_booking_operational_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
