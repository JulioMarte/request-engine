from datetime import UTC, datetime, timedelta
from uuid import UUID

from request_engine.modules.booking.contracts.lifecycle import ReleasedReservationSlot
from request_engine.modules.booking.contracts.slot_offer_capacity import SlotOfferCapacityPort
from request_engine.modules.booking.domain.lifecycle_policy import reservation_lifecycle_policy
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.application.commands.create_slot_opportunity import (
    CreateSlotOpportunityCommand,
    create_slot_opportunity,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
    offer_next_waitlist_candidate,
)
from request_engine.modules.queue.application.slot_offer_notifications import SlotOfferNotificationPort
from request_engine.modules.queue.contracts.waitlist import SlotOffer, SlotOpportunity
from request_engine.platform.db.session import SessionFactory


class PostgresReleasedSlotRecovery:
    """Turn a committed Reservation release into the existing Phase 2B chain."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        capacity: SlotOfferCapacityPort,
        notification: SlotOfferNotificationPort,
        offer_ttl_seconds: int = 300,
    ) -> None:
        self._opportunities = PostgresWaitlistCommands(session_factory)
        self._offers = PostgresSlotOfferCommands(
            session_factory,
            capacity=capacity,
            notification=notification,
        )
        self._offer_ttl_seconds = offer_ttl_seconds

    async def recover_released_slot(
        self,
        slot: ReleasedReservationSlot,
        *,
        source_event_id: UUID,
        principal_id: UUID,
    ) -> tuple[SlotOpportunity, SlotOffer | None] | None:
        policy = reservation_lifecycle_policy(slot.booking_policy_snapshot)
        if not policy.slot_recovery.enabled:
            return None
        now = datetime.now(UTC)
        if slot.start_at <= now + timedelta(minutes=policy.slot_recovery.minimum_lead_minutes):
            return None
        opportunity = await create_slot_opportunity(
            self._opportunities,
            CreateSlotOpportunityCommand(
                organization_id=slot.organization_id,
                principal_id=principal_id,
                offering_version_id=slot.offering_version_id,
                source_event_id=source_event_id,
                start_at=slot.start_at,
                end_at=slot.end_at,
                idempotency_key=f"reservation-release:{source_event_id}",
                location_id=slot.location_id,
                source_reservation_id=slot.reservation_id,
            ),
        )
        expires_at = min(
            now + timedelta(seconds=self._offer_ttl_seconds),
            slot.start_at - timedelta(seconds=1),
        )
        if expires_at <= now:
            return (opportunity, None)
        offer = await offer_next_waitlist_candidate(
            self._offers,
            OfferNextWaitlistCandidateCommand(
                organization_id=slot.organization_id,
                principal_id=principal_id,
                slot_opportunity_id=opportunity.id,
                offer_expires_at=expires_at,
                idempotency_key=f"reservation-release-offer:{source_event_id}",
            ),
        )
        return opportunity, offer
