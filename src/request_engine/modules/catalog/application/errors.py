from uuid import UUID


class LocationOperationalRevisionConflict(RuntimeError):
    def __init__(self, location_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"Location {location_id} operational revision conflict: "
            f"expected {expected}, current {actual}"
        )
        self.location_id = location_id
        self.expected = expected
        self.actual = actual


class CatalogConfigurationConflict(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OfferingBookingPolicyRevisionConflict(RuntimeError):
    def __init__(self, offering_version_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"OfferingVersion {offering_version_id} booking policy revision conflict: "
            f"expected {expected}, current {actual}"
        )
        self.offering_version_id = offering_version_id
        self.expected = expected
        self.actual = actual
