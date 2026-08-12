from fastapi import FastAPI

from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.adapters.db.request_definition_reader import (
    PostgresRequestDefinitionResolver,
)
from request_engine.modules.requests.adapters.db.request_reader import PostgresRequestReader
from request_engine.modules.requests.api.errors import request_error_handler
from request_engine.modules.requests.api.router import create_router
from request_engine.modules.requests.application.errors import RequestError
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Connect the Request module to the HTTP process through its owned surface."""

    commands = PostgresRequestCommands(session_factory)
    app.add_exception_handler(RequestError, request_error_handler)
    app.include_router(
        create_router(
            create_handler=commands,
            record_result_handler=commands,
            complete_handler=commands,
            cancel_handler=commands,
            fail_handler=commands,
            reader=PostgresRequestReader(session_factory),
            definition_resolver=PostgresRequestDefinitionResolver(session_factory),
            actor_resolver=actor_resolver,
        )
    )
