from request_engine.modules.booking.adapters.db.recovery_schedule import (
    PostgresRecoveryAssignmentSchedule,
)
from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentSchedulePort,
)
from request_engine.platform.db.session import SessionFactory


def build_recovery_assignment_schedule_port(
    session_factory: SessionFactory,
) -> RecoveryAssignmentSchedulePort:
    return PostgresRecoveryAssignmentSchedule(session_factory)
