from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
)


class SetRecoveryIntakeBody(BaseModel):
    expected_source_revision: int = Field(gt=0)
    expected_intake_revision: int = Field(gt=0)
    accepting: bool
    reason: str | None = None
    effective_until: datetime | None = None


class ExtendRecoveryDayBody(BaseModel):
    expected_source_revision: int = Field(gt=0)
    authority_party_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_location_operational_revision: int = Field(gt=0)
    expected_resource_availability_revision: int = Field(gt=0)
    reason: str = Field(min_length=1)


class RecoveryActionView(BaseModel):
    id: UUID
    incident_id: UUID
    action_kind: RecoveryActionKind
    status: RecoveryActionStatus
    expected_source_revision: int
    payload: dict[str, Any]
    owner_steps: dict[str, Any]
    failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_contract(cls, action: RecoveryAction) -> "RecoveryActionView":
        return cls(
            id=action.id,
            incident_id=action.incident_id,
            action_kind=action.action_kind,
            status=action.status,
            expected_source_revision=action.expected_source_revision,
            payload=dict(action.payload),
            owner_steps=dict(action.owner_steps),
            failure_code=action.failure_code,
            created_at=action.created_at,
            started_at=action.started_at,
            completed_at=action.completed_at,
        )
