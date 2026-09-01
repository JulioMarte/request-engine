from collections.abc import Mapping

from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    WEBHOOK_PROVIDER_KEY,
    WebhookDeliveryProvider,
)
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
)


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
