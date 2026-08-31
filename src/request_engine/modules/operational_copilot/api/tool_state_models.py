from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.discovery.contracts.commands import DiscoveryPublicationState
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident
from request_engine.modules.queue.contracts.intake import QueueIntakeControlState


class QueueIntakeView(BaseModel):
    service_queue_id: UUID
    accepting: bool
    reason: str | None
    effective_until: datetime | None
    revision: int
    updated_at: datetime

    @classmethod
    def from_state(cls, value: QueueIntakeControlState) -> "QueueIntakeView":
        return cls(
            service_queue_id=value.service_queue_id,
            accepting=value.accepting,
            reason=value.reason,
            effective_until=value.effective_until,
            revision=value.revision,
            updated_at=value.updated_at,
        )


class RecoveryIncidentView(BaseModel):
    incident_id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    source_revision: int
    source_fingerprint: str
    current_proposal_id: UUID | None
    revision: int
    status: str

    @classmethod
    def from_incident(cls, value: RecoveryIncident) -> "RecoveryIncidentView":
        return cls(
            incident_id=value.id,
            service_queue_id=value.service_queue_id,
            resource_id=value.resource_id,
            location_id=value.location_id,
            source_revision=value.source_revision,
            source_fingerprint=value.source_fingerprint,
            current_proposal_id=value.current_proposal_id,
            revision=value.revision,
            status=value.status.value,
        )


class DiscoveryPublicationView(BaseModel):
    publication_id: UUID
    offering_id: UUID
    location_id: UUID
    resource_id: UUID | None
    effective_start: datetime
    effective_end: datetime | None
    provider_visibility: str
    status: str
    revision: int

    @classmethod
    def from_state(cls, value: DiscoveryPublicationState) -> "DiscoveryPublicationView":
        return cls(
            publication_id=value.id,
            offering_id=value.offering_id,
            location_id=value.location_id,
            resource_id=value.resource_id,
            effective_start=value.effective_start,
            effective_end=value.effective_end,
            provider_visibility=value.provider_visibility,
            status=value.status,
            revision=value.revision,
        )


class AtRiskReservationView(BaseModel):
    reservation_id: UUID
    reservation_revision: int
    planned_starts_at: datetime
    planned_ends_at: datetime


class AtRiskAssessmentView(BaseModel):
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    horizon_end: datetime
    shortfall_seconds: int
    source_fingerprint: str
    recovery_source_revision: int
    affected: list[AtRiskReservationView]

    @classmethod
    def from_assessment(cls, value: RecoveryCapacityAssessment) -> "AtRiskAssessmentView":
        return cls(
            service_queue_id=value.service_queue_id,
            resource_id=value.resource_id,
            location_id=value.location_id,
            observed_at=value.observed_at,
            horizon_end=value.horizon_end,
            shortfall_seconds=value.shortfall_seconds,
            source_fingerprint=value.source_fingerprint,
            recovery_source_revision=value.checkpoint.recovery_source_revision,
            affected=[
                AtRiskReservationView(
                    reservation_id=item.reservation_id,
                    reservation_revision=item.reservation_revision,
                    planned_starts_at=item.planned_starts_at,
                    planned_ends_at=item.planned_ends_at,
                )
                for item in value.affected_commitments
            ],
        )
