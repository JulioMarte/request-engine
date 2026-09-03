from fastapi import APIRouter, FastAPI, Request

from request_engine.modules.tenancy.adapters.db.bootstrap_operational_authority_commands import (
    PostgresBootstrapOperationalAuthorityCommands,
)
from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.adapters.db.party_authority_operational_reader import (
    PostgresOperationalAuthorityPartyReader,
)
from request_engine.modules.tenancy.adapters.db.party_authority_reader import (
    PostgresPartyAuthorityReader,
)
from request_engine.modules.tenancy.adapters.db.principal_contact_commands import (
    PostgresPrincipalContactCommands,
)
from request_engine.modules.tenancy.api.bootstrap_authority_routes import (
    create_bootstrap_authority_router,
)
from request_engine.modules.tenancy.api.identity_exchange_http import (
    install_identity_exchange_http,
)
from request_engine.modules.tenancy.api.operational_router import create_operational_router
from request_engine.modules.tenancy.api.party_registry_http import install_party_registry_http
from request_engine.modules.tenancy.api.staff_contact_errors import (
    add_staff_contact_error_handlers,
)
from request_engine.modules.tenancy.api.staff_contact_routes import add_staff_contact_routes
from request_engine.modules.tenancy.contracts.authority import (
    OperationalAuthorityPartyReader,
    PartyAuthorityReader,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext
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
    identity_exchange_fingerprint_key: bytes | None = None,
) -> None:
    """Connect tenancy Party, identity-exchange and staff administration HTTP surfaces."""

    install_party_registry_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    install_identity_exchange_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        fingerprint_key=identity_exchange_fingerprint_key,
    )
    app.include_router(
        create_bootstrap_authority_router(
            handler=PostgresBootstrapOperationalAuthorityCommands(session_factory),
            actor_resolver=actor_resolver,
        )
    )
    add_staff_contact_error_handlers(app)

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    staff_commands = PostgresPrincipalContactCommands(session_factory)
    staff_router = APIRouter(prefix="/v1/staff", tags=["staff"])
    add_staff_contact_routes(
        staff_router,
        register_handler=staff_commands,
        verification_handler=staff_commands,
        confirm_handler=staff_commands,
        authenticated_actor=authenticated_actor,
    )
    app.include_router(staff_router)


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
