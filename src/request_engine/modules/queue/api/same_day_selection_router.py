from fastapi import APIRouter

from request_engine.modules.queue.adapters.db.same_day_selection_commands import (
    PostgresSameDaySelectionCommands,
)
from request_engine.modules.queue.api.same_day_dispatch_router import (
    create_same_day_dispatch_router,
)
from request_engine.modules.queue.api.same_day_hold_router import create_same_day_hold_router
from request_engine.platform.security.http import ActorResolver


def create_same_day_selection_router(
    commands: PostgresSameDaySelectionCommands,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["live-queues"])
    router.include_router(create_same_day_dispatch_router(commands, actor_resolver))
    router.include_router(create_same_day_hold_router(commands, actor_resolver))
    return router
