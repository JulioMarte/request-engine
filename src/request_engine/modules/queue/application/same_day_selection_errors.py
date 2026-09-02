from uuid import UUID

from request_engine.modules.queue.application.errors import QueueError


class QueueEntryNotSelectable(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        super().__init__(f"QueueEntry {entry_id} is not selectable from status {status}")
        self.entry_id = entry_id
        self.status = status


class QueueEntryRecallHeld(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} has an active recall hold")
        self.entry_id = entry_id


class RecallHoldInvalid(QueueError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail
