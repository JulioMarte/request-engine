from collections.abc import Mapping

from request_engine.entrypoints.worker.provider_event_router import (
    ProviderEventHandler,
    ProviderEventKey,
)
from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    WEBHOOK_PROVIDER_KEY,
    WebhookDeliveryProvider,
)
from request_engine.modules.communications.adapters.worker.delivery_outcome_events import (
    DeliveryOutcomeEventHandler,
)
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
)
from request_engine.platform.db.session import SessionFactory

WEBHOOK_PROVIDER_CONNECTION_KEY = "primary"


def build_communication_delivery_providers(
    *,
    webhook_base_url: str | None = None,
    webhook_auth_header: tuple[str, str] | None = None,
) -> Mapping[str, CommunicationDeliveryProvider]:
    """Composition wiring for remote delivery transports; inert when unconfigured."""

    providers: dict[str, CommunicationDeliveryProvider] = {}
    if webhook_base_url:
        providers[WEBHOOK_PROVIDER_KEY] = WebhookDeliveryProvider(
            webhook_base_url,
            auth_header=webhook_auth_header,
        )
    return providers


def build_communication_provider_event_handlers(
    session_factory: SessionFactory,
) -> Mapping[ProviderEventKey, ProviderEventHandler]:
    """Composition wiring for inbound transport outcome reports.

    The connection key must match the deployment's authenticated callback
    adapter for the webhook transport; unmatched reports fail loud instead of
    being silently dropped.
    """

    return {
        (WEBHOOK_PROVIDER_KEY, WEBHOOK_PROVIDER_CONNECTION_KEY): DeliveryOutcomeEventHandler(
            session_factory,
        ),
    }
