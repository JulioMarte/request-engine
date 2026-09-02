from request_engine.modules.queue.adapters.db.triage_operator_select import operator_select
from request_engine.modules.queue.adapters.db.triage_recall_hold import recall_hold
from request_engine.modules.queue.adapters.db.triage_skip import skip
from request_engine.modules.queue.application.commands.triage import (
    OperatorSelectCommand,
    RecallHoldCommand,
    SkipCommand,
)
from request_engine.modules.queue.contracts.triage import QueueTriageResult
from request_engine.platform.db.session import SessionFactory


class PostgresQueueTriageCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def operator_select(
        self,
        command: OperatorSelectCommand,
    ) -> QueueTriageResult:
        return await operator_select(self._session_factory, command)

    async def recall_hold(
        self,
        command: RecallHoldCommand,
    ) -> QueueTriageResult:
        return await recall_hold(self._session_factory, command)

    async def skip(self, command: SkipCommand) -> QueueTriageResult:
        return await skip(self._session_factory, command)
