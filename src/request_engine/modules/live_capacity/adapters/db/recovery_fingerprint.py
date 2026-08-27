import hashlib
import json
from uuid import UUID

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    PlannedWorkloadFact,
)


def source_fingerprint(
    *,
    policy_id: UUID,
    policy_revision: int,
    resource_availability_revision: int,
    location_operational_revision: int,
    intervals: tuple[OperationalAvailabilityInterval, ...],
    planned: tuple[PlannedWorkloadFact, ...],
) -> str:
    payload = {
        "policy_id": str(policy_id),
        "policy_revision": policy_revision,
        "resource_availability_revision": resource_availability_revision,
        "location_operational_revision": location_operational_revision,
        "intervals": [[item.starts_at.isoformat(), item.ends_at.isoformat()] for item in intervals],
        "planned": [
            {
                "reservation_id": str(item.reservation_id),
                "revision": item.reservation_revision,
                "offering_version_id": str(item.offering_version_id),
                "subject_party_id": str(item.subject_party_id),
                "starts_at": item.planned_starts_at.isoformat(),
                "ends_at": item.planned_ends_at.isoformat(),
                "contextual_commitment": item.contextual_commitment,
            }
            for item in sorted(
                planned,
                key=lambda value: (value.planned_starts_at, str(value.reservation_id)),
            )
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
