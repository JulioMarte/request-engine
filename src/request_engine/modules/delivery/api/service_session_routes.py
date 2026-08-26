from fastapi import APIRouter

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.adapters.db.service_session_reader import (
    PostgresServiceSessionReader,
)
from request_engine.modules.delivery.api.service_session_pause_resume_routes import (
    create_pause_resume_router,
)
from request_engine.modules.delivery.api.service_session_read_routes import (
    create_service_session_read_router,
)
from request_engine.modules.delivery.api.service_session_start_complete_routes import (
    create_start_complete_router,
)
from request_engine.platform.security.http import ActorResolver


def create_service_session_router(
    operations: PostgresLiveServiceOperations,
    reader: PostgresServiceSessionReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter()
    router.include_router(create_start_complete_router(operations, actor_resolver))
    router.include_router(create_pause_resume_router(operations, actor_resolver))
    router.include_router(create_service_session_read_router(reader, actor_resolver))
    return router
