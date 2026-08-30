from dataclasses import dataclass

from request_engine.modules.operational_recovery.application.service import OperationalRecoveryService
from request_engine.modules.operational_recovery.application.workflow_service import RecoveryWorkflowService


@dataclass(frozen=True, slots=True)
class OperationalRecoveryRuntime:
    service: OperationalRecoveryService
    workflow: RecoveryWorkflowService
