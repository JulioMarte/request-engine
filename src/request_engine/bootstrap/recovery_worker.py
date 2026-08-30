from request_engine.modules.booking.api.live_capacity import (
    build_live_capacity_source as build_booking_live_capacity_source,
)
from request_engine.modules.booking.api.recovery import build_recovery_booking_port
from request_engine.modules.communications.adapters.db.recovery_port import (
    PostgresRecoveryCommunicationPort,
)
from request_engine.modules.delivery.api.live_capacity import (
    build_live_capacity_source as build_delivery_live_capacity_source,
)
from request_engine.modules.live_capacity.api.recovery import build_recovery_capacity_source
from request_engine.modules.operational_recovery.adapters.db.recovery_impact_automation import (
    PostgresRecoveryImpactAutomation,
)
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_fence import (
    RecoverySourceRevisionReader,
)
from request_engine.modules.operational_recovery.adapters.db.scheduled_assessment_store import (
    PostgresScheduledAssessmentStore,
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


def build_recovery_assessment_handler(
    session_factory: SessionFactory,
) -> RecoveryAssessmentScheduledHandler:
    capacity = build_recovery_capacity_source(
        session_factory,
        booking_source=build_booking_live_capacity_source(),
        queue_source=build_queue_live_capacity_source(),
        delivery_source=build_delivery_live_capacity_source(),
    )
    return RecoveryAssessmentScheduledHandler(
        capacity,
        build_recovery_booking_port(session_factory),
        PostgresScheduledAssessmentStore(session_factory),
        RecoverySourceRevisionReader(session_factory),
        build_recovery_impact_automation(session_factory),
    )
