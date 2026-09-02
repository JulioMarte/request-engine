from fastapi import APIRouter

from request_engine.modules.queue.api.same_day_dispatch_router import (
    create_same_day_dispatch_router,
)
from request_engine.modules.queue.api.same_day_hold_router import create_same_day_hold_router
from request_engine.modules.queue.application.commands.operator_select import OperatorSelectExecutor
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldExecutor
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldExecutor,
)
from request_engine.modules.queue.application.commands.skip_queue_head import SkipQueueHeadExecutor
from request_engine.platform.security.http import ActorResolver


def create_same_day_selection_router(
    *,
    operator_select_executor: OperatorSelectExecutor,
    skip_executor: SkipQueueHeadExecutor,
    recall_hold_executor: RecallHoldExecutor,
    release_hold_executor: ReleaseRecallHoldExecutor,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["live-queues"])
    router.include_router(
        create_same_day_dispatch_router(
            operator_select_executor=operator_select_executor,
            skip_executor=skip_executor,
            actor_resolver=actor_resolver,
        )
    )
    router.include_router(
        create_same_day_hold_router(
            recall_hold_executor=recall_hold_executor,
            release_hold_executor=release_hold_executor,
            actor_resolver=actor_resolver,
        )
    )
    return router
