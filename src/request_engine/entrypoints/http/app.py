from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.errors import (
    integrity_error_handler,
    request_error_handler,
)
from request_engine.entrypoints.http.requests import create_requests_router
from request_engine.entrypoints.http.security import ActorResolver
from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.adapters.db.request_definition_reader import (
    PostgresRequestDefinitionResolver,
)
from request_engine.modules.requests.adapters.db.request_reader import PostgresRequestReader
from request_engine.modules.requests.application.errors import RequestError
from request_engine.platform.db.session import SessionFactory


def create_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> FastAPI:
    """Compose the HTTP process around explicit database and authentication dependencies."""

    app = FastAPI(
        title="Request Engine",
        version="0.1.0",
        description=(
            "Headless customer-operations API. Authentication/tenant authority is supplied "
            "by the deployment ActorResolver; request bodies never select their own tenant."
        ),
    )
    commands = PostgresRequestCommands(session_factory)
    reader = PostgresRequestReader(session_factory)
    definition_resolver = PostgresRequestDefinitionResolver(session_factory)

    app.add_exception_handler(RequestError, request_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.include_router(
        create_requests_router(
            commands=commands,
            reader=reader,
            definition_resolver=definition_resolver,
            actor_resolver=actor_resolver,
        )
    )
    return app
