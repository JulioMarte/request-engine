"""Shared route doubles for the staff contact route tests (DB-free)."""

from typing import cast
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.errors import capability_required_handler
from request_engine.modules.tenancy.api.staff_contact_errors import (
    add_staff_contact_error_handlers,
)
from request_engine.modules.tenancy.api.staff_contact_routes import add_staff_contact_routes
from request_engine.modules.tenancy.application.commands import (
    confirm_principal_contact,
    register_principal_contact,
    request_principal_contact_verification,
)
from request_engine.modules.tenancy.contracts.staff_contacts import (
    PrincipalContact,
    PrincipalContactVerificationIssued,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired


class RecordingCommands:
    """Recording double satisfying the three staff contact handler protocols."""

    def __init__(
        self, outcome: PrincipalContact | PrincipalContactVerificationIssued | Exception
    ) -> None:
        self.register_commands: list[
            register_principal_contact.RegisterPrincipalContactCommand
        ] = []
        self.request_commands: list[
            request_principal_contact_verification.RequestPrincipalContactVerificationCommand
        ] = []
        self.confirm_commands: list[confirm_principal_contact.ConfirmPrincipalContactCommand] = []
        self._outcome = outcome

    def _failure(self) -> None:
        if isinstance(self._outcome, Exception):
            raise self._outcome

    async def register_principal_contact(
        self, command: register_principal_contact.RegisterPrincipalContactCommand
    ) -> PrincipalContact:
        self.register_commands.append(command)
        self._failure()
        return cast(PrincipalContact, self._outcome)

    async def request_principal_contact_verification(
        self,
        command: request_principal_contact_verification.RequestPrincipalContactVerificationCommand,
    ) -> PrincipalContactVerificationIssued:
        self.request_commands.append(command)
        self._failure()
        return cast(PrincipalContactVerificationIssued, self._outcome)

    async def confirm_principal_contact(
        self, command: confirm_principal_contact.ConfirmPrincipalContactCommand
    ) -> PrincipalContact:
        self.confirm_commands.append(command)
        self._failure()
        return cast(PrincipalContact, self._outcome)


def actor(*capabilities: str, kind: PrincipalKind = PrincipalKind.HUMAN) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(capabilities),
        principal_kind=kind,
    )


def app(
    actor_context: ActorContext,
    outcome: PrincipalContact | PrincipalContactVerificationIssued | Exception,
) -> tuple[FastAPI, RecordingCommands]:
    commands = RecordingCommands(outcome)
    router = APIRouter(prefix="/v1/staff")
    add_staff_contact_routes(
        router,
        register_handler=commands,
        verification_handler=commands,
        confirm_handler=commands,
        authenticated_actor=_FixedActorResolver(actor_context).resolve_actor,
    )
    fastapi_app = FastAPI()
    fastapi_app.include_router(router)
    add_staff_contact_error_handlers(fastapi_app)
    fastapi_app.add_exception_handler(CapabilityRequired, capability_required_handler)
    return fastapi_app, commands


class _FixedActorResolver:
    def __init__(self, actor_context: ActorContext) -> None:
        self._actor = actor_context

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


def client(fastapi_app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test")


def contact() -> PrincipalContact:
    return PrincipalContact(
        contact_id=uuid4(),
        channel="whatsapp",
        normalized_value="+18095551234",
        verified=False,
        active=True,
    )
