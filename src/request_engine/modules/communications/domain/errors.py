class CommunicationsError(Exception):
    """Base class for transactional communication failures."""


class DeliveryConfigurationError(CommunicationsError):
    """Raised when durable delivery policy/configuration is invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
