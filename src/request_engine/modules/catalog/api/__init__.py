from fastapi import FastAPI

from request_engine.modules.catalog.adapters.db.business_info_reader import (
    PostgresBusinessInfoReader,
)
from request_engine.modules.catalog.adapters.db.location_creation_commands import (
    PostgresLocationCreationCommands,
)
from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.adapters.db.operational_config_commands import (
    PostgresOperationalConfigCommands,
)
from request_engine.modules.catalog.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.catalog.api.operational_errors import (
    catalog_operational_error_handler,
)
from request_engine.modules.catalog.api.operational_profile_router import (
    create_operational_profile_router,
)
from request_engine.modules.catalog.api.operational_schedule_router import (
    create_operational_schedule_router,
)
from request_engine.modules.catalog.api.router import create_router
from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    LocationOperationalRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Connect Catalog read and operational command surfaces to the HTTP process."""

    app.add_exception_handler(
        LocationOperationalRevisionConflict,
        catalog_operational_error_handler,
    )
    app.add_exception_handler(
        CatalogConfigurationConflict,
        catalog_operational_error_handler,
    )
    app.include_router(
        create_router(
            business_reader=PostgresBusinessInfoReader(session_factory),
            offering_reader=PostgresOfferingCatalogReader(session_factory),
            actor_resolver=actor_resolver,
        )
    )
    profile = PostgresOperationalProfileCommands(session_factory)
    app.include_router(
        create_operational_profile_router(
            create_handler=PostgresLocationCreationCommands(session_factory),
            update_handler=profile,
            contacts_handler=profile,
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_operational_schedule_router(
            hours_handler=PostgresOperationalConfigCommands(session_factory),
            exception_handler=profile,
            terms_handler=profile,
            actor_resolver=actor_resolver,
        )
    )
