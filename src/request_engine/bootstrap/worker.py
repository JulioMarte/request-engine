from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from request_engine.bootstrap.recovery_worker import build_recovery_assessment_handler
from request_engine.bootstrap.scheduled_worker import build_scheduled_action_router
from request_engine.entrypoints.worker.app import WorkerProcess
from request_engine.entrypoints.worker.outbox_runtime import (
    RESERVATION_LIFECYCLE_EVENT_TYPES,
    FencedOutboxInternalHandler,
    OutboxInternalHandler,
    OutboxPipelineProcessor,
    OutboxPublisher,
    ReservationLifecycleOutboxHandler,
)
from request_engine.entrypoints.worker.provider_event_router import (
    ProviderEventHandler,
    ProviderEventKey,
    ProviderEventRouter,
)
from request_engine.modules.booking.adapters.worker.no_show import NoShowScheduledHandler
from request_engine.modules.communications.adapters.db.reminder_occurrences import (
    PostgresReminderOccurrenceCommands,
)
from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.modules.communications.contracts.delivery import CommunicationDeliveryProvider
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SlotOfferExpiryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.events.provider_events import PostgresProviderEventWorker
from request_engine.platform.outbox.worker import PostgresOutboxWorker
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker
from request_engine.platform.worker.runtime import FencedWorkerRuntime, WorkerRuntimeConfig

NoShowHandlerFactory = Callable[[SessionFactory], NoShowScheduledHandler]
SlotOfferExpiryHandlerFactory = Callable[[SessionFactory], SlotOfferExpiryScheduledHandler]
ReservationLifecycleHandlerFactory = Callable[[SessionFactory], ReservationLifecycleOutboxHandler]


@dataclass(frozen=True, slots=True)
class WorkerProcessConfig:
    scheduled_actions: WorkerRuntimeConfig = field(default_factory=WorkerRuntimeConfig)
    outbox_messages: WorkerRuntimeConfig = field(default_factory=WorkerRuntimeConfig)
    provider_events: WorkerRuntimeConfig = field(default_factory=WorkerRuntimeConfig)


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
    reservation_lifecycle_factory: ReservationLifecycleHandlerFactory | None = None,
    config: WorkerProcessConfig | None = None,
) -> WorkerProcess:
    """Assemble production workers without crossing runtime credential boundaries."""

    if worker_session_factory is domain_session_factory:
        raise ValueError(
            "worker_session_factory and domain_session_factory must be distinct factories"
        )

    reserved = RESERVATION_LIFECYCLE_EVENT_TYPES & outbox_internal_handlers.keys()
    if reserved:
        names = ", ".join(sorted(reserved))
        raise ValueError(
            "Reservation lifecycle handlers must be assembled through "
            f"reservation_lifecycle_factory/domain_session_factory: {names}"
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
    recovery_assessment = build_recovery_assessment_handler(domain_session_factory)
    scheduled_router = build_scheduled_action_router(
        no_show=no_show,
        slot_offer_expiry=slot_offer_expiry,
        reminder_occurrences=reminder_occurrences,
        communication_delivery=communication_delivery,
        recovery_assessment=recovery_assessment,
    )

    fenced_internal_handlers: dict[str, FencedOutboxInternalHandler] = {}
    if reservation_lifecycle_factory is not None:
        lifecycle = reservation_lifecycle_factory(domain_session_factory)
        fenced_internal_handlers.update(lifecycle.handlers())

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
                fenced_internal_handlers=fenced_internal_handlers,
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
