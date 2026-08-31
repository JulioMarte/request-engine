"""Reference ``REQUEST_ENGINE_WORKER_FACTORY`` composition with webhook delivery.

A deployment points the worker launcher at
``request_engine.bootstrap.reference_worker_factory:create_worker``. Every
connection is explicit: webhook transport, database credentials, the worker
principal and the outbox publisher come from named environment variables or a
named publisher factory, and a missing value fails the process loudly at
startup instead of silently composing an empty provider mapping.
"""

import importlib
import os
from typing import cast
from uuid import UUID

from request_engine.bootstrap.communication_providers import (
    build_communication_delivery_providers,
)
from request_engine.bootstrap.worker import build_worker_process
from request_engine.entrypoints.worker.app import WorkerProcess
from request_engine.entrypoints.worker.outbox_runtime import OutboxPublisher
from request_engine.modules.booking.adapters.db.attendance_commands import (
    PostgresAttendanceCommands,
)
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.booking.adapters.worker.no_show import NoShowScheduledHandler
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.slot_offer_commands import (
    PostgresSlotOfferCommands,
)
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SlotOfferExpiryScheduledHandler,
)
from request_engine.platform.db.session import create_postgres_engine, create_session_factory

WEBHOOK_BASE_URL_ENV = "REQUEST_ENGINE_WEBHOOK_BASE_URL"
WEBHOOK_AUTH_HEADER_ENV = "REQUEST_ENGINE_WEBHOOK_AUTH_HEADER"
WORKER_DATABASE_URL_ENV = "REQUEST_ENGINE_WORKER_DATABASE_URL"
APP_DATABASE_URL_ENV = "REQUEST_ENGINE_APP_DATABASE_URL"
WORKER_PRINCIPAL_ID_ENV = "REQUEST_ENGINE_WORKER_PRINCIPAL_ID"
OUTBOX_PUBLISHER_FACTORY_ENV = "REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required and must not be empty")
    return value


def _webhook_auth_header() -> tuple[str, str] | None:
    raw = os.environ.get(WEBHOOK_AUTH_HEADER_ENV)
    if raw is None:
        return None
    name, separator, value = raw.partition(":")
    if not separator or not name.strip() or not value.strip():
        raise RuntimeError(f"{WEBHOOK_AUTH_HEADER_ENV} must use the form 'Header-Name: value'")
    return name.strip(), value.strip()


def _outbox_publisher() -> OutboxPublisher:
    factory_path = _required_env(OUTBOX_PUBLISHER_FACTORY_ENV)
    module_name, separator, attribute_name = factory_path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise RuntimeError(f"{OUTBOX_PUBLISHER_FACTORY_ENV} must use the form module:factory")
    factory = getattr(importlib.import_module(module_name), attribute_name, None)
    if not callable(factory):
        raise RuntimeError(f"{OUTBOX_PUBLISHER_FACTORY_ENV} {factory_path!r} is not callable")
    return cast(OutboxPublisher, factory())


def create_worker() -> WorkerProcess:
    """Assemble the production worker; misconfiguration fails before any I/O."""

    providers = build_communication_delivery_providers(
        webhook_base_url=_required_env(WEBHOOK_BASE_URL_ENV),
        webhook_auth_header=_webhook_auth_header(),
    )
    worker_sessions = create_session_factory(
        create_postgres_engine(_required_env(WORKER_DATABASE_URL_ENV))
    )
    domain_sessions = create_session_factory(
        create_postgres_engine(_required_env(APP_DATABASE_URL_ENV))
    )
    worker_principal_id = UUID(_required_env(WORKER_PRINCIPAL_ID_ENV))
    return build_worker_process(
        worker_session_factory=worker_sessions,
        domain_session_factory=domain_sessions,
        no_show_factory=lambda factory: NoShowScheduledHandler(
            PostgresAttendanceCommands(factory),
            worker_principal_id=worker_principal_id,
        ),
        slot_offer_expiry_factory=lambda factory: SlotOfferExpiryScheduledHandler(
            PostgresSlotOfferCommands(
                factory,
                capacity=CapacitySafeSlotOfferCapacity(),
                notification=PostgresSlotOfferNotificationIntent(),
            )
        ),
        communication_providers=providers,
        outbox_publisher=_outbox_publisher(),
        outbox_internal_handlers={},
        provider_event_handlers={},
    )
