class CommunicationsError(Exception):
    """Base class for transactional communication failures."""


class DeliveryConfigurationError(CommunicationsError):
    """Raised when durable delivery policy/configuration is invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ChannelPurposeDisabled(CommunicationsError):
    """The organization intentionally disabled this communication purpose.

    New durable intents for the purpose are rejected; tasks already in flight
    keep their own frozen channel-policy snapshot and are not touched.
    """

    def __init__(self, purpose: str) -> None:
        super().__init__(f"communication purpose {purpose} is disabled for this organization")
        self.purpose = purpose


class RecipientChannelUnavailable(DeliveryConfigurationError):
    """The task's resolved channel has no usable contact point.

    Distinguishes per-channel ``recipient_unreachable`` (docs/v3/36 section 4)
    from other delivery configuration defects: only this subclass walks the
    escalation ladder; the rest keep the durable
    ``delivery_configuration_invalid`` poison semantics.
    """
