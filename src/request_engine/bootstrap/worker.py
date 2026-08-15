from request_engine.entrypoints.worker.scheduled_router import ScheduledActionRouter
from request_engine.modules.booking.adapters.db.lifecycle_scheduling import (
    NO_SHOW_ACTION_TYPE,
    NO_SHOW_ACTION_VERSION,
)
from request_engine.modules.booking.adapters.worker.no_show import NoShowScheduledHandler
from request_engine.modules.communications.adapters.db.delivery_store import (
    DISPATCH_ACTION_TYPE,
    DISPATCH_ACTION_VERSION,
    RECONCILE_ACTION_TYPE,
    RECONCILE_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.reminder_commands import (
    REMINDER_ACTION_TYPE,
    REMINDER_ACTION_VERSION,
)
from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    PostgresReminderOccurrenceCommands,
)
from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SLOT_OFFER_EXPIRY_ACTION_TYPE,
    SLOT_OFFER_EXPIRY_ACTION_VERSION,
    SlotOfferExpiryScheduledHandler,
)


def build_scheduled_action_router(
    *,
    no_show: NoShowScheduledHandler,
    slot_offer_expiry: SlotOfferExpiryScheduledHandler,
    reminder_occurrences: PostgresReminderOccurrenceCommands,
    communication_delivery: CommunicationDeliveryScheduledHandler,
) -> ScheduledActionRouter:
    """Compose concrete module worker adapters at the application boundary."""

    return ScheduledActionRouter(
        {
            ("booking", NO_SHOW_ACTION_TYPE, NO_SHOW_ACTION_VERSION): no_show.handle,
            (
                "queue",
                SLOT_OFFER_EXPIRY_ACTION_TYPE,
                SLOT_OFFER_EXPIRY_ACTION_VERSION,
            ): slot_offer_expiry.handle,
            (
                "communications",
                REMINDER_ACTION_TYPE,
                REMINDER_ACTION_VERSION,
            ): reminder_occurrences.materialize,
            (
                "communications",
                DISPATCH_ACTION_TYPE,
                DISPATCH_ACTION_VERSION,
            ): communication_delivery.handle,
            (
                "communications",
                RECONCILE_ACTION_TYPE,
                RECONCILE_ACTION_VERSION,
            ): communication_delivery.handle,
        }
    )
