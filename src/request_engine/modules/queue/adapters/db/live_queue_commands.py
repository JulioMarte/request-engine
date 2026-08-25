from request_engine.modules.queue.adapters.db.check_in import check_in
from request_engine.modules.queue.adapters.db.mark_no_show import mark_no_show
from request_engine.modules.queue.application.live_commands import CheckInCommand, MarkNoShowCommand
from request_engine.modules.queue.contracts.live_queue import LiveQueueEntry
from request_engine.platform.db.session import SessionFactory


class PostgresLiveQueueCommands:
    """Small composition adapter for F3 staff queue mutations."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def check_in(self, command: CheckInCommand) -> LiveQueueEntry:
        return await check_in(self._session_factory, command)

    async def mark_no_show(self, command: MarkNoShowCommand) -> LiveQueueEntry:
        return await mark_no_show(self._session_factory, command)
