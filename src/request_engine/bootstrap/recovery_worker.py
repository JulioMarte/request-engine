from request_engine.modules.booking.api.live_capacity import (
    build_live_capacity_source as build_booking_live_capacity_source,
)
from request_engine.modules.booking.api.recovery import build_recovery_booking_port
from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.communications.adapters.db.recovery_port import (
    PostgresRecoveryCommunicationPort,
)
from request_engine.modules.delivery.api.live_capacity import (
    build_live_capacity_source as build_delivery_live_capacity_source,
)
from request_engine.modules.live_capacity.api.recovery import build_recovery_capacity_source
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.adapters.db import (
    recovery_autonomy_policy_reader,
)
from request_engine.modules.operational_recovery.adapters.db.recovery_autonomy_automation import (
    PostgresRecoveryRescheduleAutonomy,
)
from request_engine.modules.operational_recovery.adapters.db.recovery_impact_automation import (
    PostgresRecoveryImpactAutomation,
)
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_fence import (
    RecoverySourceRevisionReader,
)
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_store import (
    PostgresScheduledAssessmentStore,
)
from request_engine.modules.operational_recovery.adapters.db.store import (
    PostgresRecoveryRepository,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_repository import (
    PostgresRecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.adapters.worker.scheduled_assessment import (
    RecoveryAssessmentScheduledHandler,
)
from request_engine.modules.queue.api.live_capacity import (
    build_live_capacity_source as build_queue_live_capacity_source,
)
from request_engine.platform.db.session import SessionFactory


def build_recovery_impact_automation(
    session_factory: SessionFactory,
) -> PostgresRecoveryImpactAutomation:
    return PostgresRecoveryImpactAutomation(
        session_factory,
        PostgresRecoveryCommunicationPort(session_factory),
    )


def build_recovery_reschedule_autonomy(
    session_factory: SessionFactory,
    capacity: RecoveryCapacitySource,
    booking: RecoveryBookingPort,
) -> PostgresRecoveryRescheduleAutonomy:
    return PostgresRecoveryRescheduleAutonomy(
        session_factory,
        recovery_autonomy_policy_reader.PostgresRecoveryAutonomyPolicyReader(session_factory),
        PostgresRecoveryWorkflowRepository(session_factory),
        PostgresRecoveryRepository(session_factory),
        booking,
        capacity,
        PostgresRecoveryCommunicationPort(session_factory),
    )


def build_recovery_assessment_handler(
    session_factory: SessionFactory,
) -> RecoveryAssessmentScheduledHandler:
    capacity = build_recovery_capacity_source(
        session_factory,
        booking_source=build_booking_live_capacity_source(),
        queue_source=build_queue_live_capacity_source(),
        delivery_source=build_delivery_live_capacity_source(),
    )
    booking = build_recovery_booking_port(session_factory)
    autonomy = build_recovery_reschedule_autonomy(session_factory, capacity, booking)
    return RecoveryAssessmentScheduledHandler(
        capacity,
        booking,
        PostgresScheduledAssessmentStore(session_factory),
        RecoverySourceRevisionReader(session_factory),
        build_recovery_impact_automation(session_factory),
        autonomy,
    )
