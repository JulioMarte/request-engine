from uuid import UUID

from request_engine.modules.queue.application.commands.expire_slot_offer import (
    ExpireSlotOfferCommand,
    ExpireSlotOfferExecutor,
    expire_slot_offer,
)
from request_engine.modules.queue.contracts.waitlist import SlotOfferResolution
from request_engine.platform.scheduling.postgres import ScheduledActionLease

SLOT_OFFER_EXPIRY_ACTION_TYPE = "waitlist.expire_slot_offer"
SLOT_OFFER_EXPIRY_ACTION_VERSION = 1


class SlotOfferExpiryScheduledHandler:
    """Translate a fenced ScheduledAction lease into the semantic expiry command."""

    def __init__(self, executor: ExpireSlotOfferExecutor) -> None:
        self._executor = executor

    async def handle(self, lease: ScheduledActionLease) -> SlotOfferResolution:
        if lease.owner_module != "queue":
            raise ValueError("ScheduledAction is not owned by queue")
        if (
            lease.action_type != SLOT_OFFER_EXPIRY_ACTION_TYPE
            or lease.action_version != SLOT_OFFER_EXPIRY_ACTION_VERSION
        ):
            raise ValueError("unsupported queue ScheduledAction")
        raw_offer_id = lease.payload.get("slot_offer_id")
        raw_revision = lease.payload.get("expected_revision")
        raw_principal_id = lease.payload.get("principal_id")
        if not isinstance(raw_offer_id, str) or not isinstance(raw_principal_id, str):
            raise ValueError("SlotOffer expiry payload is missing identifiers")
        if not isinstance(raw_revision, int) or raw_revision <= 0:
            raise ValueError("SlotOffer expiry payload has invalid expected_revision")

        return await expire_slot_offer(
            self._executor,
            ExpireSlotOfferCommand(
                organization_id=lease.organization_id,
                principal_id=UUID(raw_principal_id),
                slot_offer_id=UUID(raw_offer_id),
                expected_revision=raw_revision,
                idempotency_key=f"scheduled-action:{lease.id}",
            ),
        )
