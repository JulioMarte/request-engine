from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from request_engine.modules.communications.adapters.transport.managed_webhook_delivery_provider import (
    ManagedWebhookDeliveryProvider,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)
from request_engine.modules.platform_configuration.contracts.runtime import (
    PlatformRuntimeConfigurationError,
    ResolvedWebhookConfiguration,
)


def _resolved(revision: int = 3) -> ResolvedWebhookConfiguration:
    return ResolvedWebhookConfiguration(
        base_url="https://transport.example.test/handoff",
        auth_header_name="Authorization",
        auth_header_value="Bearer governed",
        timeout_seconds=7.0,
        configuration_revision=revision,
        secret_binding_revision=2,
        secret_backend_version=4,
    )


def _send_request() -> ProviderSendRequest:
    return ProviderSendRequest(
        delivery_id=uuid4(),
        communication_task_id=uuid4(),
        provider_key="webhook",
        provider_idempotency_key="communication:test:attempt:1",
        channel="email",
        destination="subject@example.test",
        contact_point_id=uuid4(),
        template_key="appointment_confirmation",
        template_version=1,
        render_context={"reservation_id": str(uuid4())},
        attempt_no=1,
    )


class _Resolver:
    def __init__(self, active: ResolvedWebhookConfiguration | None) -> None:
        self.active = active
        self.exact: dict[int, ResolvedWebhookConfiguration] = {}
        self.requests: list[int | None] = []
        self.fail = False

    async def resolve_webhook(
        self,
        *,
        revision: int | None = None,
        force_refresh: bool = False,
    ) -> ResolvedWebhookConfiguration | None:
        del force_refresh
        self.requests.append(revision)
        if self.fail:
            raise PlatformRuntimeConfigurationError("unavailable")
        if revision is None:
            return self.active
        return self.exact.get(revision)


class _Provider:
    def __init__(self) -> None:
        self.sent = 0
        self.lookups = 0

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        del request
        self.sent += 1
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.ACCEPTED,
            provider_message_id="message-1",
            result_data={"transport": "fake"},
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        del request
        self.lookups += 1
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id="message-1",
        )


@pytest.mark.asyncio
async def test_managed_webhook_send_records_configuration_pin() -> None:
    resolver = _Resolver(_resolved(7))
    child = _Provider()
    provider = ManagedWebhookDeliveryProvider(
        resolver=resolver,
        provider_factory=lambda _configuration: child,
    )

    result = await provider.send(_send_request())

    assert result.status is ProviderDeliveryStatus.ACCEPTED
    assert result.result_data["provider_configuration_source"] == "managed"
    assert result.result_data["provider_configuration_revision"] == 7
    assert child.sent == 1
    assert resolver.requests == [None]


@pytest.mark.asyncio
async def test_bootstrap_send_is_pinned_and_lookup_never_jumps_to_managed() -> None:
    resolver = _Resolver(None)
    bootstrap = _Provider()
    provider = ManagedWebhookDeliveryProvider(
        resolver=resolver,
        fallback=bootstrap,
        provider_factory=lambda _configuration: pytest.fail("managed provider not expected"),
    )

    sent = await provider.send(_send_request())
    assert sent.result_data["provider_configuration_source"] == "bootstrap"

    resolver.active = _resolved(8)
    lookup = await provider.lookup(
        ProviderLookupRequest(
            delivery_id=uuid4(),
            communication_task_id=uuid4(),
            provider_key="webhook",
            provider_idempotency_key="communication:test:attempt:1",
            provider_message_id="message-1",
            provider_configuration_source="bootstrap",
        )
    )

    assert lookup.status is ProviderDeliveryStatus.DELIVERED
    assert bootstrap.lookups == 1
    assert resolver.requests == [None]


@pytest.mark.asyncio
async def test_managed_lookup_resolves_exact_superseded_revision() -> None:
    resolver = _Resolver(_resolved(9))
    resolver.exact[4] = _resolved(4)
    children: dict[int, _Provider] = {}

    def build(configuration: ResolvedWebhookConfiguration) -> _Provider:
        return children.setdefault(configuration.configuration_revision, _Provider())

    provider = ManagedWebhookDeliveryProvider(
        resolver=resolver,
        provider_factory=build,
    )
    result = await provider.lookup(
        ProviderLookupRequest(
            delivery_id=uuid4(),
            communication_task_id=uuid4(),
            provider_key="webhook",
            provider_idempotency_key="communication:test:attempt:1",
            provider_message_id="message-4",
            provider_configuration_source="managed",
            provider_configuration_revision=4,
        )
    )

    assert result.status is ProviderDeliveryStatus.DELIVERED
    assert children[4].lookups == 1
    assert 9 not in children
    assert resolver.requests == [4]


@pytest.mark.asyncio
async def test_missing_exact_managed_revision_is_ambiguous_not_retargeted() -> None:
    resolver = _Resolver(_resolved(10))
    provider = ManagedWebhookDeliveryProvider(
        resolver=resolver,
        provider_factory=lambda _configuration: pytest.fail("provider must not be contacted"),
    )

    result = await provider.lookup(
        ProviderLookupRequest(
            delivery_id=uuid4(),
            communication_task_id=uuid4(),
            provider_key="webhook",
            provider_idempotency_key="communication:test:attempt:1",
            provider_message_id="message-old",
            provider_configuration_source="managed",
            provider_configuration_revision=3,
        )
    )

    assert result.status is ProviderDeliveryStatus.AMBIGUOUS
    assert result.result_data["provider_configuration_revision"] == 3
    assert resolver.requests == [3]


@pytest.mark.asyncio
async def test_pre_send_configuration_outage_is_retryable_not_ambiguous() -> None:
    resolver = _Resolver(None)
    resolver.fail = True
    provider = ManagedWebhookDeliveryProvider(resolver=resolver)

    result = await provider.send(_send_request())

    assert result.status is ProviderDeliveryStatus.FAILED
    assert result.retryable is True
    assert result.result_data["error_phase"] == "provider_resolution"
