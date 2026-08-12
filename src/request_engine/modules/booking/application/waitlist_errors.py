from uuid import UUID


class WaitlistError(Exception):
    """Base class for stable waitlist/released-capacity semantic failures."""


class WaitlistEntryNotFound(WaitlistError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"WaitlistEntry {entry_id} was not found")
        self.entry_id = entry_id


class WaitlistEntryNotActive(WaitlistError):
    def __init__(self, entry_id: UUID) -> None:
        super().__init__(f"WaitlistEntry {entry_id} is not active")
        self.entry_id = entry_id


class SlotOpportunityNotFound(WaitlistError):
    def __init__(self, opportunity_id: UUID) -> None:
        super().__init__(f"SlotOpportunity {opportunity_id} was not found")
        self.opportunity_id = opportunity_id


class SlotOpportunityNotOpen(WaitlistError):
    def __init__(self, opportunity_id: UUID) -> None:
        super().__init__(f"SlotOpportunity {opportunity_id} is not open")
        self.opportunity_id = opportunity_id


class SlotOpportunitySourceInvalid(WaitlistError):
    def __init__(self, reservation_id: UUID) -> None:
        super().__init__(
            f"Reservation {reservation_id} cannot seed a released-slot opportunity"
        )
        self.reservation_id = reservation_id


class SlotOfferNotFound(WaitlistError):
    def __init__(self, offer_id: UUID) -> None:
        super().__init__(f"SlotOffer {offer_id} was not found")
        self.offer_id = offer_id


class SlotOfferNotActive(WaitlistError):
    def __init__(self, offer_id: UUID) -> None:
        super().__init__(f"SlotOffer {offer_id} is not active")
        self.offer_id = offer_id


class SlotOfferExpired(WaitlistError):
    def __init__(self, offer_id: UUID) -> None:
        super().__init__(f"SlotOffer {offer_id} has expired")
        self.offer_id = offer_id


class NoEligibleWaitlistCandidate(WaitlistError):
    def __init__(self, opportunity_id: UUID) -> None:
        super().__init__(f"SlotOpportunity {opportunity_id} has no eligible waitlist candidate")
        self.opportunity_id = opportunity_id


class ActiveSlotOfferExists(WaitlistError):
    def __init__(self, opportunity_id: UUID) -> None:
        super().__init__(f"SlotOpportunity {opportunity_id} already has an active offer")
        self.opportunity_id = opportunity_id
