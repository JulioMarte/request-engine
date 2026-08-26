from datetime import datetime

from pydantic import BaseModel

from request_engine.modules.live_capacity.contracts.customer_projection import (
    CustomerLiveCapacityProjection,
)


class CustomerLiveCapacityProjectionView(BaseModel):
    observed_at: datetime
    entries_ahead: int
    estimated_wait_seconds: int | None
    estimated_start: datetime | None

    @classmethod
    def from_contract(
        cls, item: CustomerLiveCapacityProjection
    ) -> "CustomerLiveCapacityProjectionView":
        return cls(
            observed_at=item.observed_at,
            entries_ahead=item.entries_ahead,
            estimated_wait_seconds=item.estimated_wait_seconds,
            estimated_start=item.estimated_start,
        )
