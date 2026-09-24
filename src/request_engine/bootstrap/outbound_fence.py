"""Fail-closed deployment fence for outbound side effects.

Fresh/cloned/restored production-shaped processes start fenced unless the
operator explicitly enables outbound effects.  This is a technical deployment
boundary: business modules remain unaware of clone/environment policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict

from request_engine.entrypoints.worker.outbox_runtime import OutboxEvent, OutboxPublisher
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
    SmtpConfigurationValidator,
    SmtpProviderTester,
)
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryRetryable,
    RecoverySecretDelivery,
    StagedRecoverySecret,
)
from request_engine.platform.secrets.delivery_parts import RecoveryDeliveryChannel
from request_engine.platform.security.native_recovery_addresses import NativeRecoveryMessenger


class OutboundFenceSettings(BaseSettings):
    """Deployment policy.  Absence deliberately means fenced."""

    model_config = SettingsConfigDict(
        env_prefix="REQUEST_ENGINE_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    outbound_fenced: bool = True


class RecoveryOutboundChannel(RecoveryDeliveryChannel, NativeRecoveryMessenger, Protocol):
    """Combined structural contract implemented by the reference SMTP channels."""


@dataclass(frozen=True, slots=True)
class OutboundSideEffectFence:
    fenced: bool

    @classmethod
    def from_environment(cls) -> "OutboundSideEffectFence":
        return cls(fenced=OutboundFenceSettings().outbound_fenced)

    def outbox(self, publisher: OutboxPublisher) -> OutboxPublisher:
        return publisher if not self.fenced else _FencedOutboxPublisher(publisher, self)

    def communications(
        self,
        providers: Mapping[str, CommunicationDeliveryProvider],
    ) -> Mapping[str, CommunicationDeliveryProvider]:
        if not self.fenced:
            return providers
        return {
            key: _FencedCommunicationDeliveryProvider(provider, self)
            for key, provider in providers.items()
        }

    def recovery(
        self,
        channel: RecoveryOutboundChannel | None,
    ) -> RecoveryOutboundChannel | None:
        if channel is None or not self.fenced:
            return channel
        return _FencedRecoveryDeliveryChannel(channel, self)

    def secret_delivery(
        self,
        delivery: RecoverySecretDelivery | None,
    ) -> RecoverySecretDelivery | None:
        if delivery is None or not self.fenced:
            return delivery
        return _FencedRecoverySecretDelivery(delivery, self)

    def smtp_validator(
        self,
        validator: SmtpConfigurationValidator,
    ) -> SmtpConfigurationValidator:
        return validator if not self.fenced else _FencedSmtpConfigurationValidator(validator, self)

    def smtp_tester(self, tester: SmtpProviderTester) -> SmtpProviderTester:
        return tester if not self.fenced else _FencedSmtpProviderTester(tester, self)


class _FencedOutboxPublisher:
    def __init__(self, inner: OutboxPublisher, fence: OutboundSideEffectFence) -> None:
        self._inner = inner
        self._fence = fence

    async def publish(self, event: OutboxEvent) -> None:
        if self._fence.fenced:
            raise RuntimeError("outbound side effects are fenced")
        await self._inner.publish(event)


class _FencedCommunicationDeliveryProvider:
    def __init__(
        self,
        inner: CommunicationDeliveryProvider,
        fence: OutboundSideEffectFence,
    ) -> None:
        self._inner = inner
        self._fence = fence

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        if self._fence.fenced:
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=True,
                result_data={
                    "error_class": "outbound_fenced",
                    "error_phase": "clone_fence",
                },
            )
        return await self._inner.send(request)

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        if self._fence.fenced:
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.AMBIGUOUS,
                retryable=False,
                result_data={
                    "error_class": "outbound_fenced",
                    "error_phase": "clone_fence",
                },
            )
        return await self._inner.lookup(request)


class _FencedRecoveryDeliveryChannel:
    def __init__(
        self,
        inner: RecoveryOutboundChannel,
        fence: OutboundSideEffectFence,
    ) -> None:
        self._inner = inner
        self._fence = fence

    def _require_open(self) -> None:
        if self._fence.fenced:
            raise RecoveryDeliveryRetryable("outbound recovery delivery is fenced")

    async def send(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        self._require_open()
        return await self._inner.send(
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
        self._require_open()
        return await self._inner.send_recovery(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def send_verification(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        self._require_open()
        return await self._inner.send_verification(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def reconcile(self, *, idempotency_key: str) -> DeliveryOutcome | None:
        self._require_open()
        return await self._inner.reconcile(idempotency_key=idempotency_key)


class _FencedRecoverySecretDelivery:
    """Allow local secret staging while preventing provider publication."""

    def __init__(
        self,
        inner: RecoverySecretDelivery,
        fence: OutboundSideEffectFence,
    ) -> None:
        self._inner = inner
        self._fence = fence

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        return await self._inner.stage(
            case_id=case_id,
            generation=generation,
            secret=secret,
            expires_at=expires_at,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        await self._inner.discard(case_id=case_id, generation=generation)

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        if self._fence.fenced:
            raise RecoveryDeliveryRetryable("outbound recovery delivery is fenced")
        return await self._inner.publish(
            reference=reference,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def reconcile(
        self,
        *,
        reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome | None:
        if self._fence.fenced:
            raise RecoveryDeliveryRetryable("outbound recovery delivery is fenced")
        return await self._inner.reconcile(
            reference=reference,
            idempotency_key=idempotency_key,
        )


class _FencedSmtpConfigurationValidator:
    def __init__(
        self,
        inner: SmtpConfigurationValidator,
        fence: OutboundSideEffectFence,
    ) -> None:
        self._inner = inner
        self._fence = fence

    async def validate(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
    ) -> ProviderValidationResult:
        if self._fence.fenced:
            return ProviderValidationResult(
                ProviderValidationStatus.UNAVAILABLE,
                "outbound_fenced",
            )
        return await self._inner.validate(configuration, password=password)


class _FencedSmtpProviderTester:
    def __init__(
        self,
        inner: SmtpProviderTester,
        fence: OutboundSideEffectFence,
    ) -> None:
        self._inner = inner
        self._fence = fence

    async def test(
        self,
        configuration: SmtpConfiguration,
        *,
        password: str | None,
        destination: str,
        idempotency_key: str,
    ) -> ProviderTestResult:
        if self._fence.fenced:
            return ProviderTestResult(
                ProviderTestOutcome.FAILED,
                "outbound_fenced",
            )
        return await self._inner.test(
            configuration,
            password=password,
            destination=destination,
            idempotency_key=idempotency_key,
        )
