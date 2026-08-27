from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.engine import RowMapping

from request_engine.modules.operational_recovery.adapters.db.target_codec import target_from_json, target_to_json
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryCommitmentCheckpoint,
    RecoverySourceCheckpoint,
    RescheduleProposal,
)


def checkpoint_to_json(checkpoint: RecoverySourceCheckpoint) -> dict[str, object]:
    return {
        "projection_policy_revision": checkpoint.projection_policy_revision,
        "resource_availability_revision": checkpoint.resource_availability_revision,
        "location_operational_revision": checkpoint.location_operational_revision,
        "commitments": [{"reservation_id": str(item.reservation_id), "revision": item.revision, "starts_at": item.starts_at.isoformat(), "ends_at": item.ends_at.isoformat()} for item in checkpoint.commitments],
    }


def checkpoint_from_json(raw: dict[str, object]) -> RecoverySourceCheckpoint:
    commitments = cast(list[dict[str, object]], raw.get("commitments", []))
    return RecoverySourceCheckpoint(
        projection_policy_revision=cast(int, raw["projection_policy_revision"]),
        resource_availability_revision=cast(int, raw["resource_availability_revision"]),
        location_operational_revision=cast(int, raw["location_operational_revision"]),
        commitments=tuple(RecoveryCommitmentCheckpoint(reservation_id=UUID(cast(str, item["reservation_id"])), revision=cast(int, item["revision"]), starts_at=datetime.fromisoformat(cast(str, item["starts_at"])), ends_at=datetime.fromisoformat(cast(str, item["ends_at"]))) for item in commitments),
    )


def affected_to_json(item: AffectedReservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id), "offering_version_id": str(item.offering_version_id), "subject_party_id": str(item.subject_party_id),
        "expected_revision": item.expected_revision, "original_start_at": item.original_start_at.isoformat(), "original_end_at": item.original_end_at.isoformat(),
        "contextual_commitment": item.contextual_commitment, "target": target_to_json(item.target) if item.target is not None else None,
    }


def affected_from_json(raw: dict[str, object]) -> AffectedReservation:
    target = raw.get("target")
    return AffectedReservation(
        reservation_id=UUID(cast(str, raw["reservation_id"])), offering_version_id=UUID(cast(str, raw["offering_version_id"])), subject_party_id=UUID(cast(str, raw["subject_party_id"])),
        expected_revision=cast(int, raw["expected_revision"]), original_start_at=datetime.fromisoformat(cast(str, raw["original_start_at"])), original_end_at=datetime.fromisoformat(cast(str, raw["original_end_at"])),
        target=target_from_json(cast(dict[str, object], target)) if target is not None else None, contextual_commitment=cast(bool, raw.get("contextual_commitment", False)),
    )


def proposal_from_row(row: RowMapping) -> RescheduleProposal:
    raw = cast(dict[str, object], row["snapshot"])
    affected = cast(list[dict[str, object]], raw["affected"])
    return RescheduleProposal(
        id=cast(UUID, row["id"]), service_queue_id=cast(UUID, row["service_queue_id"]), resource_id=cast(UUID, row["resource_id"]), location_id=cast(UUID, row["location_id"]),
        observed_at=cast(datetime, row["observed_at"]), horizon_end=cast(datetime, row["horizon_end"]), source_fingerprint=cast(str, row["source_fingerprint"]),
        source_checkpoint=checkpoint_from_json(cast(dict[str, object], raw["source_checkpoint"])), proposal_fingerprint=cast(str, row["proposal_fingerprint"]),
        executable_capacity_seconds=cast(int, row["executable_capacity_seconds"]), committed_capacity_seconds=cast(int, row["committed_capacity_seconds"]), shortfall_seconds=cast(int, row["shortfall_seconds"]),
        affected=tuple(affected_from_json(item) for item in affected), created_at=cast(datetime, row["created_at"]),
    )


def with_created_at(proposal: RescheduleProposal, created_at: datetime) -> RescheduleProposal:
    return RescheduleProposal(id=proposal.id, service_queue_id=proposal.service_queue_id, resource_id=proposal.resource_id, location_id=proposal.location_id, observed_at=proposal.observed_at, horizon_end=proposal.horizon_end, source_fingerprint=proposal.source_fingerprint, source_checkpoint=proposal.source_checkpoint, proposal_fingerprint=proposal.proposal_fingerprint, executable_capacity_seconds=proposal.executable_capacity_seconds, committed_capacity_seconds=proposal.committed_capacity_seconds, shortfall_seconds=proposal.shortfall_seconds, affected=proposal.affected, created_at=created_at)
