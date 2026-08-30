from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_copilot.adapters.live_capacity_reader import (
    LiveCapacityAtRiskReader,
)
from request_engine.modules.operational_copilot.application.ports import AtRiskReservationReader

__all__ = ["build_live_capacity_at_risk_reader"]


def build_live_capacity_at_risk_reader(source: RecoveryCapacitySource) -> AtRiskReservationReader:
    return LiveCapacityAtRiskReader(source)
