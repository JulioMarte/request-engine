import hashlib
import json
from uuid import UUID

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)
from request_engine.modules.live_capacity.contracts.projection import ProjectionWorkItem


def source_fingerprint(
    *,
    policy_id: UUID,
    policy_revision: int,
    resource_availability_revision: int,
    location_operational_revision: int,
    intervals: tuple[OperationalAvailabilityInterval, ...],
    planned: tuple[PlannedWorkloadFact, ...],
    work_items: tuple[ProjectionWorkItem, ...],
    has_open_interruption: bool,
    has_open_resource_activity: bool,
) -> str:
    """Fingerprint every authoritative input that can change an F5 recovery decision."""

    payload = {
        "policy_id": str(policy_id),
        "policy_revision": policy_revision,
        "resource_availability_revision": resource_availability_revision,
        "location_operational_revision": location_operational_revision,
        "has_open_interruption": has_open_interruption,
        "has_open_resource_activity": has_open_resource_activity,
        "intervals": [[item.starts_at.isoformat(), item.ends_at.isoformat()] for item in intervals],
        "planned": [
            {
                "reservation_id": str(item.reservation_id),
                "revision": item.reservation_revision,
                "offering_version_id": str(item.offering_version_id),
                "subject_party_id": str(item.subject_party_id),
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
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
