from fastapi import FastAPI

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentSchedulePort,
)
from request_engine.modules.communications.contracts.recovery import RecoveryCommunicationPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.adapters.db.store import PostgresRecoveryRepository
from request_engine.modules.operational_recovery.adapters.db.workflow_repository import (
    PostgresRecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.api.errors import (
    operational_recovery_error_handler,
)
from request_engine.modules.operational_recovery.api.router import create_router
from request_engine.modules.operational_recovery.api.workflow_errors import (
    workflow_recovery_error_handler,
)
from request_engine.modules.operational_recovery.api.workflow_router import create_workflow_router
from request_engine.modules.operational_recovery.application.errors import OperationalRecoveryError
from request_engine.modules.operational_recovery.application.service import OperationalRecoveryService
from request_engine.modules.operational_recovery.application.workflow_intake_port import (
    RecoveryIntakeControlPort,
)
from request_engine.modules.operational_recovery.application.workflow_location_port import (
    RecoveryLocationExtensionPort,
)
from request_engine.modules.operational_recovery.application.workflow_service import (
    RecoveryWorkflowService,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryActionConflict,
    RecoveryIncidentNotFound,
    RecoveryIncidentStale,
)
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
    intake: RecoveryIntakeControlPort,
    location_schedule: RecoveryLocationExtensionPort,
    assignment_schedule: RecoveryAssignmentSchedulePort,
) -> None:
    service = OperationalRecoveryService(
        repository=PostgresRecoveryRepository(session_factory),
        capacity=capacity,
        booking=booking,
        communications=communications,
    )
    workflow = RecoveryWorkflowService(
        repository=PostgresRecoveryWorkflowRepository(session_factory),
        intake=intake,
        location_schedule=location_schedule,
        assignment_schedule=assignment_schedule,
        capacity=capacity,
    )
    app.add_exception_handler(OperationalRecoveryError, operational_recovery_error_handler)
    for error_type in (RecoveryIncidentNotFound, RecoveryIncidentStale, RecoveryActionConflict):
        app.add_exception_handler(error_type, workflow_recovery_error_handler)
    app.include_router(create_router(service, actor_resolver))
    app.include_router(create_workflow_router(workflow, actor_resolver))
