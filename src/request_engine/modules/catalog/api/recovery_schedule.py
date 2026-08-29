from request_engine.modules.catalog.adapters.db.recovery_schedule import (
    PostgresRecoveryLocationSchedule,
)
from request_engine.modules.catalog.contracts.recovery_schedule import RecoveryLocationSchedulePort
from request_engine.platform.db.session import SessionFactory


def build_recovery_location_schedule_port(
    session_factory: SessionFactory,
) -> RecoveryLocationSchedulePort:
    return PostgresRecoveryLocationSchedule(session_factory)
