import hashlib
import json
from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.adapters.db.recovery_snapshot_parts import (
    delivery_payload,
    planned_payload,
    queue_payload,
    work_payload,
)
from request_engine.modules.live_capacity.contracts.projection import (
    LiveCapacityProjection,
    ProjectionWorkItem,
)
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSnapshot


def source_snapshot(
    *,
    observed_at: datetime,
    horizon_end: datetime,
    policy_id: UUID,
    policy_revision: int,
    resource_availability_revision: int,
    location_operational_revision: int,
    recovery_source_revision: int,
    intervals: tuple[OperationalAvailabilityInterval, ...],
    planned: tuple[PlannedWorkloadFact, ...],
    work_items: tuple[ProjectionWorkItem, ...],
    queue: QueueProjectionSnapshot,
    delivery: DeliveryProjectionSnapshot,
    projection: LiveCapacityProjection,
    live_pressure_seconds: int,
) -> dict[str, object]:
    """Return the canonical, replayable F4 evidence used by an F5 decision."""

    active_service, open_resource_activity = delivery_payload(delivery)
    return {
        "schema_version": 2,
        "projection_contract_version": 1,
        "observed_at": observed_at.isoformat(),
        "horizon_end": horizon_end.isoformat(),
        "policy": {"id": str(policy_id), "revision": policy_revision},
        "revisions": {
            "resource_availability": resource_availability_revision,
            "location_operational": location_operational_revision,
            "recovery_source": recovery_source_revision,
        },
        "remaining_intervals": [
            {"starts_at": item.starts_at.isoformat(), "ends_at": item.ends_at.isoformat()}
            for item in intervals
        ],
        "planned_commitments": planned_payload(planned),
        "queue_entries": queue_payload(queue),
        "completed_reservation_ids": sorted(str(v) for v in queue.completed_reservation_ids),
        "work_items": work_payload(work_items),
        "active_service": active_service,
        "open_resource_activity": open_resource_activity,
        "projection": {
            "state": projection.state.value,
            "reasons": [reason.value for reason in projection.reasons],
            "remaining_operational_seconds": projection.remaining_operational_seconds,
            "projected_remaining_workload_seconds": projection.projected_remaining_workload_seconds,
            "scheduled_committed_workload_seconds": projection.scheduled_committed_workload_seconds,
            "scheduled_headroom_seconds": projection.scheduled_headroom_seconds,
            "live_headroom_seconds": projection.live_headroom_seconds,
            "live_pressure_seconds": live_pressure_seconds,
        },
    }


def source_fingerprint(payload: dict[str, object]) -> str:
    encoded = canonical_source_json(payload).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def canonical_source_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
