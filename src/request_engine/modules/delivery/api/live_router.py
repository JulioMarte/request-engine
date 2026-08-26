from fastapi import APIRouter

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.adapters.db.resource_activity_reader import (
    PostgresResourceActivityReader,
)
from request_engine.modules.delivery.adapters.db.service_session_reader import (
    PostgresServiceSessionReader,
)
from request_engine.modules.delivery.api.resource_activity_routes import (
    create_resource_activity_router,
)
from request_engine.modules.delivery.api.service_session_routes import (
    create_service_session_router,
)
from request_engine.platform.security.http import ActorResolver


def create_live_service_router(
    *,
    operations: PostgresLiveServiceOperations,
    session_reader: PostgresServiceSessionReader,
    activity_reader: PostgresResourceActivityReader,
    actor_resolver: ActorResolver,
) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["live-service"])
    router.include_router(create_service_session_router(operations, session_reader, actor_resolver))
    router.include_router(
        create_resource_activity_router(operations, activity_reader, actor_resolver)
    )
    return router
