from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ServiceSessionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class InterruptionKind(StrEnum):
    EMERGENCY = "emergency"
    BREAK = "break"
    ADMINISTRATIVE = "administrative"
    OTHER_OPERATIONAL = "other_operational"


class ResourceActivityKind(StrEnum):
    BREAK = "break"
    EMERGENCY = "emergency"
    ADMINISTRATIVE = "administrative"
    OTHER_OPERATIONAL = "other_operational"


@dataclass(frozen=True, slots=True)
class ServiceSession:
    id: UUID
    queue_entry_id: UUID
    resource_id: UUID
    location_id: UUID
    status: ServiceSessionStatus
    started_at: datetime
    completed_at: datetime | None
    actual_workload_classification_id: UUID | None
    revision: int


@dataclass(frozen=True, slots=True)
class ServiceSessionInterruption:
    id: UUID
    service_session_id: UUID
    kind: InterruptionKind
    started_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class ServiceSessionOperationalSnapshot:
    session: ServiceSession
    observed_at: datetime
    wall_clock_seconds: int
    interruption_seconds: int
    active_service_seconds: int
    interruptions: tuple[ServiceSessionInterruption, ...]


@dataclass(frozen=True, slots=True)
class ResourceActivity:
    id: UUID
    resource_id: UUID
    location_id: UUID | None
    kind: ResourceActivityKind
    started_at: datetime
    ended_at: datetime | None
    revision: int
