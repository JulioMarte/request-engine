from collections.abc import Mapping

from request_engine.entrypoints.worker.provider_event_router import (
    ProviderEventHandler,
    ProviderEventKey,
)
from request_engine.modules.communications.adapters.transport.managed_webhook_delivery_provider import (
    ManagedWebhookDeliveryProvider,
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
from request_engine.modules.platform_configuration.contracts.runtime import (
    ActiveWebhookConfigurationResolver,
)
from request_engine.platform.db.session import SessionFactory

WEBHOOK_PROVIDER_CONNECTION_KEY = "primary"


def build_communication_delivery_providers(
    *,
    webhook_base_url: str | None = None,
    webhook_auth_header: tuple[str, str] | None = None,
    managed_webhook_resolver: ActiveWebhookConfigurationResolver | None = None,
) -> Mapping[str, CommunicationDeliveryProvider]:
    """Compose Communications transports with managed-over-bootstrap precedence."""

    if webhook_auth_header is not None and not webhook_base_url:
        raise ValueError("webhook auth header requires a bootstrap webhook URL")

    bootstrap = (
        WebhookDeliveryProvider(
            webhook_base_url,
            auth_header=webhook_auth_header,
        )
        if webhook_base_url
        else None
    )
    if managed_webhook_resolver is not None:
        return {
            WEBHOOK_PROVIDER_KEY: ManagedWebhookDeliveryProvider(
                resolver=managed_webhook_resolver,
                fallback=bootstrap,
            )
        }
    if bootstrap is None:
        return {}
    return {WEBHOOK_PROVIDER_KEY: bootstrap}


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
