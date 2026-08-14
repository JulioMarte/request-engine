from uuid import UUID


class QueueError(Exception):
    """Base class for semantic service-queue and waitlist errors."""


class SubjectAuthorityRequired(QueueError):
    def __init__(self, subject_party_id: UUID, scope_key: str) -> None:
        super().__init__(
            f"Principal is not authorized to act for Party {subject_party_id} in scope {scope_key}"
        )
        self.subject_party_id = subject_party_id
        self.scope_key = scope_key


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


class QueueEntryNotFound(QueueError):
    def __init__(self, queue_id: UUID, entry_id: UUID) -> None:
        super().__init__(f"QueueEntry {entry_id} was not found in ServiceQueue {queue_id}")
        self.queue_id = queue_id
        self.entry_id = entry_id


class QueueEntryRevisionConflict(QueueError):
    def __init__(self, entry_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"QueueEntry {entry_id} revision conflict: expected {expected}, current {actual}"
        )
        self.entry_id = entry_id
        self.expected = expected
        self.actual = actual


class QueueEntryNotCancellable(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        super().__init__(f"QueueEntry {entry_id} cannot be cancelled from status {status}")
        self.entry_id = entry_id
        self.status = status


class OfferingNotAvailableForWaitlist(QueueError):
    def __init__(self, offering_id: UUID) -> None:
        super().__init__(f"Offering {offering_id} is not available for waitlist")
        self.offering_id = offering_id


class AlreadyOnWaitlist(QueueError):
    def __init__(self, offering_id: UUID, subject_party_id: UUID) -> None:
        super().__init__(
            f"Party {subject_party_id} already has an active waitlist entry "
            f"for Offering {offering_id}"
        )
        self.offering_id = offering_id
        self.subject_party_id = subject_party_id


class WaitlistEntryNotFound(QueueError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"WaitlistEntry {entry_id} was not found")
        self.entry_id = entry_id


class WaitlistEntryRevisionConflict(QueueError):
    def __init__(self, entry_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"WaitlistEntry {entry_id} revision conflict: expected {expected}, current {actual}"
        )
        self.entry_id = entry_id
        self.expected = expected
        self.actual = actual


class WaitlistEntryNotCancellable(QueueError):
    def __init__(self, entry_id: UUID, status: str) -> None:
        super().__init__(f"WaitlistEntry {entry_id} cannot be cancelled from status {status}")
        self.entry_id = entry_id
        self.status = status


class SlotOpportunitySourceConflict(QueueError):
    def __init__(self, source_event_id: UUID) -> None:
        super().__init__(
            f"source event {source_event_id} is already bound to a different SlotOpportunity"
        )
        self.source_event_id = source_event_id


class SlotOpportunityNotFound(QueueError):
    def __init__(self, opportunity_id: UUID) -> None:
        super().__init__(f"SlotOpportunity {opportunity_id} was not found")
        self.opportunity_id = opportunity_id


class SlotOpportunityNotOpen(QueueError):
    def __init__(self, opportunity_id: UUID, status: str) -> None:
        super().__init__(f"SlotOpportunity {opportunity_id} is not open: {status}")
        self.opportunity_id = opportunity_id
        self.status = status


class SlotOfferNotFound(QueueError):
    def __init__(self, slot_offer_id: UUID) -> None:
        super().__init__(f"SlotOffer {slot_offer_id} was not found")
        self.slot_offer_id = slot_offer_id


class SlotOfferRevisionConflict(QueueError):
    def __init__(self, slot_offer_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"SlotOffer {slot_offer_id} revision conflict: expected {expected}, current {actual}"
        )
        self.slot_offer_id = slot_offer_id
        self.expected = expected
        self.actual = actual


class SlotOfferNotActionable(QueueError):
    def __init__(self, slot_offer_id: UUID, status: str) -> None:
        super().__init__(f"SlotOffer {slot_offer_id} is not actionable from status {status}")
        self.slot_offer_id = slot_offer_id
        self.status = status


class SlotOfferExpired(QueueError):
    def __init__(self, slot_offer_id: UUID) -> None:
        super().__init__(f"SlotOffer {slot_offer_id} has expired")
        self.slot_offer_id = slot_offer_id
