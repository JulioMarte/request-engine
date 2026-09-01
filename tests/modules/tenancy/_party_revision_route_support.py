"""Shared route doubles for the party revision route tests (DB-free)."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request

from request_engine.entrypoints.http.errors import capability_required_handler
from request_engine.modules.tenancy.api.party_registry_errors import (
    add_party_registry_error_handlers,
)
from request_engine.modules.tenancy.api.party_revision_routes import add_party_revision_routes
from request_engine.modules.tenancy.application.commands.rollback_party_identity import (
    RollbackPartyIdentityHandler,
)
from request_engine.modules.tenancy.application.queries.party_revision_history import (
    PartyRevisionHistoryReader,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyRevision,
    PartySourceKind,
    RegisteredParty,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import CapabilityRequired


class FixedActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


def actor(*capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(), principal_id=uuid4(), capabilities=frozenset(capabilities)
    )


def revision(number: int) -> PartyRevision:
    return PartyRevision(
        revision=number,
        change_kind="renamed",
        display_name="Jose Perez",
        active=True,
        source_kind=PartySourceKind.OPERATOR,
        platform="reception_web",
        actor_principal_id=uuid4(),
        attributed_operator_principal_id=None,
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        snapshot={"display_name": "Jose Perez", "active": True},
    )


def party() -> RegisteredParty:
    return RegisteredParty(
        party_id=uuid4(),
        organization_id=uuid4(),
        party_kind="person",
        display_name="Jose Perez",
        active=True,
        contact_points=(),
        documents=(),
    )


def app(
    actor_context: ActorContext,
    reader: PartyRevisionHistoryReader,
    rollbacks: RollbackPartyIdentityHandler,
) -> FastAPI:
    resolver = FixedActorResolver(actor_context)
    router = APIRouter(prefix="/v1/parties")
    add_party_revision_routes(
        router,
        revision_history_reader=reader,
        rollback_handler=rollbacks,
        authenticated_actor=resolver.resolve_actor,
    )
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    add_party_registry_error_handlers(fastapi_app)
    fastapi_app.add_exception_handler(CapabilityRequired, capability_required_handler)
    return fastapi_app
