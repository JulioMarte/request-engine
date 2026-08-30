from typing import Protocol
from uuid import UUID

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_copilot.contracts import AtRiskReservationsQuery
from request_engine.modules.operational_recovery.contracts.queries import RecoveryProposalReader


class AtRiskReservationReader(Protocol):
    async def read(self, query: AtRiskReservationsQuery) -> RecoveryCapacityAssessment: ...


class AuthorityPartyReader(Protocol):
    """Trusted-boundary authority resolution from tenant-owned representation truth.

    Returns the single party the principal currently holds operational authority
    for, or None when authority is absent or ambiguous; callers must refuse
    rather than guess. Satisfied structurally by the tenancy module's published
    operational authority reader.
    """

    async def resolve_operational_party(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        scope_keys: frozenset[str],
    ) -> UUID | None: ...


__all__ = ["AtRiskReservationReader", "AuthorityPartyReader", "RecoveryProposalReader"]
