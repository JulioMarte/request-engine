from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EvaluateIntakeQuery:
    organization_id: UUID
    service_queue_id: UUID
    workload_classification_id: UUID
