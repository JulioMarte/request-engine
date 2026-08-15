from collections.abc import Mapping

from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    PostgresReminderOccurrenceCommands,
)
from request_engine.modules.communications.adapters.worker.delivery_worker import (
    CommunicationDeliveryWorker,
)
from request_engine.modules.communications.adapters.worker.scheduled_worker import (
    CommunicationScheduledActionWorker,
)
from request_engine.modules.communications.contracts.delivery import CommunicationDeliveryProvider
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker


def build_scheduled_action_worker(
    session_factory: SessionFactory,
    scheduler: PostgresScheduledActionWorker,
    providers: Mapping[str, CommunicationDeliveryProvider],
) -> CommunicationScheduledActionWorker:
    """Compose the module-owned ScheduledAction processor for process entrypoints."""

    return CommunicationScheduledActionWorker(
        scheduler=scheduler,
        delivery=CommunicationDeliveryWorker(
            session_factory=session_factory,
            scheduler=scheduler,
            providers=providers,
        ),
        reminders=PostgresReminderOccurrenceCommands(session_factory),
    )
