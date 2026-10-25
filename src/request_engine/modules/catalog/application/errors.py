from uuid import UUID


class CatalogInvalidInput(ValueError):
    """Caller-controlled catalog input violates an owner command contract."""


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


class OfferingRevisionConflict(RuntimeError):
    def __init__(self, offering_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"Offering {offering_id} revision conflict: expected {expected}, current {actual}"
        )
        self.offering_id = offering_id
        self.expected = expected
        self.actual = actual


class OfferingVersionSuperseded(RuntimeError):
    """The caller's expected current OfferingVersion is no longer the latest one."""

    def __init__(self, offering_id: UUID, expected: UUID, actual: UUID) -> None:
        super().__init__(
            f"Offering {offering_id} current version is {actual}, not the expected {expected}"
        )
        self.offering_id = offering_id
        self.expected = expected
        self.actual = actual
