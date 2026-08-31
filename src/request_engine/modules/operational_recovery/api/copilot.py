from request_engine.modules.operational_recovery.adapters.db.copilot_reader import (
    PostgresCopilotRecoveryIncidentReader,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.platform.db.session import SessionFactory


def build_copilot_recovery_incident_reader(
    session_factory: SessionFactory,
) -> CopilotRecoveryIncidentReader:
    return PostgresCopilotRecoveryIncidentReader(session_factory)
