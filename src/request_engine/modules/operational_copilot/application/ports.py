from typing import Protocol
from uuid import UUID

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotExecutionReceipt,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_recovery.contracts.queries import RecoveryProposalReader
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryAction
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)


class AtRiskReservationReader(Protocol):
    async def read(self, query: AtRiskReservationsQuery) -> RecoveryCapacityAssessment: ...


class AuthorityPartyReader(Protocol):
    """Resolve one trusted operational authority party or fail closed with None."""

    async def resolve_operational_party(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        scope_keys: frozenset[str],
    ) -> UUID | None: ...


class RecoveryIntakeExecutor(Protocol):
    async def set_intake(self, command: SetRecoveryIntakeCommand) -> RecoveryAction: ...


class RecoveryExtendDayExecutor(Protocol):
    async def extend_day(self, command: ExtendRecoveryDayCommand) -> RecoveryAction: ...


class CopilotMutationExecutor(Protocol):
    """One explicitly registered bridge from an F6 operation to its owner surface."""

    operation_type: type[object]
    owner_capability: str

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt: ...


__all__ = [
    "AtRiskReservationReader",
    "AuthorityPartyReader",
    "CopilotMutationExecutor",
    "RecoveryExtendDayExecutor",
    "RecoveryIntakeExecutor",
    "RecoveryProposalReader",
]
