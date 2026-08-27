from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryCommitmentCheckpoint,
    RecoverySourceCheckpoint,
)


def checkpoint_to_json(checkpoint: RecoverySourceCheckpoint) -> dict[str, object]:
    commitments = [
        {
            "reservation_id": str(item.reservation_id),
            "revision": item.revision,
            "starts_at": item.starts_at.isoformat(),
            "ends_at": item.ends_at.isoformat(),
        }
        for item in checkpoint.commitments
    ]
    return {
        "projection_policy_revision": checkpoint.projection_policy_revision,
        "resource_availability_revision": checkpoint.resource_availability_revision,
        "location_operational_revision": checkpoint.location_operational_revision,
        "commitments": commitments,
    }


def checkpoint_from_json(raw: dict[str, object]) -> RecoverySourceCheckpoint:
    commitments = cast(list[dict[str, object]], raw.get("commitments", []))
    return RecoverySourceCheckpoint(
        projection_policy_revision=cast(int, raw["projection_policy_revision"]),
        resource_availability_revision=cast(int, raw["resource_availability_revision"]),
        location_operational_revision=cast(int, raw["location_operational_revision"]),
        commitments=tuple(_commitment_from_json(item) for item in commitments),
    )


def _commitment_from_json(raw: dict[str, object]) -> RecoveryCommitmentCheckpoint:
    return RecoveryCommitmentCheckpoint(
        reservation_id=UUID(cast(str, raw["reservation_id"])),
        revision=cast(int, raw["revision"]),
        starts_at=datetime.fromisoformat(cast(str, raw["starts_at"])),
        ends_at=datetime.fromisoformat(cast(str, raw["ends_at"])),
    )
