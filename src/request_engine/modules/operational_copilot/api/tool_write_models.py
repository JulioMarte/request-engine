from datetime import datetime
from uuid import UUID

from pydantic import Field

from request_engine.modules.operational_copilot.api.models import F6RequestBody
from request_engine.modules.operational_copilot.contracts import (
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
    SetRecoveryIntakeIntent,
)


class CreateRecoveryProposalBody(F6RequestBody):
    service_queue_id: UUID
    search_days: int = Field(default=7, ge=1, le=30)

    def to_intent(self) -> CreateRecoveryProposalIntent:
        return CreateRecoveryProposalIntent(self.service_queue_id, self.search_days)


class ExecuteRecoveryBody(F6RequestBody):
    proposal_id: UUID
    reservation_id: UUID
    expected_source_fingerprint: str | None = None
    expected_proposal_fingerprint: str | None = None
    allow_subject_override: bool = False
    notify: bool = True

    def to_intent(self) -> ExecuteRecoveryIntent:
        return ExecuteRecoveryIntent(**self.model_dump())


class SetRecoveryIntakeBody(F6RequestBody):
    incident_id: UUID
    accepting: bool
    expected_source_revision: int = Field(ge=0)
    expected_intake_revision: int = Field(ge=0)
    reason: str | None = None
    effective_until: datetime | None = None

    def to_intent(self) -> SetRecoveryIntakeIntent:
        return SetRecoveryIntakeIntent(**self.model_dump())


class ExtendRecoveryDayBody(F6RequestBody):
    incident_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_source_revision: int = Field(ge=0)
    expected_location_operational_revision: int = Field(ge=0)
    expected_resource_availability_revision: int = Field(ge=0)
    reason: str

    def to_intent(self) -> ExtendRecoveryDayIntent:
        return ExtendRecoveryDayIntent(**self.model_dump())


class PublishDiscoverySupplyBody(F6RequestBody):
    offering_id: UUID
    location_id: UUID
    effective_start: datetime
    effective_end: datetime | None = None
    resource_id: UUID | None = None
    provider_visibility: str = "hidden"
    effective_start_is_resolved_now: bool = False

    def to_intent(self) -> PublishDiscoverySupplyIntent:
        return PublishDiscoverySupplyIntent(**self.model_dump())


class RevokeDiscoveryPublicationBody(F6RequestBody):
    publication_id: UUID
    expected_revision: int = Field(ge=0)

    def to_intent(self) -> RevokeDiscoveryPublicationIntent:
        return RevokeDiscoveryPublicationIntent(**self.model_dump())
