from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacitySource,
)
from request_engine.modules.operational_copilot.contracts import AtRiskReservationsQuery


class LiveCapacityAtRiskReader:
    def __init__(self, source: RecoveryCapacitySource) -> None:
        self._source = source

    async def read(self, query: AtRiskReservationsQuery) -> RecoveryCapacityAssessment:
        return await self._source.assess_recovery_capacity(
            organization_id=query.organization_id,
            service_queue_id=query.service_queue_id,
        )
