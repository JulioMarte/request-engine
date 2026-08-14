from collections.abc import Awaitable, Callable, Mapping

from request_engine.platform.events.provider_events import ProviderEventLease
from request_engine.platform.worker.runtime import PermanentWorkError

ProviderEventKey = tuple[str, str]
ProviderEventHandler = Callable[[ProviderEventLease], Awaitable[object]]


class ProviderEventRouter:
    """Route inbound provider work only to an explicitly configured connection."""

    def __init__(self, handlers: Mapping[ProviderEventKey, ProviderEventHandler]) -> None:
        self._handlers = dict(handlers)

    async def process(self, lease: ProviderEventLease) -> None:
        key = (lease.provider_key, lease.connection_key)
        handler = self._handlers.get(key)
        if handler is None:
            raise PermanentWorkError(
                "provider_event_handler_not_configured",
                f"no ProviderEvent handler registered for {key!r}",
            )
        await handler(lease)
