from __future__ import annotations

import pytest

from request_engine.bootstrap.communication_providers import (
    build_communication_delivery_providers,
)
from request_engine.modules.communications.adapters.transport import (
    managed_webhook_delivery_provider as managed_webhook,
)
from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    WEBHOOK_PROVIDER_KEY,
    WebhookDeliveryProvider,
)

pytestmark = [pytest.mark.unit]


def test_provider_wiring_registers_webhook_only_when_configured() -> None:
    assert build_communication_delivery_providers() == {}

    configured = build_communication_delivery_providers(
        webhook_base_url="https://transport.example.test/webhook",
        webhook_auth_header=("Authorization", "Bearer token-1"),
    )
    assert set(configured) == {WEBHOOK_PROVIDER_KEY}
    assert isinstance(configured[WEBHOOK_PROVIDER_KEY], WebhookDeliveryProvider)

class _ManagedResolver:
    async def resolve_webhook(
        self,
        *,
        revision: int | None = None,
        force_refresh: bool = False,
    ) -> None:
        del revision, force_refresh
        return None


def test_provider_wiring_registers_managed_webhook_without_bootstrap_url() -> None:
    configured = build_communication_delivery_providers(
        managed_webhook_resolver=_ManagedResolver(),
    )

    assert set(configured) == {WEBHOOK_PROVIDER_KEY}
    assert isinstance(configured[WEBHOOK_PROVIDER_KEY], managed_webhook.ManagedWebhookDeliveryProvider)

