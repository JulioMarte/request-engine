from fastapi import APIRouter

from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.api.triage_hold_router import create_recall_hold_router
from request_engine.modules.queue.api.triage_operator_router import create_operator_select_router
from request_engine.modules.queue.api.triage_release_router import create_release_recall_hold_router
from request_engine.modules.queue.api.triage_skip_router import create_skip_router
from request_engine.platform.security.http import ActorResolver


def create_triage_router(
    commands: PostgresQueueTriageCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["live-queues"])
    router.include_router(create_operator_select_router(commands, actor_resolver))
    router.include_router(create_recall_hold_router(commands, actor_resolver))
    router.include_router(create_release_recall_hold_router(commands, actor_resolver))
    router.include_router(create_skip_router(commands, actor_resolver))
    return router
