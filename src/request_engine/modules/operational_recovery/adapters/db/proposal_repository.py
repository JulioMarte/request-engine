from uuid import UUID

from request_engine.modules.operational_recovery.adapters.db.proposal_store import (
    create_proposal,
    find_proposal_replay,
    get_proposal,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.platform.db.session import SessionFactory


class ProposalRepositoryMixin:
    _session_factory: SessionFactory

    async def find_proposal_replay(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        idempotency_key: str,
        command_fingerprint: str,
    ) -> RescheduleProposal | None:
        return await find_proposal_replay(
            self._session_factory,
            organization_id=organization_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint,
        )

    async def create_proposal(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        idempotency_key: str,
        command_fingerprint: str,
        proposal: RescheduleProposal,
    ) -> RescheduleProposal:
        return await create_proposal(
            self._session_factory,
            organization_id=organization_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint,
            proposal=proposal,
        )

    async def get_proposal(
        self,
        *,
        organization_id: UUID,
        proposal_id: UUID,
    ) -> RescheduleProposal | None:
        return await get_proposal(
            self._session_factory,
            organization_id=organization_id,
            proposal_id=proposal_id,
        )
