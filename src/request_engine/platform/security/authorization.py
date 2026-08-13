from request_engine.platform.security.context import ActorContext


class CapabilityRequired(Exception):
    """Raised when an authenticated actor lacks a required technical capability."""

    def __init__(self, capability: str) -> None:
        super().__init__(f"capability {capability!r} is required")
        self.capability = capability


def require_capability(actor: ActorContext, capability: str) -> None:
    """Enforce one canonical capability at a transport-neutral operation boundary."""

    if not actor.allows(capability):
        raise CapabilityRequired(capability)
