from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryExecution,
    RecoveryTarget,
    RescheduleProposal,
)


class CreateRecoveryProposalBody(BaseModel):
    search_days: int = Field(default=7, ge=1, le=30)


class ExecuteRecoveryBody(BaseModel):
    reservation_id: UUID
    expected_source_fingerprint: str = Field(min_length=1)
    expected_proposal_fingerprint: str = Field(min_length=1)
    notify: bool = True


class RecoveryResourceChoiceView(BaseModel):
    requirement_id: UUID
    resource_id: UUID
    resource_location_assignment_id: UUID | None
    assignment_revision: int | None
    availability_revision: int | None


class RecoveryTargetView(BaseModel):
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[RecoveryResourceChoiceView, ...]
    actionable: bool
    blocked_reason: str | None

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
            actionable=item.actionable,
            blocked_reason=item.blocked_reason,
        )


class AffectedReservationView(BaseModel):
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    expected_revision: int
    original_start_at: datetime
    original_end_at: datetime
    target: RecoveryTargetView | None

    @classmethod
    def from_contract(cls, item: AffectedReservation) -> "AffectedReservationView":
        return cls(
            reservation_id=item.reservation_id,
            offering_version_id=item.offering_version_id,
            subject_party_id=item.subject_party_id,
            expected_revision=item.expected_revision,
            original_start_at=item.original_start_at,
            original_end_at=item.original_end_at,
            target=RecoveryTargetView.from_contract(item.target) if item.target else None,
        )


class RecoveryProposalView(BaseModel):
    id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    horizon_end: datetime
    source_fingerprint: str
    proposal_fingerprint: str
    executable_capacity_seconds: int
    committed_capacity_seconds: int
    shortfall_seconds: int
    affected: tuple[AffectedReservationView, ...]
    created_at: datetime

    @classmethod
    def from_contract(cls, item: RescheduleProposal) -> "RecoveryProposalView":
        return cls(
            id=item.id,
            service_queue_id=item.service_queue_id,
            resource_id=item.resource_id,
            location_id=item.location_id,
            observed_at=item.observed_at,
            horizon_end=item.horizon_end,
            source_fingerprint=item.source_fingerprint,
            proposal_fingerprint=item.proposal_fingerprint,
            executable_capacity_seconds=item.executable_capacity_seconds,
            committed_capacity_seconds=item.committed_capacity_seconds,
            shortfall_seconds=item.shortfall_seconds,
            affected=tuple(AffectedReservationView.from_contract(v) for v in item.affected),
            created_at=item.created_at,
        )


class RecoveryExecutionView(BaseModel):
    id: UUID
    proposal_id: UUID
    reservation_id: UUID
    original_reservation_revision: int
    resulting_reservation_revision: int
    target: RecoveryTargetView
    executed_at: datetime
    notification_requested: bool
    communication_task_id: UUID | None

    @classmethod
    def from_contract(cls, item: RecoveryExecution) -> "RecoveryExecutionView":
        return cls(
            id=item.id,
            proposal_id=item.proposal_id,
            reservation_id=item.reservation_id,
            original_reservation_revision=item.original_reservation_revision,
            resulting_reservation_revision=item.resulting_reservation_revision,
            target=RecoveryTargetView.from_contract(item.target),
            executed_at=item.executed_at,
            notification_requested=item.notification.requested,
            communication_task_id=item.notification.communication_task_id,
        )
