from uuid import UUID


class QueueError(Exception):
    """Base class for semantic service-queue errors."""


class QueueNotFound(QueueError):
    def __init__(self, queue_id: UUID) -> None:
        super().__init__(f"ServiceQueue {queue_id} was not found")
        self.queue_id = queue_id


class QueueInactive(QueueError):
    def __init__(self, queue_id: UUID) -> None:
        super().__init__(f"ServiceQueue {queue_id} is inactive")
        self.queue_id = queue_id


class AlreadyInQueue(QueueError):
    def __init__(self, queue_id: UUID, subject_party_id: UUID) -> None:
        message = f"Party {subject_party_id} already has an active entry in queue {queue_id}"
        super().__init__(message)
        self.queue_id = queue_id
        self.subject_party_id = subject_party_id


class ActiveQueueEntryNotFound(QueueError):
    def __init__(self, queue_id: UUID, subject_party_id: UUID) -> None:
        message = f"Party {subject_party_id} has no cancellable entry in queue {queue_id}"
        super().__init__(message)
        self.queue_id = queue_id
        self.subject_party_id = subject_party_id


class QueueEntryNotCancellable(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        super().__init__(f"QueueEntry {entry_id} cannot be cancelled from status {status}")
        self.entry_id = entry_id
        self.status = status
