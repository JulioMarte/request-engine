from fastapi import APIRouter, FastAPI, Request

from request_engine.modules.tenancy.adapters.db.controller_policy_adoption_commands import (
    PostgresControllerPolicyAdoptionCommands,
)
from request_engine.modules.tenancy.api.controller_policy_adoption_routes import (
    add_controller_policy_adoption_error_handlers,
    add_controller_policy_adoption_platform_routes,
)
from request_engine.modules.tenancy.application.commands.controller_policy_adoption import (
    ControllerPolicyAdoptionReader,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.platform_http import PlatformActorResolver


def install_platform_controller_policy_adoption_http(
    app: FastAPI,
    *,
    write_session_factory: SessionFactory,
    read_session_factory: SessionFactory,
    actor_resolver: PlatformActorResolver,
) -> None:
    """Mount the Tenancy-owned apply command on the private platform control API."""

    commands = PostgresControllerPolicyAdoptionCommands(
        write_session_factory,
        platform_session_factory=write_session_factory,
    )
    reader: ControllerPolicyAdoptionReader = PostgresControllerPolicyAdoptionCommands(
        read_session_factory
    )

    async def authenticated_actor(request: Request) -> PlatformActorContext:
        return await actor_resolver.resolve_platform_actor(request)

    add_controller_policy_adoption_error_handlers(app)
    router = APIRouter(tags=["Platform controller policy adoption"])
    add_controller_policy_adoption_platform_routes(
        router,
        commands=commands,
        reader=reader,
        authenticated_actor=authenticated_actor,
    )
    app.include_router(router)
