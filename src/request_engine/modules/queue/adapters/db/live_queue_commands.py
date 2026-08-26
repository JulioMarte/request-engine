from request_engine.modules.queue.adapters.db.check_in import check_in
from request_engine.modules.queue.adapters.db.classify_expected_workload import (
    classify_expected_workload,
)
from request_engine.modules.queue.adapters.db.create_workload_classification import (
    create_workload_classification,
)
from request_engine.modules.queue.adapters.db.deactivate_workload_classification import (
    deactivate_workload_classification,
)
from request_engine.modules.queue.adapters.db.mark_no_show import mark_no_show
from request_engine.modules.queue.adapters.db.update_workload_classification import (
    update_workload_classification,
)
from request_engine.modules.queue.application.live_commands import (
    CheckInCommand,
    ClassifyExpectedWorkloadCommand,
    CreateWorkloadClassificationCommand,
    DeactivateWorkloadClassificationCommand,
    MarkNoShowCommand,
    UpdateWorkloadClassificationCommand,
)
from request_engine.modules.queue.contracts.live_queue import (
    LiveQueueEntry,
    WorkloadClassification,
)
from request_engine.platform.db.session import SessionFactory


class PostgresLiveQueueCommands:
    """Small composition adapter for F3 staff queue mutations."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def check_in(self, command: CheckInCommand) -> LiveQueueEntry:
        return await check_in(self._session_factory, command)

    async def classify_expected_workload(
        self, command: ClassifyExpectedWorkloadCommand
    ) -> LiveQueueEntry:
        return await classify_expected_workload(self._session_factory, command)

    async def mark_no_show(self, command: MarkNoShowCommand) -> LiveQueueEntry:
        return await mark_no_show(self._session_factory, command)

    async def create_workload(
        self, command: CreateWorkloadClassificationCommand
    ) -> WorkloadClassification:
        return await create_workload_classification(self._session_factory, command)

    async def update_workload(
        self, command: UpdateWorkloadClassificationCommand
    ) -> WorkloadClassification:
        return await update_workload_classification(self._session_factory, command)

    async def deactivate_workload(
        self, command: DeactivateWorkloadClassificationCommand
    ) -> WorkloadClassification:
        return await deactivate_workload_classification(self._session_factory, command)
