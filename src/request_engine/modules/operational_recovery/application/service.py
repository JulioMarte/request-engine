from uuid import UUID

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.communications.contracts.recovery import RecoveryCommunicationPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.application.execution_ops import execute_recovery
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.proposal_ops import (
    create_proposal,
    get_proposal,
)
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RescheduleProposal,
)


class OperationalRecoveryService:
    def __init__(
        self,
        *,
        repository: RecoveryRepository,
        capacity: RecoveryCapacitySource,
        booking: RecoveryBookingPort,
        communications: RecoveryCommunicationPort,
    ) -> None:
        self._repository = repository
        self._capacity = capacity
        self._booking = booking
        self._communications = communications

    async def create_proposal(
        self,
        command: CreateRecoveryProposalCommand,
    ) -> RescheduleProposal:
        return await create_proposal(
            command,
            repository=self._repository,
            capacity=self._capacity,
            booking=self._booking,
        )

    async def get_proposal(
        self,
        *,
        organization_id: UUID,
        proposal_id: UUID,
    ) -> RescheduleProposal:
        return await get_proposal(
            repository=self._repository,
            organization_id=organization_id,
            proposal_id=proposal_id,
        )

    async def execute(self, command: ExecuteRecoveryCommand) -> RecoveryExecution:
        return await execute_recovery(
            command,
            repository=self._repository,
            capacity=self._capacity,
            booking=self._booking,
            communications=self._communications,
        )


__all__ = [
    "CreateRecoveryProposalCommand",
    "ExecuteRecoveryCommand",
    "OperationalRecoveryService",
]
