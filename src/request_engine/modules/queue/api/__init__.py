from dataclasses import dataclass

from fastapi import FastAPI

from request_engine.modules.booking.contracts.slot_offer_capacity import (
    SlotOfferCapacityPort,
)
from request_engine.modules.queue.adapters.db.leave_queue_commands import (
    PostgresLeaveQueueCommands,
)
from request_engine.modules.queue.adapters.db.live_queue_commands import (
    PostgresLiveQueueCommands,
)
from request_engine.modules.queue.adapters.db.live_queue_reader import PostgresLiveQueueReader
from request_engine.modules.queue.adapters.db.service_queue_catalog_reader import (
    PostgresServiceQueueCatalogReader,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_creation_commands import (
    PostgresServiceQueueCreationCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_reader import (
    PostgresServiceQueueReader,
)
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.adapters.db.triage_commands import PostgresQueueTriageCommands
from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.adapters.db.waitlist_reader import PostgresWaitlistEntryReader
from request_engine.modules.queue.api.errors import queue_error_handler
from request_engine.modules.queue.api.intake_errors import queue_intake_stopped_handler
from request_engine.modules.queue.api.live_router import create_live_router
from request_engine.modules.queue.api.router import create_router
from request_engine.modules.queue.api.service_queue_bootstrap_router import (
    create_service_queue_bootstrap_router,
)
from request_engine.modules.queue.api.triage_router import create_triage_router
from request_engine.modules.queue.application.errors import QueueError
from request_engine.modules.queue.application.slot_offer_notifications import (
    SlotOfferNotificationPort,
)
from request_engine.modules.queue.contracts.intake import QueueIntakeStopped
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


@dataclass(frozen=True, slots=True)
class QueueSlotOfferHttpPorts:
    """Cross-module ports required to expose SlotOffer resolution over HTTP."""

    capacity: SlotOfferCapacityPort
    notification: SlotOfferNotificationPort


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    slot_offer_ports: QueueSlotOfferHttpPorts | None = None,
) -> None:
    """Connect Queue customer, waitlist and live-operation surfaces."""

    commands = PostgresServiceQueueCommands(session_factory)
    waitlist_commands = PostgresWaitlistCommands(session_factory)
    slot_offer_commands = (
        PostgresSlotOfferCommands(
            session_factory,
            capacity=slot_offer_ports.capacity,
            notification=slot_offer_ports.notification,
        )
        if slot_offer_ports is not None
        else None
    )
    app.add_exception_handler(QueueError, queue_error_handler)
    app.add_exception_handler(QueueIntakeStopped, queue_intake_stopped_handler)
    app.include_router(
        create_service_queue_bootstrap_router(
            handler=PostgresServiceQueueCreationCommands(session_factory),
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_router(
            join_executor=commands,
            call_next_executor=commands,
            leave_executor=PostgresLeaveQueueCommands(session_factory),
            reader=PostgresServiceQueueReader(session_factory),
            catalog_reader=PostgresServiceQueueCatalogReader(session_factory),
            waitlist_join_executor=waitlist_commands,
            waitlist_leave_executor=waitlist_commands,
            waitlist_reader=PostgresWaitlistEntryReader(session_factory),
            slot_offer_accept_executor=slot_offer_commands,
            slot_offer_decline_executor=slot_offer_commands,
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_live_router(
            commands=PostgresLiveQueueCommands(session_factory),
            reader=PostgresLiveQueueReader(session_factory),
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_triage_router(
            PostgresQueueTriageCommands(session_factory),
            actor_resolver,
        )
    )