import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.contracts.projection import LiveCapacityProjection, ProjectionWorkItem
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

    active = delivery.active_service
    activity = delivery.open_resource_activity
    payload: dict[str, object] = {
        "schema_version": 1,
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
        "planned_commitments": [
            {
                "reservation_id": str(item.reservation_id),
                "revision": item.reservation_revision,
                "offering_version_id": str(item.offering_version_id),
                "subject_party_id": str(item.subject_party_id) if item.subject_party_id else None,
                "starts_at": item.planned_starts_at.isoformat(),
                "ends_at": item.planned_ends_at.isoformat(),
                "duration_seconds": item.planned_duration_seconds,
                "contextual_commitment": item.contextual_commitment,
            }
            for item in sorted(
                planned,
                key=lambda value: (value.planned_starts_at, str(value.reservation_id)),
            )
        ],
        "queue_entries": [
            {
                "queue_entry_id": str(item.queue_entry_id),
                "reservation_id": str(item.reservation_id) if item.reservation_id else None,
                "status": item.status,
                "arrived_at": item.arrived_at.isoformat(),
                "admitted_at": item.admitted_at.isoformat(),
                "called_at": item.called_at.isoformat() if item.called_at else None,
                "expected_workload_classification_id": (
                    str(item.expected_workload_classification_id)
                    if item.expected_workload_classification_id
                    else None
                ),
            }
            for item in queue.entries
        ],
        "completed_reservation_ids": sorted(
            (str(value) for value in queue.completed_reservation_ids)
        ),
        "work_items": [
            {
                "key": str(item.key),
                "duration_seconds": item.duration_seconds,
                "source": item.source.value,
                "queue_entry_id": str(item.queue_entry_id) if item.queue_entry_id else None,
                "reservation_id": str(item.reservation_id) if item.reservation_id else None,
                "active_service_seconds": item.active_service_seconds,
            }
            for item in work_items
        ],
        "active_service": (
            {
                "service_session_id": str(active.service_session_id),
                "queue_entry_id": str(active.queue_entry_id),
                "resource_id": str(active.resource_id),
                "location_id": str(active.location_id),
                "status": active.status,
                "actual_workload_classification_id": (
                    str(active.actual_workload_classification_id)
                    if active.actual_workload_classification_id
                    else None
                ),
                "started_at": active.started_at.isoformat(),
                "active_service_seconds": active.active_service_seconds,
                "has_open_interruption": active.has_open_interruption,
            }
            if active is not None
            else None
        ),
        "open_resource_activity": (
            {
                "resource_activity_id": str(activity.resource_activity_id),
                "resource_id": str(activity.resource_id),
                "location_id": str(activity.location_id) if activity.location_id else None,
                "started_at": activity.started_at.isoformat(),
                "has_known_end": activity.has_known_end,
            }
            if activity is not None
            else None
        ),
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
    return payload


def source_fingerprint(payload: dict[str, object]) -> str:
    """Hash the exact immutable snapshot persisted with the recovery proposal."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def canonical_source_json(payload: dict[str, object]) -> str:
    """Expose canonical serialization for replay/audit tests without duplicating hash rules."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
