from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryCommitmentCheckpoint,
    RecoverySourceCheckpoint,
    RecoveryTarget,
)


class RecoveryResourceChoiceView(BaseModel):
    requirement_id: UUID
    resource_id: UUID
    resource_location_assignment_id: UUID | None
    assignment_revision: int | None
    availability_revision: int | None


class RecoveryCommitmentCheckpointView(BaseModel):
    reservation_id: UUID
    revision: int
    starts_at: datetime
    ends_at: datetime

    @classmethod
    def from_contract(
        cls,
        item: RecoveryCommitmentCheckpoint,
    ) -> "RecoveryCommitmentCheckpointView":
        return cls(
            reservation_id=item.reservation_id,
            revision=item.revision,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
        )


class RecoverySourceCheckpointView(BaseModel):
    projection_policy_revision: int
    resource_availability_revision: int
    location_operational_revision: int
    recovery_source_revision: int
    commitments: tuple[RecoveryCommitmentCheckpointView, ...]

    @classmethod
    def from_contract(
        cls,
        item: RecoverySourceCheckpoint,
    ) -> "RecoverySourceCheckpointView":
        return cls(
            projection_policy_revision=item.projection_policy_revision,
            resource_availability_revision=item.resource_availability_revision,
            location_operational_revision=item.location_operational_revision,
            recovery_source_revision=item.recovery_source_revision,
            commitments=tuple(
                RecoveryCommitmentCheckpointView.from_contract(value) for value in item.commitments
            ),
        )


class RecoveryTargetView(BaseModel):
    start_at: datetime
    end_at: datetime
    location_id: UUID
    resources: tuple[RecoveryResourceChoiceView, ...]
    planned_duration_minutes: int
    amount: Decimal
    currency: str
    location_operational_revision: int
    configuration_fingerprint: str

    @classmethod
    def from_contract(cls, item: RecoveryTarget) -> "RecoveryTargetView":
        return cls(
            start_at=item.start_at,
            end_at=item.end_at,
            location_id=item.location_id,
            resources=tuple(
                RecoveryResourceChoiceView(
                    requirement_id=value.requirement_id,
                    resource_id=value.resource_id,
                    resource_location_assignment_id=value.resource_location_assignment_id,
                    assignment_revision=value.assignment_revision,
                    availability_revision=value.availability_revision,
                )
                for value in item.resources
            ),
            planned_duration_minutes=item.planned_duration_minutes,
            amount=item.amount,
            currency=item.currency,
            location_operational_revision=item.location_operational_revision,
            configuration_fingerprint=item.configuration_fingerprint,
        )


class AffectedReservationView(BaseModel):
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    expected_revision: int
    original_start_at: datetime
    original_end_at: datetime
    target: RecoveryTargetView | None
    replacement_target: RecoveryTargetView | None

    @classmethod
    def from_contract(cls, item: AffectedReservation) -> "AffectedReservationView":
        target = item.target
        replacement = item.replacement_target
        return cls(
            reservation_id=item.reservation_id,
            offering_version_id=item.offering_version_id,
            subject_party_id=item.subject_party_id,
            expected_revision=item.expected_revision,
            original_start_at=item.original_start_at,
            original_end_at=item.original_end_at,
            target=RecoveryTargetView.from_contract(target) if target is not None else None,
            replacement_target=(
                RecoveryTargetView.from_contract(replacement) if replacement is not None else None
            ),
        )
