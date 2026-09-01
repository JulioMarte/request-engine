from fastapi import APIRouter, FastAPI

from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.adapters.db.party_authority_operational_reader import (
    PostgresOperationalAuthorityPartyReader,
)
from request_engine.modules.tenancy.adapters.db.party_authority_reader import (
    PostgresPartyAuthorityReader,
)
from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.adapters.db.party_registry_reader import (
    PostgresPartyLookupReader,
)
from request_engine.modules.tenancy.api.operational_router import create_operational_router
from request_engine.modules.tenancy.api.party_registry_errors import (
    add_party_registry_error_handlers,
)
from request_engine.modules.tenancy.api.party_registry_routes import add_party_registry_routes
from request_engine.modules.tenancy.contracts.authority import (
    OperationalAuthorityPartyReader,
    PartyAuthorityReader,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def build_party_authority_reader(session_factory: SessionFactory) -> PartyAuthorityReader:
    """Compose the tenant-owned Party authority reader behind the module API surface."""

    return PostgresPartyAuthorityReader(session_factory)


def build_operational_authority_party_reader(
    session_factory: SessionFactory,
) -> OperationalAuthorityPartyReader:
    """Compose the fail-closed operational Party authority reader for composition roots."""

    return PostgresOperationalAuthorityPartyReader(session_factory)


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Connect the public tenancy party registry HTTP surface."""

    commands = PostgresPartyRegistryCommands(session_factory)
    add_party_registry_error_handlers(app)
    router = APIRouter(prefix="/v1/parties", tags=["parties"])
    add_party_registry_routes(
        router,
        register_handler=commands,
        add_contact_point_handler=commands,
        confirm_handler=commands,
        lookup_reader=PostgresPartyLookupReader(session_factory),
        actor_resolver=actor_resolver,
    )
    app.include_router(router)


def install_operational_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    commands = PostgresOperationalProfileCommands(session_factory)
    app.include_router(
        create_operational_router(
            profile_handler=commands,
            contacts_handler=commands,
            actor_resolver=actor_resolver,
        )
    )
