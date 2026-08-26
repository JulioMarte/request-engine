from fastapi import FastAPI

from request_engine.modules.booking.contracts.live_capacity import OperationalAvailabilitySource
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSource
from request_engine.modules.live_capacity.adapters.db.customer_projection_reader import (
    PostgresCustomerLiveCapacityReader,
)
from request_engine.modules.live_capacity.adapters.db.intake_reader import (
    PostgresIntakeEvaluationReader,
)
from request_engine.modules.live_capacity.adapters.db.live_capacity_reader import (
    PostgresLiveCapacityReader,
)
from request_engine.modules.live_capacity.api.customer_projection_router import (
    create_customer_projection_router,
)
from request_engine.modules.live_capacity.api.errors import live_capacity_error_handler
from request_engine.modules.live_capacity.api.intake_router import create_intake_router
from request_engine.modules.live_capacity.api.projection_policy_router import (
    create_projection_policy_router,
)
from request_engine.modules.live_capacity.api.projection_router import create_projection_router
from request_engine.modules.live_capacity.api.workload_policy_router import (
    create_workload_policy_router,
)
from request_engine.modules.live_capacity.application.errors import LiveCapacityError
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSource
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    booking_source: OperationalAvailabilitySource,
    queue_source: QueueProjectionSource,
    delivery_source: DeliveryProjectionSource,
) -> None:
    sources = LiveCapacitySources(
        booking=booking_source,
        queue=queue_source,
        delivery=delivery_source,
    )
    app.add_exception_handler(LiveCapacityError, live_capacity_error_handler)
    app.include_router(create_projection_policy_router(session_factory, actor_resolver))
    app.include_router(create_workload_policy_router(session_factory, actor_resolver))
    app.include_router(
        create_projection_router(
            PostgresLiveCapacityReader(session_factory, sources),
            actor_resolver,
        )
    )
    app.include_router(
        create_customer_projection_router(
            PostgresCustomerLiveCapacityReader(session_factory, sources),
            actor_resolver,
        )
    )
    app.include_router(
        create_intake_router(
            PostgresIntakeEvaluationReader(session_factory, sources),
            actor_resolver,
        )
    )
