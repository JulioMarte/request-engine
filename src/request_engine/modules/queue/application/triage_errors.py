from uuid import UUID

from request_engine.modules.queue.application.errors import QueueError


class TriageQueueEntryNotFound(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} was not found")
        self.entry_id = entry_id


class QueueEntryNotWaiting(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        super().__init__(f"QueueEntry {entry_id} is not waiting: {status}")
        self.entry_id = entry_id
        self.status = status


class QueueEntryNotCurrentHead(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} is not the current eligible FIFO head")
        self.entry_id = entry_id


class QueueEntryAlreadyHeld(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} already has an active recall hold")
        self.entry_id = entry_id


class QueueEntryAlreadySkipped(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} already has an active skip")
        self.entry_id = entry_id


class InvalidRecallHold(QueueError):
    pass


class QueueHoldNotActive(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} has no active recall hold to release")
        self.entry_id = entry_id


class RecallHoldConflict(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} active hold does not match the requested hold")
        self.entry_id = entry_id
