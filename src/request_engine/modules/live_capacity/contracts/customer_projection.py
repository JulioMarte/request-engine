from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CustomerLiveCapacityProjection:
    observed_at: datetime
    entries_ahead: int
    estimated_wait_seconds: int | None
    estimated_start: datetime | None
