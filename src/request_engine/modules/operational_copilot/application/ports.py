from typing import Protocol
from uuid import UUID

from request_engine.modules.discovery.contracts.commands import (
    DiscoveryPublicationState,
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotContext,
    CopilotExecutionReceipt,
    CopilotIntent,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_copilot.references import CopilotParsedIntent
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RescheduleProposal,
)
from request_engine.modules.operational_recovery.contracts.queries import RecoveryProposalReader
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryAction
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)


class AtRiskReservationReader(Protocol):
    async def read(self, query: AtRiskReservationsQuery) -> RecoveryCapacityAssessment: ...


class AuthorityPartyReader(Protocol):
    async def resolve_operational_party(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        scope_keys: frozenset[str],
    ) -> UUID | None: ...


class CopilotReferenceResolver(Protocol):
    async def resolve(
        self,
        context: CopilotContext,
        intent: CopilotParsedIntent,
    ) -> CopilotIntent: ...


class RecoveryCommandExecutor(Protocol):
    async def create_proposal(
        self,
        command: CreateRecoveryProposalCommand,
    ) -> RescheduleProposal: ...

    async def execute(self, command: ExecuteRecoveryCommand) -> RecoveryExecution: ...


class RecoveryIntakeExecutor(Protocol):
    async def set_intake(self, command: SetRecoveryIntakeCommand) -> RecoveryAction: ...


class RecoveryExtendDayExecutor(Protocol):
    async def extend_day(self, command: ExtendRecoveryDayCommand) -> RecoveryAction: ...


class DiscoveryPublicationExecutor(Protocol):
    async def publish(
        self,
        command: PublishDiscoverySupplyCommand,
    ) -> DiscoveryPublicationState: ...

    async def revoke(
        self,
        command: RevokeDiscoveryPublicationCommand,
    ) -> DiscoveryPublicationState: ...


class CopilotMutationExecutor(Protocol):
    operation_type: type[object]
    owner_capability: str | None

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt: ...


__all__ = [
    "AtRiskReservationReader",
    "AuthorityPartyReader",
    "CopilotMutationExecutor",
    "CopilotReferenceResolver",
    "DiscoveryPublicationExecutor",
    "RecoveryCommandExecutor",
    "RecoveryExtendDayExecutor",
    "RecoveryIntakeExecutor",
    "RecoveryProposalReader",
]
