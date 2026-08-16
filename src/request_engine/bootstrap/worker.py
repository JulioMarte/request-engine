from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from request_engine.entrypoints.worker.app import WorkerProcess
from request_engine.entrypoints.worker.outbox_runtime import (
    OutboxInternalHandler,
    OutboxPipelineProcessor,
    OutboxPublisher,
)
from request_engine.entrypoints.worker.provider_event_router import (
    ProviderEventHandler,
    ProviderEventKey,
    ProviderEventRouter,
)
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
from request_engine.modules.communications.contracts.delivery import CommunicationDeliveryProvider
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SLOT_OFFER_EXPIRY_ACTION_TYPE,
    SLOT_OFFER_EXPIRY_ACTION_VERSION,
    SlotOfferExpiryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.events.provider_events import PostgresProviderEventWorker
from request_engine.platform.outbox.worker import PostgresOutboxWorker
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker
from request_engine.platform.worker.runtime import FencedWorkerRuntime, WorkerRuntimeConfig

NoShowHandlerFactory = Callable[[SessionFactory], NoShowScheduledHandler]
SlotOfferExpiryHandlerFactory = Callable[[SessionFactory], SlotOfferExpiryScheduledHandler]


@dataclass(frozen=True, slots=True)
class WorkerProcessConfig:
    scheduled_actions: WorkerRuntimeConfig = field(default_factory=WorkerRuntimeConfig)
    outbox_messages: WorkerRuntimeConfig = field(default_factory=WorkerRuntimeConfig)
    provider_events: WorkerRuntimeConfig = field(default_factory=WorkerRuntimeConfig)


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


def build_worker_process(
    *,
    worker_session_factory: SessionFactory,
    domain_session_factory: SessionFactory,
    no_show_factory: NoShowHandlerFactory,
    slot_offer_expiry_factory: SlotOfferExpiryHandlerFactory,
    communication_providers: Mapping[str, CommunicationDeliveryProvider],
    outbox_publisher: OutboxPublisher,
    outbox_internal_handlers: Mapping[str, OutboxInternalHandler],
    provider_event_handlers: Mapping[ProviderEventKey, ProviderEventHandler],
    config: WorkerProcessConfig | None = None,
) -> WorkerProcess:
    """Assemble the production worker without crossing runtime credential boundaries."""

    if worker_session_factory is domain_session_factory:
        raise ValueError(
            "worker_session_factory and domain_session_factory must be distinct factories"
        )

    runtime_config = config or WorkerProcessConfig()

    scheduled_store = PostgresScheduledActionWorker(worker_session_factory)
    outbox_store = PostgresOutboxWorker(worker_session_factory)
    provider_event_store = PostgresProviderEventWorker(worker_session_factory)

    no_show = no_show_factory(domain_session_factory)
    slot_offer_expiry = slot_offer_expiry_factory(domain_session_factory)
    reminder_occurrences = PostgresReminderOccurrenceCommands(domain_session_factory)
    communication_delivery = CommunicationDeliveryScheduledHandler(
        domain_session_factory,
        scheduled_store,
        communication_providers,
    )
    scheduled_router = build_scheduled_action_router(
        no_show=no_show,
        slot_offer_expiry=slot_offer_expiry,
        reminder_occurrences=reminder_occurrences,
        communication_delivery=communication_delivery,
    )

    return WorkerProcess(
        scheduled_actions=FencedWorkerRuntime(
            scheduled_store,
            scheduled_router,
            config=runtime_config.scheduled_actions,
        ),
        outbox_messages=FencedWorkerRuntime(
            outbox_store,
            OutboxPipelineProcessor(
                publisher=outbox_publisher,
                internal_handlers=outbox_internal_handlers,
            ),
            config=runtime_config.outbox_messages,
        ),
        provider_events=FencedWorkerRuntime(
            provider_event_store,
            ProviderEventRouter(provider_event_handlers),
            rejecter=provider_event_store.reject,
            config=runtime_config.provider_events,
        ),
    )
