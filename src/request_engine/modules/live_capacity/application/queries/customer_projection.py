from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReadCustomerLiveCapacityQuery:
    organization_id: UUID
    principal_id: UUID
    service_queue_id: UUID
    subject_party_id: UUID
    allow_subject_override: bool = False
