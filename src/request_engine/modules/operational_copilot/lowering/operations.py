from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentExtensionRequest,
)
from request_engine.modules.discovery.contracts.commands import (
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.operational_copilot.contracts import AtRiskReservationsQuery
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)
from request_engine.modules.queue.contracts.intake import SetQueueIntakeControlRequest

CopilotOperation = (
    CreateRecoveryProposalCommand
    | ExecuteRecoveryCommand
    | SetRecoveryIntakeCommand
    | ExtendRecoveryDayCommand
    | SetQueueIntakeControlRequest
    | OperationalAssignmentExtensionRequest
    | PublishDiscoverySupplyCommand
    | RevokeDiscoveryPublicationCommand
    | AtRiskReservationsQuery
)
