from typing import Protocol
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal


class RecoveryProposalReader(Protocol):
    async def get_proposal(
        self,
        *,
        organization_id: UUID,
        proposal_id: UUID,
    ) -> RescheduleProposal: ...
