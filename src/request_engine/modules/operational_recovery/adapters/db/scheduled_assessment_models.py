from dataclasses import dataclass
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident


@dataclass(frozen=True, slots=True)
class ScheduledAssessmentCommit:
    applied: bool
    stale: bool
    incident: RecoveryIncident | None
    proposal_id: UUID | None = None
