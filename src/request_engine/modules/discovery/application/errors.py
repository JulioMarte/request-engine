from uuid import UUID


class DiscoveryConfigurationConflict(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DiscoveryRevisionConflict(RuntimeError):
    def __init__(self, aggregate_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"discovery revision conflict for {aggregate_id}: expected {expected}, current {actual}"
        )
        self.aggregate_id = aggregate_id
        self.expected = expected
        self.actual = actual
