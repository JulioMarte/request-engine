from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.arrival_estimates import (
    ArrivalEstimateSource,
    ReservationArrivalEstimate,
)


@dataclass(frozen=True, slots=True)
class RecordArrivalEstimateCommand:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    estimated_arrival_at: datetime
    source_kind: ArrivalEstimateSource
    idempotency_key: str
    expected_revision: int
    allow_subject_override: bool = False


class RecordArrivalEstimateHandler(Protocol):
    async def record_arrival_estimate(
        self,
        command: RecordArrivalEstimateCommand,
    ) -> ReservationArrivalEstimate: ...


async def record_arrival_estimate(
    handler: RecordArrivalEstimateHandler,
    command: RecordArrivalEstimateCommand,
) -> ReservationArrivalEstimate:
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.estimated_arrival_at.tzinfo is None:
        raise ValueError("estimated_arrival_at must be timezone-aware")
    return await handler.record_arrival_estimate(command)
