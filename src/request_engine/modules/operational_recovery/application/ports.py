from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RescheduleProposal,
)


class RecoveryExecutionUnit(Protocol):
    async def existing(self) -> tuple[RecoveryExecution, str] | None: ...

    async def record(
        self,
        *,
        principal_id: UUID,
        idempotency_key: str,
        command_fingerprint: str,
        proposal: RescheduleProposal,
        reservation_id: UUID,
        resulting_revision: int,
        notification_requested: bool,
    ) -> RecoveryExecution: ...


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

    def execution_unit(
        self,
        *,
        organization_id: UUID,
        proposal_id: UUID,
        reservation_id: UUID,
    ) -> AbstractAsyncContextManager[RecoveryExecutionUnit]: ...

    async def attach_communication_task(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        communication_task_id: UUID,
    ) -> RecoveryExecution: ...
