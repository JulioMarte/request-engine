from fastapi import FastAPI

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.operator_resolution import OperatorCapabilitySource
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.api import QueueSlotOfferHttpPorts
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.discovery import TenantCapabilityPolicy
from request_engine.platform.security.http import ActorResolver


def build_http_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    appointment_option_signing_key: bytes | None = None,
    tenant_capability_policy: TenantCapabilityPolicy | None = None,
    operator_capability_source: OperatorCapabilitySource | None = None,
) -> FastAPI:
    """Compose the full V3 HTTP product without cross-module adapter imports in modules."""

    return create_app(
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        appointment_option_signing_key=appointment_option_signing_key,
        tenant_capability_policy=tenant_capability_policy,
        operator_capability_source=operator_capability_source,
        slot_offer_ports=QueueSlotOfferHttpPorts(
            capacity=CapacitySafeSlotOfferCapacity(),
            notification=PostgresSlotOfferNotificationIntent(),
        ),
    )
