from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class QueueIntakeControlState:
    service_queue_id: UUID
    accepting: bool
    reason: str | None
    effective_until: datetime | None
    revision: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SetQueueIntakeControlRequest:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
    accepting: bool
    expected_revision: int
    idempotency_key: str
    reason: str | None = None
    effective_until: datetime | None = None


class QueueIntakeStopped(Exception):
    def __init__(self, service_queue_id: UUID, reason: str | None) -> None:
        super().__init__(f"ServiceQueue {service_queue_id} is not accepting new intake")
        self.service_queue_id = service_queue_id
        self.reason = reason


class QueueIntakeRevisionConflict(Exception):
    def __init__(self, service_queue_id: UUID, expected: int, actual: int) -> None:
        super().__init__(f"ServiceQueue {service_queue_id} intake revision conflict")
        self.service_queue_id = service_queue_id
        self.expected = expected
        self.actual = actual


class QueueIntakeControlPort(Protocol):
    async def get_intake_control(
        self,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> QueueIntakeControlState: ...

    async def set_intake_control(
        self,
        request: SetQueueIntakeControlRequest,
    ) -> QueueIntakeControlState: ...
