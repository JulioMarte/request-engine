from fastapi import FastAPI

from request_engine.modules.queue.adapters.db.leave_queue_commands import PostgresLeaveQueueCommands
from request_engine.modules.queue.adapters.db.service_queue_catalog_reader import (
    PostgresServiceQueueCatalogReader,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_reader import PostgresServiceQueueReader
from request_engine.modules.queue.api.errors import queue_error_handler
from request_engine.modules.queue.api.router import create_router
from request_engine.modules.queue.application.errors import QueueError
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Connect the Queue module to the HTTP process through its owned surface."""

    app.add_exception_handler(QueueError, queue_error_handler)
    app.include_router(
        create_router(
            commands=PostgresServiceQueueCommands(session_factory),
            leave_commands=PostgresLeaveQueueCommands(session_factory),
            reader=PostgresServiceQueueReader(session_factory),
            catalog_reader=PostgresServiceQueueCatalogReader(session_factory),
            actor_resolver=actor_resolver,
        )
    )
