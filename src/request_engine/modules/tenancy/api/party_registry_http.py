"""Composition root for the public Party registry HTTP surface."""

from fastapi import APIRouter, FastAPI, Request

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_reader import (
    PostgresPartyAdministrativeIdentifierReader,
)
from request_engine.modules.tenancy.adapters.db.party_registry_commands import PostgresPartyRegistryCommands
from request_engine.modules.tenancy.adapters.db.party_registry_reader import PostgresPartyLookupReader
from request_engine.modules.tenancy.adapters.db.party_revision_history_reader import (
    PostgresPartyRevisionHistoryReader,
)
from request_engine.modules.tenancy.api.party_administrative_identifier_errors import (
    add_party_administrative_identifier_error_handlers,
)
from request_engine.modules.tenancy.api.party_administrative_identifier_routes import (
    add_party_administrative_identifier_routes,
)
from request_engine.modules.tenancy.api.party_registry_correction_routes import add_party_correction_routes
from request_engine.modules.tenancy.api.party_registry_deactivation_routes import add_party_deactivation_routes
from request_engine.modules.tenancy.api.party_registry_errors import add_party_registry_error_handlers
from request_engine.modules.tenancy.api.party_registry_routes import add_party_registry_routes
from request_engine.modules.tenancy.api.party_revision_routes import add_party_revision_routes
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import ActorResolver


def install_party_registry_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    commands = PostgresPartyRegistryCommands(session_factory)
    identifier_reader = PostgresPartyAdministrativeIdentifierReader(session_factory)
    add_party_registry_error_handlers(app)
    add_party_administrative_identifier_error_handlers(app)
    router = APIRouter(prefix="/v1/parties", tags=["parties"])

    async def authenticated_actor(request: Request) -> ActorContext:
        return await actor_resolver.resolve_actor(request)

    add_party_registry_routes(
        router,
        register_handler=commands,
        add_contact_point_handler=commands,
        confirm_handler=commands,
        lookup_reader=PostgresPartyLookupReader(session_factory),
        actor_resolver=actor_resolver,
    )
    add_party_administrative_identifier_routes(
        router,
        add_handler=commands,
        reader=identifier_reader,
        authenticated_actor=authenticated_actor,
    )
    add_party_correction_routes(
        router,
        rename_handler=commands,
        add_document_handler=commands,
        authenticated_actor=authenticated_actor,
    )
    add_party_deactivation_routes(
        router,
        deactivate_contact_point_handler=commands,
        deactivate_party_handler=commands,
        authenticated_actor=authenticated_actor,
    )
    add_party_revision_routes(
        router,
        revision_history_reader=PostgresPartyRevisionHistoryReader(session_factory),
        rollback_handler=commands,
        authenticated_actor=authenticated_actor,
    )
    app.include_router(router)
