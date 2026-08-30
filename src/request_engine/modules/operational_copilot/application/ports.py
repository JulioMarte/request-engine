from typing import Protocol

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_copilot.contracts import AtRiskReservationsQuery
from request_engine.modules.operational_recovery.contracts.queries import RecoveryProposalReader


class AtRiskReservationReader(Protocol):
    async def read(self, query: AtRiskReservationsQuery) -> RecoveryCapacityAssessment: ...


__all__ = ["AtRiskReservationReader", "RecoveryProposalReader"]
