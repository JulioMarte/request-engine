from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.booking.contracts.arrival_estimates import (
    ArrivalEstimateSource,
    ReservationArrivalEstimate,
)


def estimate_to_json(state: ReservationArrivalEstimate) -> dict[str, object]:
    return {
        "reservation_id": str(state.reservation_id),
        "reservation_revision": state.reservation_revision,
        "estimate_id": str(state.estimate_id),
        "estimated_arrival_at": state.estimated_arrival_at.isoformat(),
        "source_kind": state.source_kind.value,
        "asserted_at": state.asserted_at.isoformat(),
    }


def estimate_from_json(data: dict[str, object]) -> ReservationArrivalEstimate:
    return ReservationArrivalEstimate(
        reservation_id=UUID(cast(str, data["reservation_id"])),
        reservation_revision=cast(int, data["reservation_revision"]),
        estimate_id=UUID(cast(str, data["estimate_id"])),
        estimated_arrival_at=datetime.fromisoformat(cast(str, data["estimated_arrival_at"])),
        source_kind=ArrivalEstimateSource(cast(str, data["source_kind"])),
        asserted_at=datetime.fromisoformat(cast(str, data["asserted_at"])),
    )
