from fastapi import FastAPI

from request_engine.modules.catalog.adapters.db.business_info_reader import PostgresBusinessInfoReader
from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.api.router import create_router
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Connect the Catalog module to the HTTP process through its owned surface."""

    app.include_router(
        create_router(
            business_reader=PostgresBusinessInfoReader(session_factory),
            offering_reader=PostgresOfferingCatalogReader(session_factory),
            actor_resolver=actor_resolver,
        )
    )
