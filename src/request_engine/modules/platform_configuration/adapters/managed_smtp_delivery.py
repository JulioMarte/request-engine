from __future__ import annotations

from request_engine.modules.platform_configuration.application.runtime import (
    ActivePlatformConfigurationError,
    ActivePlatformConfigurationResolver,
)
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryRetryable,
)
from request_engine.platform.secrets.delivery_parts import RecoveryDeliveryChannel
from request_engine.platform.secrets.smtp_delivery_channel import (
    SmtpRecoveryDeliveryChannel,
)


class ManagedSmtpRecoveryDeliveryChannel(RecoveryDeliveryChannel):
    """Resolve the ACTIVE SMTP provider immediately before each delivery."""

    def __init__(
        self,
        *,
        resolver: ActivePlatformConfigurationResolver,
        fallback: SmtpRecoveryDeliveryChannel | None = None,
        reset_url: str | None = None,
    ) -> None:
        self._resolver = resolver
        self._fallback = fallback
        self._reset_url = reset_url

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
        channel = await self._resolved_channel()
        if channel is None:
            assert self._fallback is not None
            return await self._fallback.send(
                secret=secret,
                destination_reference=destination_reference,
                idempotency_key=idempotency_key,
            )
        return await channel.send_recovery(
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
        channel = await self._resolved_channel()
        if channel is None:
            fallback = self._fallback
            if fallback is None:
                raise RecoveryDeliveryRetryable(
                    "SMTP is neither managed nor bootstrap-configured"
                )
            return await fallback.send_verification(
                secret=secret,
                destination_reference=destination_reference,
                idempotency_key=idempotency_key,
            )
        return await channel.send_verification(
            secret=secret,
            destination_reference=destination_reference,
            idempotency_key=idempotency_key,
        )

    async def _resolved_channel(self) -> SmtpRecoveryDeliveryChannel | None:
        try:
            managed = await self._resolver.resolve_smtp()
        except (ActivePlatformConfigurationError, RuntimeError) as exc:
            raise RecoveryDeliveryRetryable(
                "managed SMTP configuration is temporarily unavailable"
            ) from exc

        if managed is None:
            if self._fallback is None:
                raise RecoveryDeliveryRetryable(
                    "SMTP is neither managed nor bootstrap-configured"
                )
            return None

        smtp = managed.configuration
        return SmtpRecoveryDeliveryChannel(
            host=smtp.host,
            port=smtp.port,
            sender=smtp.sender,
            username=smtp.username,
            password=managed.password,
            starttls=smtp.security.value == "starttls",
            use_ssl=smtp.security.value == "tls",
            timeout_seconds=smtp.timeout_seconds,
            reset_url=self._reset_url,
        )

    async def reconcile(self, *, idempotency_key: str) -> DeliveryOutcome | None:
        # SMTP has no provider-side query API. UNKNOWN remains terminal for the
        # existing delivery processor and is never blindly retransmitted.
        del idempotency_key
        return None
