from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReadStaffLiveCapacityQuery:
    organization_id: UUID
    service_queue_id: UUID
