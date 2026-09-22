from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.platform_configuration.application.smtp import (
    SmtpConfiguration,
    parse_smtp_configuration,
)
from request_engine.platform.secrets.platform_store import PlatformSecretStore


class ActivePlatformConfigurationError(RuntimeError):
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


@dataclass(slots=True)
class _CacheEntry:
    fingerprint: tuple[int, int | None, int | None]
    value: ResolvedSmtpConfiguration
    checked_at: float


class ActivePlatformConfigurationResolver:
    """Resolve managed runtime configuration with bounded stale-cache time.

    PostgreSQL is consulted again after poll_interval_seconds even when no
    notification arrives. invalidate is the fast path used by LISTEN/NOTIFY;
    polling is the correctness backstop.
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
        self._smtp_cache: _CacheEntry | None = None

    def invalidate(self, configuration_kind: str) -> None:
        if configuration_kind == "email.delivery":
            self._smtp_cache = None

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
            if (
                active.secret_binding_id is None
                or active.secret_id is None
                or active.secret_binding_revision is None
                or active.secret_backend_version is None
                or active.secret_purpose != "email.smtp.password"
                or active.secret_backend != "openbao"
                or active.secret_status != "active"
            ):
                raise ActivePlatformConfigurationError(
                    "ACTIVE SMTP secret binding is unavailable or incompatible"
                )
            if self._secret_store is None:
                raise ActivePlatformConfigurationError(
                    "ACTIVE SMTP requires a configured platform secret store"
                )
            password = await self._secret_store.resolve(secret_id=active.secret_id)
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
        self._smtp_cache = _CacheEntry(
            fingerprint=active.cache_fingerprint,
            value=resolved,
            checked_at=now,
        )
        return resolved
