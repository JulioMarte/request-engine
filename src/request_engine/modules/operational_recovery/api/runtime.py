from dataclasses import dataclass

from request_engine.modules.operational_recovery.application.service import (
    OperationalRecoveryService,
)
from request_engine.modules.operational_recovery.application.workflow_service import (
    RecoveryWorkflowService,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)


@dataclass(frozen=True, slots=True)
class OperationalRecoveryRuntime:
    service: OperationalRecoveryService
    workflow: RecoveryWorkflowService
    incidents: CopilotRecoveryIncidentReader
