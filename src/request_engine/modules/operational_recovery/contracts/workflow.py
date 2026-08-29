from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class RecoveryIncidentStatus(StrEnum):
    OPEN = "open"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"


class RecoveryImpactKind(StrEnum):
    DELAY = "delay"
    CAPACITY_SHORTFALL = "capacity_shortfall"
    INDETERMINATE = "indeterminate"


class RecoveryActionKind(StrEnum):
    STOP_INTAKE = "stop_intake"
    REOPEN_INTAKE = "reopen_intake"
    EXTEND_DAY = "extend_day"
    RESCHEDULE = "reschedule"
    REPLACE_RESOURCE = "replace_resource"
    COMMUNICATE_IMPACT = "communicate_impact"


class RecoveryActionStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    PARTIALLY_APPLIED = "partially_applied"


@dataclass(frozen=True, slots=True)
class RecoveryIncident:
    id: UUID
    organization_id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    status: RecoveryIncidentStatus
    impact_kind: RecoveryImpactKind
    escalation_level: int
    source_revision: int
    source_fingerprint: str
    current_proposal_id: UUID | None
    opened_at: datetime
    last_assessed_at: datetime
    resolved_at: datetime | None
    revision: int


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    id: UUID
    organization_id: UUID
    incident_id: UUID
    action_kind: RecoveryActionKind
    status: RecoveryActionStatus
    principal_id: UUID
    idempotency_key: str
    command_fingerprint: str
    expected_source_revision: int
    payload: Mapping[str, object]
    owner_steps: Mapping[str, object]
    failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RecoveryIncidentNotFound(Exception):
    def __init__(self, incident_id: UUID) -> None:
        super().__init__(f"RecoveryIncident {incident_id} not found")
        self.incident_id = incident_id


class RecoveryIncidentStale(Exception):
    def __init__(self, incident_id: UUID, expected: int, actual: int) -> None:
        super().__init__(f"RecoveryIncident {incident_id} source revision changed")
        self.incident_id = incident_id
        self.expected = expected
        self.actual = actual


class RecoveryActionConflict(Exception):
    pass


class RecoveryOwnerRevisionConflict(Exception):
    def __init__(
        self,
        *,
        owner: str,
        scope_id: UUID,
        expected: int,
        actual: int,
    ) -> None:
        super().__init__(f"Recovery owner {owner} revision changed")
        self.owner = owner
        self.scope_id = scope_id
        self.expected = expected
        self.actual = actual
