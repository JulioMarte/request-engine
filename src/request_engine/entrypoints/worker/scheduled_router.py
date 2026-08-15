from collections.abc import Awaitable, Callable, Mapping

from request_engine.platform.scheduling.postgres import ScheduledActionLease
from request_engine.platform.worker.runtime import PermanentWorkError

ScheduledActionKey = tuple[str, str, int]
ScheduledActionHandler = Callable[[ScheduledActionLease], Awaitable[object]]


class ScheduledActionRouter:
    """Route a claimed ScheduledAction only to an explicitly registered handler."""

    def __init__(self, handlers: Mapping[ScheduledActionKey, ScheduledActionHandler]) -> None:
        self._handlers = dict(handlers)

    async def process(self, lease: ScheduledActionLease) -> None:
        key = (lease.owner_module, lease.action_type, lease.action_version)
        handler = self._handlers.get(key)
        if handler is None:
            raise PermanentWorkError(
                "unsupported_scheduled_action",
                f"no worker handler registered for {key!r}",
            )
        await handler(lease)
