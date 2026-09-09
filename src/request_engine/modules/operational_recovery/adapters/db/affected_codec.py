from datetime import datetime
from typing import cast
from uuid import UUID

from request_engine.modules.operational_recovery.adapters.db.target_codec import (
    target_from_json,
    target_to_json,
)
from request_engine.modules.operational_recovery.contracts.models import AffectedReservation


def affected_to_json(item: AffectedReservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id),
        "offering_version_id": str(item.offering_version_id),
        "subject_party_id": str(item.subject_party_id),
        "expected_revision": item.expected_revision,
        "original_start_at": item.original_start_at.isoformat(),
        "original_end_at": item.original_end_at.isoformat(),
        "target": target_to_json(item.target) if item.target is not None else None,
        "replacement_target": (
            target_to_json(item.replacement_target) if item.replacement_target is not None else None
        ),
    }


def affected_from_json(raw: dict[str, object]) -> AffectedReservation:
    target = raw.get("target")
    replacement = raw.get("replacement_target")
    return AffectedReservation(
        reservation_id=UUID(cast(str, raw["reservation_id"])),
        offering_version_id=UUID(cast(str, raw["offering_version_id"])),
        subject_party_id=UUID(cast(str, raw["subject_party_id"])),
        expected_revision=cast(int, raw["expected_revision"]),
        original_start_at=datetime.fromisoformat(cast(str, raw["original_start_at"])),
        original_end_at=datetime.fromisoformat(cast(str, raw["original_end_at"])),
        target=(target_from_json(cast(dict[str, object], target)) if target is not None else None),
        replacement_target=(
            target_from_json(cast(dict[str, object], replacement))
            if replacement is not None
            else None
        ),
    )
