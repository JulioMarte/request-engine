from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from request_engine.modules.booking.adapters.appointment_signing_reference import (
    ActiveAppointmentSigningReference,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretNotFound,
    PlatformSecretStore,
    PlatformSecretStoreUnavailable,
)
from request_engine.platform.security.appointment_option_keyring import (
    AppointmentOptionKeyring,
    parse_appointment_option_keyring,
)


class AppointmentSigningReferenceSource(Protocol):
    async def read_active(self) -> ActiveAppointmentSigningReference | None: ...


class AppointmentSigningKeyringUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class _CacheEntry:
    fingerprint: tuple[int, int, int]
    keyring: AppointmentOptionKeyring
    checked_at: float


class ManagedAppointmentSigningKeyringResolver:
    """Resolve the ACTIVE keyring through a signing-family-only secret store."""

    def __init__(
        self,
        *,
        source: AppointmentSigningReferenceSource,
        secret_store: PlatformSecretStore,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        if poll_interval_seconds <= 0 or poll_interval_seconds > 300:
            raise ValueError("signing keyring poll interval must be > 0 and <= 300 seconds")
        self._source = source
        self._secret_store = secret_store
        self._poll_interval_seconds = poll_interval_seconds
        self._cache: _CacheEntry | None = None

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval_seconds

    async def resolve(
        self,
        *,
        force_refresh: bool = False,
    ) -> AppointmentOptionKeyring | None:
        now = time.monotonic()
        cached = self._cache
        if (
            not force_refresh
            and cached is not None
            and now - cached.checked_at < self._poll_interval_seconds
        ):
            return cached.keyring

        reference = await self._source.read_active()
        if reference is None:
            self._cache = None
            return None
        if cached is not None and cached.fingerprint == reference.fingerprint and not force_refresh:
            cached.checked_at = now
            return cached.keyring

        try:
            value = await self._secret_store.resolve(secret_id=reference.secret_id)
        except (PlatformSecretNotFound, PlatformSecretStoreUnavailable) as exc:
            raise AppointmentSigningKeyringUnavailable(
                "ACTIVE appointment signing keyring could not be resolved"
            ) from exc
        try:
            keyring = parse_appointment_option_keyring(value)
        except ValueError as exc:
            raise AppointmentSigningKeyringUnavailable(
                "ACTIVE appointment signing keyring is invalid"
            ) from exc

        self._cache = _CacheEntry(
            fingerprint=reference.fingerprint,
            keyring=keyring,
            checked_at=now,
        )
        return keyring
