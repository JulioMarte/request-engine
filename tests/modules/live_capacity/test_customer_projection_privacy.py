from datetime import UTC, datetime

from request_engine.modules.live_capacity.api.customer_projection_models import (
    CustomerLiveCapacityProjectionView,
)
from request_engine.modules.live_capacity.contracts.customer_projection import (
    CustomerLiveCapacityProjection,
)


def test_customer_projection_serializes_only_privacy_safe_fields() -> None:
    view = CustomerLiveCapacityProjectionView.from_contract(
        CustomerLiveCapacityProjection(
            observed_at=datetime(2026, 8, 26, 14, 0, tzinfo=UTC),
            entries_ahead=3,
            estimated_wait_seconds=None,
            estimated_start=None,
        )
    )

    payload = view.model_dump(mode="json")

    assert set(payload) == {
        "observed_at",
        "entries_ahead",
        "estimated_wait_seconds",
        "estimated_start",
    }
    forbidden = {
        "subject_party_id",
        "queue_entry_id",
        "service_session_id",
        "resource_id",
        "location_id",
        "workload_classification_id",
        "source",
        "sample_count",
        "state",
        "reasons",
        "live_headroom_seconds",
        "projected_remaining_workload_seconds",
    }
    assert forbidden.isdisjoint(payload)
