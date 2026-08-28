from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class RecoveryIntakeControlRequest:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
    accepting: bool
    idempotency_key: str
    reason: str
    effective_until: datetime | None


@dataclass(frozen=True)
class RecoveryIntakeControlResult:
    service_queue_id: UUID
    revision: int
    accepting: bool


class RecoveryIntakeControlPort(Protocol):
    async def set_recovery_intake_control(
        self,
        request: RecoveryIntakeControlRequest,
    ) -> RecoveryIntakeControlResult: ...
