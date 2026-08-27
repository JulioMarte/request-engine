from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SetRecoveryIntakeCommand:
    organization_id: UUID
    principal_id: UUID
    incident_id: UUID
    expected_source_revision: int
    accepting: bool
    idempotency_key: str
    reason: str | None = None
    effective_until: datetime | None = None
