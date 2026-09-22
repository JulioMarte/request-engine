from __future__ import annotations

from collections.abc import Callable

from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    WebhookDeliveryProvider,
)
from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)
from request_engine.modules.platform_configuration.contracts.runtime import (
    ActiveWebhookConfigurationResolver,
    PlatformRuntimeConfigurationError,
    ResolvedWebhookConfiguration,
)


class ManagedWebhookDeliveryProvider:
    """Resolve governed webhook configuration without breaking delivery lineage."""

    def __init__(
        self,
        *,
        resolver: ActiveWebhookConfigurationResolver,
        fallback: CommunicationDeliveryProvider | None = None,
        provider_factory: Callable[[ResolvedWebhookConfiguration], CommunicationDeliveryProvider]
        | None = None,
    ) -> None:
        self._resolver = resolver
        self._fallback = fallback
        self._provider_factory = provider_factory or _build_provider

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        try:
            managed = await self._resolver.resolve_webhook()
        except PlatformRuntimeConfigurationError as exc:
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=True,
                result_data={
                    "error_class": type(exc).__name__,
                    "error_phase": "provider_resolution",
                },
            )

        if managed is None:
            if self._fallback is None:
                return _not_configured()
            result = await self._fallback.send(request)
            return _tag_result(
                result,
                source="bootstrap",
                revision=None,
            )

        result = await self._provider_factory(managed).send(request)
        return _tag_result(
            result,
            source="managed",
            revision=managed.configuration_revision,
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        source = request.provider_configuration_source
        revision = request.provider_configuration_revision

        if source == "bootstrap":
            if self._fallback is None:
                return _ambiguous_configuration("bootstrap_provider_unavailable")
            return await self._fallback.lookup(request)

        if source == "managed":
            if revision is None:
                return _ambiguous_configuration("managed_provider_revision_missing")
            return await self._managed_lookup(request, revision)

        # Deliveries created before configuration pinning necessarily used the
        # bootstrap provider. Never reinterpret that old lineage as the current
        # managed endpoint merely because P7 was activated later.
        if source is None and revision is None:
            if self._fallback is None:
                return _ambiguous_configuration("legacy_provider_unavailable")
            return await self._fallback.lookup(request)

        return _ambiguous_configuration("provider_configuration_pin_invalid")

    async def _managed_lookup(
        self,
        request: ProviderLookupRequest,
        revision: int,
    ) -> ProviderDeliveryResult:
        try:
            managed = await self._resolver.resolve_webhook(revision=revision)
        except PlatformRuntimeConfigurationError as exc:
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.AMBIGUOUS,
                retryable=False,
                result_data={
                    "error_class": type(exc).__name__,
                    "error_phase": "provider_resolution",
                    "provider_configuration_source": "managed",
                    "provider_configuration_revision": revision,
                },
            )
        if managed is None:
            return _ambiguous_configuration(
                "managed_provider_revision_unavailable",
                revision=revision,
            )
        result = await self._provider_factory(managed).lookup(request)
        return _tag_result(result, source="managed", revision=revision)


def _build_provider(
    configuration: ResolvedWebhookConfiguration,
) -> CommunicationDeliveryProvider:
    auth_header = (
        None
        if configuration.auth_header_name is None
        else (
            configuration.auth_header_name,
            configuration.auth_header_value or "",
        )
    )
    return WebhookDeliveryProvider(
        configuration.base_url,
        auth_header=auth_header,
        timeout_seconds=configuration.timeout_seconds,
    )


def _tag_result(
    result: ProviderDeliveryResult,
    *,
    source: str,
    revision: int | None,
) -> ProviderDeliveryResult:
    data = {
        **result.result_data,
        "provider_configuration_source": source,
    }
    if revision is not None:
        data["provider_configuration_revision"] = revision
    return ProviderDeliveryResult(
        status=result.status,
        provider_message_id=result.provider_message_id,
        retryable=result.retryable,
        result_data=data,
    )


def _not_configured() -> ProviderDeliveryResult:
    return ProviderDeliveryResult(
        status=ProviderDeliveryStatus.FAILED,
        retryable=False,
        result_data={
            "error_class": "provider_not_configured",
            "error_phase": "provider_resolution",
        },
    )


def _ambiguous_configuration(
    error_class: str,
    *,
    revision: int | None = None,
) -> ProviderDeliveryResult:
    data: dict[str, object] = {
        "error_class": error_class,
        "error_phase": "provider_resolution",
    }
    if revision is not None:
        data["provider_configuration_source"] = "managed"
        data["provider_configuration_revision"] = revision
    return ProviderDeliveryResult(
        status=ProviderDeliveryStatus.AMBIGUOUS,
        retryable=False,
        result_data=data,
    )
