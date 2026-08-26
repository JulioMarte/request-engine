from uuid import UUID


class LiveServiceError(Exception):
    """Base semantic rejection for F3 live operations."""


class QueueEntryNotCallable(LiveServiceError):
    def __init__(self, queue_entry_id: UUID, status: str) -> None:
        super().__init__(f"QueueEntry {queue_entry_id} cannot start service from {status}")
        self.queue_entry_id = queue_entry_id
        self.status = status


class LiveServiceRevisionConflict(LiveServiceError):
    def __init__(self, aggregate_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"revision conflict for {aggregate_id}: expected {expected}, actual {actual}"
        )
        self.aggregate_id = aggregate_id
        self.expected = expected
        self.actual = actual


class ServiceSessionNotFound(LiveServiceError):
    def __init__(self, service_session_id: UUID) -> None:
        super().__init__(f"ServiceSession {service_session_id} not found")
        self.service_session_id = service_session_id


class ServiceSessionNotActionable(LiveServiceError):
    def __init__(self, service_session_id: UUID, status: str, action: str) -> None:
        super().__init__(f"ServiceSession {service_session_id} is {status}; cannot {action}")
        self.service_session_id = service_session_id
        self.status = status
        self.action = action


class ResourceExecutionUnavailable(LiveServiceError):
    def __init__(self, resource_id: UUID, reason: str) -> None:
        super().__init__(f"Resource {resource_id} unavailable for live execution: {reason}")
        self.resource_id = resource_id
        self.reason = reason


class WorkloadClassificationUnavailable(LiveServiceError):
    def __init__(self, workload_id: UUID) -> None:
        super().__init__(f"Operational workload classification {workload_id} is unavailable")
        self.workload_id = workload_id


class ResourceActivityNotFound(LiveServiceError):
    def __init__(self, activity_id: UUID) -> None:
        super().__init__(f"ResourceActivity {activity_id} not found")
        self.activity_id = activity_id
