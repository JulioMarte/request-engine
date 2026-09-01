from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ArrivalEstimateSource(StrEnum):
    CUSTOMER = "customer"
    OPERATOR = "operator"


@dataclass(frozen=True, slots=True)
class ReservationArrivalEstimate:
    reservation_id: UUID
    reservation_revision: int
    estimate_id: UUID
    estimated_arrival_at: datetime
    source_kind: ArrivalEstimateSource
    asserted_at: datetime
