from fastapi import FastAPI

from request_engine.modules.communications.adapters.db.organization_channel_policy_commands import (
    PostgresOrganizationChannelPolicyCommands,
)
from request_engine.modules.communications.adapters.db.reminder_commands import (
    PostgresReminderCommands,
)
from request_engine.modules.communications.adapters.db.reminder_reader import (
    PostgresReminderPlanReader,
)
from request_engine.modules.communications.api.channel_policy_router import (
    create_channel_policy_router,
)
from request_engine.modules.communications.api.errors import communications_error_handler
from request_engine.modules.communications.api.router import create_router
from request_engine.modules.communications.domain.errors import CommunicationsError
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Connect the public ReminderPlan surface to the HTTP process."""

    commands = PostgresReminderCommands(session_factory)
    app.add_exception_handler(CommunicationsError, communications_error_handler)
    app.include_router(
        create_router(
            commands=commands,
            reader=PostgresReminderPlanReader(session_factory),
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_channel_policy_router(
            handler=PostgresOrganizationChannelPolicyCommands(session_factory),
            actor_resolver=actor_resolver,
        )
    )
