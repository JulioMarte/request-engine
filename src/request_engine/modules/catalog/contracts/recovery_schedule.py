from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RecoveryLocationExtensionRequest:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    location_id: UUID
    start_at: datetime
    end_at: datetime
    expected_operational_revision: int
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class RecoveryLocationExtensionResult:
    exception_id: UUID
    location_id: UUID
    start_at: datetime
    end_at: datetime
    operational_revision: int


class RecoveryLocationSchedulePort(Protocol):
    async def extend_location_hours(
        self,
        request: RecoveryLocationExtensionRequest,
    ) -> RecoveryLocationExtensionResult: ...
