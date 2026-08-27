from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RescheduleProposal,
)


@dataclass(frozen=True, slots=True)
class RecoveryExecutionRecord:
    execution: RecoveryExecution
    command_fingerprint: str
    created: bool


class RecoveryRepository(Protocol):
    async def create_proposal(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        proposal: RescheduleProposal,
    ) -> RescheduleProposal: ...

    async def get_proposal(
        self, *, organization_id: UUID, proposal_id: UUID
    ) -> RescheduleProposal | None: ...

    async def prepare_execution(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        idempotency_key: str,
        command_fingerprint: str,
        proposal: RescheduleProposal,
        reservation_id: UUID,
        notification_requested: bool,
    ) -> RecoveryExecutionRecord: ...

    async def succeed_execution(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        resulting_revision: int,
    ) -> RecoveryExecution: ...

    async def reject_execution(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        failure_code: str,
    ) -> RecoveryExecution: ...

    async def attach_communication_task(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        communication_task_id: UUID,
    ) -> RecoveryExecution: ...
