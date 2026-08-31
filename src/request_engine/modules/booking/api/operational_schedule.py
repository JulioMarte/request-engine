from request_engine.modules.booking.adapters.db.operational_schedule import (
    PostgresOperationalAssignmentSchedule,
)
from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentSchedulePort,
)
from request_engine.platform.db.session import SessionFactory


def build_operational_assignment_schedule_port(
    session_factory: SessionFactory,
) -> OperationalAssignmentSchedulePort:
    return PostgresOperationalAssignmentSchedule(session_factory)
