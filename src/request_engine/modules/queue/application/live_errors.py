from uuid import UUID

from request_engine.modules.queue.application.errors import QueueError


class QueueEntryNotClassifiable(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        super().__init__(f"QueueEntry {entry_id} cannot change expected workload from status {status}")
        self.entry_id = entry_id
        self.status = status
