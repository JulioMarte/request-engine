from uuid import UUID

from request_engine.modules.queue.application.errors import QueueError


class QueueEntryNotClassifiable(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        message = f"QueueEntry {entry_id} cannot change expected workload from status {status}"
        super().__init__(message)
        self.entry_id = entry_id
        self.status = status
