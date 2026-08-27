from fastapi import FastAPI

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.communications.contracts.recovery import RecoveryCommunicationPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.adapters.db.store import PostgresRecoveryRepository
from request_engine.modules.operational_recovery.api.errors import operational_recovery_error_handler
from request_engine.modules.operational_recovery.api.router import create_router
from request_engine.modules.operational_recovery.application.errors import OperationalRecoveryError
from request_engine.modules.operational_recovery.application.service import OperationalRecoveryService
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    capacity: RecoveryCapacitySource,
    booking: RecoveryBookingPort,
    communications: RecoveryCommunicationPort,
) -> None:
    service = OperationalRecoveryService(
        repository=PostgresRecoveryRepository(session_factory),
        capacity=capacity,
        booking=booking,
        communications=communications,
    )
    app.add_exception_handler(OperationalRecoveryError, operational_recovery_error_handler)
    app.include_router(create_router(service, actor_resolver))
