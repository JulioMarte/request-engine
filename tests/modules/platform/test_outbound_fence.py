from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest

from request_engine.bootstrap.outbound_fence import (
    OutboundFenceSettings,
    OutboundSideEffectFence,
    RecoveryOutboundChannel,
)
from request_engine.entrypoints.worker.outbox_runtime import OutboxEvent
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)
from request_engine.modules.platform_configuration.application.smtp import (
    ProviderTestOutcome,
    ProviderTestResult,
    ProviderValidationResult,
    ProviderValidationStatus,
    SmtpConfiguration,
    SmtpSecurityMode,
)
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryRetryable,
)


class _Outbox:
    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, event: OutboxEvent) -> None:
        del event
        self.calls += 1


class _Provider:
    def __init__(self) -> None:
        self.sends = 0
        self.lookups = 0

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        del request
        self.sends += 1
        return ProviderDeliveryResult(ProviderDeliveryStatus.ACCEPTED)

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        del request
        self.lookups += 1
        return ProviderDeliveryResult(ProviderDeliveryStatus.DELIVERED)


class _Recovery:
    def __init__(self) -> None:
        self.calls = 0

    async def send(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        return await self.send_recovery(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def send_recovery(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        del secret, destination_reference, idempotency_key
        self.calls += 1
        return DeliveryOutcome.DELIVERED

    async def send_verification(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        return await self.send_recovery(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def reconcile(self, *, idempotency_key: str) -> DeliveryOutcome | None:
        del idempotency_key
        self.calls += 1
        return DeliveryOutcome.DELIVERED


class _Validator:
    def __init__(self) -> None:
        self.calls = 0

    async def validate(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
    ) -> ProviderValidationResult:
        del configuration, password
        self.calls += 1
        return ProviderValidationResult(ProviderValidationStatus.VALID, "ok")


class _Tester:
    def __init__(self) -> None:
        self.calls = 0

    async def test(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
        destination: str,
        idempotency_key: str,
    ) -> ProviderTestResult:
        del configuration, password, destination, idempotency_key
        self.calls += 1
        return ProviderTestResult(ProviderTestOutcome.DELIVERED, "ok")


def _event() -> OutboxEvent:
    return OutboxEvent(
        id=uuid4(),
        organization_id=uuid4(),
        event_type="test.v1",
        schema_version=1,
        aggregate_kind=None,
        aggregate_id=None,
        payload={},
    )


def _send_request() -> ProviderSendRequest:
    return ProviderSendRequest(
        delivery_id=uuid4(),
        communication_task_id=uuid4(),
        provider_key="webhook",
        provider_idempotency_key="fence:test",
        channel="email",
        destination="subject@example.test",
        contact_point_id=uuid4(),
        template_key="test",
        template_version=1,
        render_context={},
        attempt_no=1,
    )


def _lookup_request() -> ProviderLookupRequest:
    return ProviderLookupRequest(
        delivery_id=uuid4(),
        communication_task_id=uuid4(),
        provider_key="webhook",
        provider_idempotency_key="fence:test",
        provider_message_id="message",
    )


def _smtp() -> SmtpConfiguration:
    return SmtpConfiguration(
        host="smtp.example.test",
        port=587,
        sender="noreply@example.test",
        security=SmtpSecurityMode.STARTTLS,
    )


def test_outbound_fence_defaults_closed_and_requires_explicit_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REQUEST_ENGINE_OUTBOUND_FENCED", raising=False)
    assert OutboundFenceSettings().outbound_fenced is True
    monkeypatch.setenv("REQUEST_ENGINE_OUTBOUND_FENCED", "false")
    assert OutboundFenceSettings().outbound_fenced is False


@pytest.mark.asyncio
async def test_fenced_outbox_and_communications_never_reach_transport() -> None:
    fence = OutboundSideEffectFence(fenced=True)
    outbox = _Outbox()
    provider = _Provider()

    with pytest.raises(RuntimeError, match="fenced"):
        await fence.outbox(outbox).publish(_event())

    wrapped = fence.communications({"webhook": provider})["webhook"]
    sent = await wrapped.send(_send_request())
    looked_up = await wrapped.lookup(_lookup_request())

    assert sent.status is ProviderDeliveryStatus.FAILED and sent.retryable is True
    assert looked_up.status is ProviderDeliveryStatus.AMBIGUOUS
    assert sent.result_data["error_class"] == "outbound_fenced"
    assert provider.sends == provider.lookups == 0
    assert outbox.calls == 0


@pytest.mark.asyncio
async def test_fenced_recovery_validation_and_provider_test_never_delegate() -> None:
    fence = OutboundSideEffectFence(fenced=True)
    recovery = _Recovery()
    validator = _Validator()
    tester = _Tester()
    channel = fence.recovery(cast(RecoveryOutboundChannel, recovery))
    assert channel is not None

    with pytest.raises(RecoveryDeliveryRetryable, match="fenced"):
        await channel.send_recovery(
            secret="secret",
            destination_reference="subject@example.test",
            idempotency_key="fence:test",
        )

    validation = await fence.smtp_validator(validator).validate(_smtp(), password=None)
    provider_test = await fence.smtp_tester(tester).test(
        _smtp(),
        password=None,
        destination="subject@example.test",
        idempotency_key="fence:test",
    )

    assert validation == ProviderValidationResult(
        ProviderValidationStatus.UNAVAILABLE,
        "outbound_fenced",
    )
    assert provider_test == ProviderTestResult(ProviderTestOutcome.FAILED, "outbound_fenced")
    assert recovery.calls == validator.calls == tester.calls == 0


@pytest.mark.asyncio
async def test_open_fence_delegates_normally() -> None:
    fence = OutboundSideEffectFence(fenced=False)
    outbox = _Outbox()
    provider = _Provider()
    recovery = _Recovery()

    await fence.outbox(outbox).publish(_event())
    sent = await fence.communications({"webhook": cast(CommunicationDeliveryProvider, provider)})[
        "webhook"
    ].send(_send_request())
    channel = fence.recovery(cast(RecoveryOutboundChannel, recovery))
    assert channel is not None
    delivered = await channel.send_recovery(
        secret="secret",
        destination_reference="subject@example.test",
        idempotency_key="fence:test",
    )

    assert outbox.calls == 1
    assert provider.sends == 1 and sent.status is ProviderDeliveryStatus.ACCEPTED
    assert recovery.calls == 1 and delivered is DeliveryOutcome.DELIVERED
