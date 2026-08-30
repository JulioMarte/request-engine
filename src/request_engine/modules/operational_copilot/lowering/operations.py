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

CopilotOperation = (
    CreateRecoveryProposalCommand
    | ExecuteRecoveryCommand
    | SetRecoveryIntakeCommand
    | ExtendRecoveryDayCommand
    | PublishDiscoverySupplyCommand
    | RevokeDiscoveryPublicationCommand
    | AtRiskReservationsQuery
)
