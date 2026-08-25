from fastapi import APIRouter

from request_engine.modules.queue.adapters.db.live_queue_commands import (
    PostgresLiveQueueCommands,
)
from request_engine.modules.queue.adapters.db.live_queue_reader import PostgresLiveQueueReader
from request_engine.modules.queue.api.live_classification_router import (
    create_live_classification_router,
)
from request_engine.modules.queue.api.live_mutation_router import create_live_mutation_router
from request_engine.modules.queue.api.live_read_router import create_live_read_router
from request_engine.platform.security.http import ActorResolver


def create_live_router(
    *,
    commands: PostgresLiveQueueCommands,
    reader: PostgresLiveQueueReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["live-queues"])
    router.include_router(create_live_mutation_router(commands, actor_resolver))
    router.include_router(create_live_classification_router(commands, actor_resolver))
    router.include_router(create_live_read_router(reader, actor_resolver))
    return router
