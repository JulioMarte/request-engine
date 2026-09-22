from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.platform_configuration.application.smtp import (
    SmtpConfiguration,
    parse_smtp_configuration,
)
from request_engine.modules.platform_configuration.application.webhook import (
    parse_webhook_configuration,
)
from request_engine.modules.platform_configuration.contracts.runtime import (
    PlatformRuntimeConfigurationError,
    ResolvedWebhookConfiguration,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretNotFound,
    PlatformSecretStore,
    PlatformSecretStoreUnavailable,
)


class ActivePlatformConfigurationError(PlatformRuntimeConfigurationError):
    pass


@dataclass(frozen=True, slots=True)
class ActivePlatformConfiguration:
    configuration_revision_id: UUID
    configuration_kind: str
    provider_kind: str
    revision: int
    configuration: dict[str, object]
    secret_binding_id: UUID | None
    secret_binding_revision: int | None
    secret_id: UUID | None
    secret_purpose: str | None
    secret_backend: str | None
    secret_backend_version: int | None
    secret_status: str | None

    @property
    def cache_fingerprint(self) -> tuple[int, int | None, int | None]:
        return (
            self.revision,
            self.secret_binding_revision,
            self.secret_backend_version,
        )


@dataclass(frozen=True, slots=True)
class ResolvedSmtpConfiguration:
    configuration: SmtpConfiguration
    password: str | None
    active_revision: int
    secret_binding_revision: int | None
    secret_backend_version: int | None
    source: str = "managed"


class ActivePlatformConfigurationSource(Protocol):
    async def read_active(
        self,
        configuration_kind: str,
    ) -> ActivePlatformConfiguration | None: ...

    async def read_revision(
        self,
        configuration_kind: str,
        revision: int,
    ) -> ActivePlatformConfiguration | None: ...


@dataclass(slots=True)
class _SmtpCacheEntry:
    fingerprint: tuple[int, int | None, int | None]
    value: ResolvedSmtpConfiguration
    checked_at: float


@dataclass(slots=True)
class _WebhookCacheEntry:
    fingerprint: tuple[int, int | None, int | None]
    value: ResolvedWebhookConfiguration
    checked_at: float


class ActivePlatformConfigurationResolver:
    """Resolve governed runtime configuration with bounded stale-cache time.

    PostgreSQL is consulted again after the polling interval even when no
    notification arrives. invalidate is the LISTEN/NOTIFY fast path;
    PostgreSQL remains the correctness authority.

    Webhook reconciliation may resolve an exact SUPERSEDED revision so an
    in-flight delivery does not jump to a newly activated provider endpoint.
    """

    def __init__(
        self,
        *,
        source: ActivePlatformConfigurationSource,
        secret_store: PlatformSecretStore | None,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        if poll_interval_seconds <= 0 or poll_interval_seconds > 300:
            raise ValueError("poll interval must be > 0 and <= 300 seconds")
        self._source = source
        self._secret_store = secret_store
        self._poll_interval_seconds = poll_interval_seconds
        self._smtp_cache: _SmtpCacheEntry | None = None
        self._webhook_active_cache: _WebhookCacheEntry | None = None
        self._webhook_revision_cache: dict[int, _WebhookCacheEntry] = {}

    def invalidate(self, configuration_kind: str) -> None:
        if configuration_kind == "email.delivery":
            self._smtp_cache = None
        elif configuration_kind == "communications.webhook":
            self._webhook_active_cache = None
            self._webhook_revision_cache.clear()

    async def resolve_smtp(
        self,
        *,
        force_refresh: bool = False,
    ) -> ResolvedSmtpConfiguration | None:
        now = time.monotonic()
        cached = self._smtp_cache
        if (
            not force_refresh
            and cached is not None
            and now - cached.checked_at < self._poll_interval_seconds
        ):
            return cached.value

        active = await self._source.read_active("email.delivery")
        if active is None:
            self._smtp_cache = None
            return None
        if active.provider_kind != "smtp":
            raise ActivePlatformConfigurationError("ACTIVE email.delivery provider is not SMTP")

        if (
            cached is not None
            and cached.fingerprint == active.cache_fingerprint
            and not force_refresh
        ):
            cached.checked_at = now
            return cached.value

        try:
            smtp = parse_smtp_configuration(active.configuration)
        except (TypeError, ValueError) as exc:
            raise ActivePlatformConfigurationError("ACTIVE SMTP configuration is invalid") from exc

        password: str | None = None
        if smtp.username is not None:
            password = await self._resolve_secret(
                active,
                expected_purpose="email.smtp.password",
                missing_message="ACTIVE SMTP secret binding is unavailable or incompatible",
                store_message="ACTIVE SMTP requires a configured platform secret store",
            )
        elif active.secret_binding_id is not None:
            raise ActivePlatformConfigurationError(
                "Unauthenticated SMTP must not reference a secret binding"
            )

        resolved = ResolvedSmtpConfiguration(
            configuration=smtp,
            password=password,
            active_revision=active.revision,
            secret_binding_revision=active.secret_binding_revision,
            secret_backend_version=active.secret_backend_version,
        )
        self._smtp_cache = _SmtpCacheEntry(
            fingerprint=active.cache_fingerprint,
            value=resolved,
            checked_at=now,
        )
        return resolved

    async def resolve_webhook(
        self,
        *,
        revision: int | None = None,
        force_refresh: bool = False,
    ) -> ResolvedWebhookConfiguration | None:
        if revision is not None and revision <= 0:
            raise ValueError("webhook configuration revision must be positive")
        if revision is None:
            return await self._resolve_active_webhook(force_refresh=force_refresh)
        return await self._resolve_exact_webhook(
            revision,
            force_refresh=force_refresh,
        )

    async def _resolve_active_webhook(
        self,
        *,
        force_refresh: bool,
    ) -> ResolvedWebhookConfiguration | None:
        now = time.monotonic()
        cached = self._webhook_active_cache
        if (
            not force_refresh
            and cached is not None
            and now - cached.checked_at < self._poll_interval_seconds
        ):
            return cached.value

        active = await self._source.read_active("communications.webhook")
        if active is None:
            self._webhook_active_cache = None
            return None
        resolved = await self._materialize_webhook(active)

        if (
            cached is not None
            and cached.fingerprint == active.cache_fingerprint
            and not force_refresh
        ):
            cached.checked_at = now
            return cached.value

        entry = _WebhookCacheEntry(
            fingerprint=active.cache_fingerprint,
            value=resolved,
            checked_at=now,
        )
        self._webhook_active_cache = entry
        self._webhook_revision_cache[active.revision] = entry
        return resolved

    async def _resolve_exact_webhook(
        self,
        revision: int,
        *,
        force_refresh: bool,
    ) -> ResolvedWebhookConfiguration | None:
        now = time.monotonic()
        cached = self._webhook_revision_cache.get(revision)
        if (
            not force_refresh
            and cached is not None
            and now - cached.checked_at < self._poll_interval_seconds
        ):
            return cached.value

        observed = await self._source.read_revision("communications.webhook", revision)
        if observed is None:
            self._webhook_revision_cache.pop(revision, None)
            return None
        resolved = await self._materialize_webhook(observed)
        if (
            cached is not None
            and cached.fingerprint == observed.cache_fingerprint
            and not force_refresh
        ):
            cached.checked_at = now
            return cached.value

        entry = _WebhookCacheEntry(
            fingerprint=observed.cache_fingerprint,
            value=resolved,
            checked_at=now,
        )
        self._webhook_revision_cache[revision] = entry
        return resolved

    async def _materialize_webhook(
        self,
        observed: ActivePlatformConfiguration,
    ) -> ResolvedWebhookConfiguration:
        if observed.provider_kind != "webhook":
            raise ActivePlatformConfigurationError(
                "communications.webhook provider is not webhook"
            )
        try:
            webhook = parse_webhook_configuration(observed.configuration)
        except (TypeError, ValueError) as exc:
            raise ActivePlatformConfigurationError(
                "managed webhook configuration is invalid"
            ) from exc

        auth_header_value: str | None = None
        if webhook.auth_header_name is not None:
            auth_header_value = await self._resolve_secret(
                observed,
                expected_purpose="communications.webhook.auth_header",
                missing_message=(
                    "managed webhook secret binding is unavailable or incompatible"
                ),
                store_message=(
                    "authenticated managed webhook requires a configured platform secret store"
                ),
            )
        elif observed.secret_binding_id is not None:
            raise ActivePlatformConfigurationError(
                "unauthenticated managed webhook must not reference a secret binding"
            )

        return ResolvedWebhookConfiguration(
            base_url=webhook.base_url,
            auth_header_name=webhook.auth_header_name,
            auth_header_value=auth_header_value,
            timeout_seconds=webhook.timeout_seconds,
            configuration_revision=observed.revision,
            secret_binding_revision=observed.secret_binding_revision,
            secret_backend_version=observed.secret_backend_version,
        )

    async def _resolve_secret(
        self,
        observed: ActivePlatformConfiguration,
        *,
        expected_purpose: str,
        missing_message: str,
        store_message: str,
    ) -> str:
        if (
            observed.secret_binding_id is None
            or observed.secret_id is None
            or observed.secret_binding_revision is None
            or observed.secret_backend_version is None
            or observed.secret_purpose != expected_purpose
            or observed.secret_backend != "openbao"
            or observed.secret_status != "active"
        ):
            raise ActivePlatformConfigurationError(missing_message)
        if self._secret_store is None:
            raise ActivePlatformConfigurationError(store_message)
        try:
            return await self._secret_store.resolve(secret_id=observed.secret_id)
        except (PlatformSecretNotFound, PlatformSecretStoreUnavailable) as exc:
            raise ActivePlatformConfigurationError(store_message) from exc
