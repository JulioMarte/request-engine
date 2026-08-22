from uuid import UUID


class ResourceAvailabilityRevisionConflict(RuntimeError):
    def __init__(self, resource_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"Resource {resource_id} availability revision conflict: "
            f"expected {expected}, current {actual}"
        )
        self.resource_id = resource_id
        self.expected = expected
        self.actual = actual


class ResourceLocationAssignmentRevisionConflict(RuntimeError):
    def __init__(self, assignment_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"ResourceLocationAssignment {assignment_id} revision conflict: "
            f"expected {expected}, current {actual}"
        )
        self.assignment_id = assignment_id
        self.expected = expected
        self.actual = actual


class ContextualConfigurationConflict(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
