from uuid import UUID


class LiveCapacityError(Exception):
    """Base semantic error for F4 live-capacity operations."""


class ProjectionScopeAlreadyConfigured(LiveCapacityError):
    def __init__(self, service_queue_id: UUID) -> None:
        self.service_queue_id = service_queue_id
        super().__init__("projection scope already configured")


class ProjectionPolicyNotFound(LiveCapacityError):
    def __init__(self, policy_id: UUID) -> None:
        self.policy_id = policy_id
        super().__init__("projection policy not found")


class ProjectionScopeNotConfigured(LiveCapacityError):
    def __init__(self, service_queue_id: UUID) -> None:
        self.service_queue_id = service_queue_id
        super().__init__("projection scope is not configured")


class InvalidProjectionConfiguration(LiveCapacityError):
    def __init__(self, service_queue_id: UUID) -> None:
        self.service_queue_id = service_queue_id
        super().__init__("projection scope is no longer operationally valid")


class CustomerProjectionTargetNotFound(LiveCapacityError):
    def __init__(self, service_queue_id: UUID) -> None:
        self.service_queue_id = service_queue_id
        super().__init__("customer has no active QueueEntry in the projection queue")


class WorkloadEstimateAlreadyConfigured(LiveCapacityError):
    def __init__(self, workload_classification_id: UUID) -> None:
        self.workload_classification_id = workload_classification_id
        super().__init__("workload estimate already configured")


class InvalidWorkloadEstimateConfiguration(LiveCapacityError):
    def __init__(self, workload_classification_id: UUID) -> None:
        self.workload_classification_id = workload_classification_id
        super().__init__("workload classification is not valid for estimate configuration")


class WorkloadEstimatePolicyNotFound(LiveCapacityError):
    def __init__(self, policy_id: UUID) -> None:
        self.policy_id = policy_id
        super().__init__("workload estimate policy not found")


class PolicyRevisionConflict(LiveCapacityError):
    def __init__(self, expected_revision: int) -> None:
        self.expected_revision = expected_revision
        super().__init__("live-capacity policy revision conflict")
