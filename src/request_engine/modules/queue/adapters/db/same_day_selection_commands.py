from request_engine.modules.queue.adapters.db.operator_select import operator_select
from request_engine.modules.queue.adapters.db.recall_hold import recall_hold
from request_engine.modules.queue.adapters.db.release_recall_hold import release_recall_hold
from request_engine.modules.queue.adapters.db.skip_queue_head import skip_queue_head
from request_engine.modules.queue.application.commands.operator_select import OperatorSelectCommand
from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.commands.release_recall_hold import (
    ReleaseRecallHoldCommand,
)
from request_engine.modules.queue.application.commands.skip_queue_head import SkipQueueHeadCommand
from request_engine.modules.queue.contracts.same_day_selection import RecallHold, SkipResult
from request_engine.modules.queue.contracts.service_queue import QueueEntry
from request_engine.platform.db.session import SessionFactory


class PostgresSameDaySelectionCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def operator_select(self, command: OperatorSelectCommand) -> QueueEntry:
        return await operator_select(self._session_factory, command)

    async def recall_hold(self, command: RecallHoldCommand) -> RecallHold:
        return await recall_hold(self._session_factory, command)

    async def release_recall_hold(
        self,
        command: ReleaseRecallHoldCommand,
    ) -> RecallHold | None:
        return await release_recall_hold(self._session_factory, command)

    async def skip_queue_head(self, command: SkipQueueHeadCommand) -> SkipResult | None:
        return await skip_queue_head(self._session_factory, command)
