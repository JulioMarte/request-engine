from uuid import UUID

from request_engine.modules.queue.application.errors import QueueError


class QueueEntryNotClassifiable(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        message = f"QueueEntry {entry_id} cannot change expected workload from status {status}"
        super().__init__(message)
        self.entry_id = entry_id
        self.status = status


class WorkloadClassificationNotFound(QueueError):
    def __init__(self, workload_id: UUID) -> None:
        super().__init__(f"OperationalWorkloadClassification {workload_id} not found")
        self.workload_id = workload_id


class WorkloadClassificationRevisionConflict(QueueError):
    def __init__(self, workload_id: UUID, expected: int, actual: int) -> None:
        super().__init__(f"OperationalWorkloadClassification {workload_id} revision conflict")
        self.workload_id = workload_id
        self.expected = expected
        self.actual = actual


class WorkloadClassificationInactive(QueueError):
    def __init__(self, workload_id: UUID) -> None:
        super().__init__(f"OperationalWorkloadClassification {workload_id} is inactive")
        self.workload_id = workload_id


class WorkloadKeyConflict(QueueError):
    def __init__(self, workload_key: str) -> None:
        super().__init__(f"Operational workload key {workload_key!r} already exists")
        self.workload_key = workload_key
