from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoveryDeliveryPermanent,
    RecoveryDeliveryRetryable,
)
from request_engine.platform.security.native_auth import (
    digest_opaque_secret,
    issue_opaque_token,
    normalize_login_handle,
    parse_opaque_token,
)

_DEFAULT_VERIFICATION_TTL = timedelta(minutes=15)
_DEFAULT_RECOVERY_TTL = timedelta(minutes=30)


class NativeRecoveryAddressError(RuntimeError):
    """Base error for self-service verified recovery destinations."""


class NativeRecoveryAddressInvalid(NativeRecoveryAddressError):
    pass


class NativeRecoveryAddressDeliveryUnavailable(NativeRecoveryAddressError):
    pass


@dataclass(frozen=True, slots=True)
class NativeRecoveryAddress:
    address_id: UUID
    kind: str
    normalized_address: str
    status: str
    revision: int
    verified_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NativeRecoveryAddressPrepared:
    address_id: UUID
    status: str
    verification_created: bool


class NativeRecoveryMessenger(Protocol):
    async def send_verification(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome: ...

    async def send_recovery(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome: ...


class NativeRecoveryAddressStore(Protocol):
    async def prepare(
        self,
        *,
        address_id: UUID,
        native_identity_id: UUID,
        kind: str,
        normalized_address: str,
        verification_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        expires_at: datetime,
    ) -> NativeRecoveryAddressPrepared | None: ...

    async def verify(self, *, verification_id: UUID, token_digest: bytes) -> UUID | None: ...

    async def list_for_identity(
        self, *, native_identity_id: UUID
    ) -> tuple[NativeRecoveryAddress, ...]: ...

    async def revoke(self, *, native_identity_id: UUID, address_id: UUID) -> bool: ...

    async def queue_recovery(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
        request_id: UUID,
    ) -> bool: ...


class NativeRecoveryAddressService:
    def __init__(
        self,
        *,
        store: NativeRecoveryAddressStore,
        messenger: NativeRecoveryMessenger | None,
        clock: Callable[[], datetime] | None = None,
        verification_ttl: timedelta = _DEFAULT_VERIFICATION_TTL,
        recovery_ttl: timedelta = _DEFAULT_RECOVERY_TTL,
    ) -> None:
        if verification_ttl <= timedelta(0) or recovery_ttl <= timedelta(0):
            raise ValueError("recovery address TTLs must be positive")
        self._store = store
        self._messenger = messenger
        self._clock = clock or (lambda: datetime.now(UTC))
        self._verification_ttl = verification_ttl
        self._recovery_ttl = recovery_ttl

    async def prepare_email(
        self,
        *,
        native_identity_id: UUID,
        address: str,
    ) -> NativeRecoveryAddressPrepared:
        normalized = normalize_recovery_email(address)
        token = issue_opaque_token()
        prepared = await self._store.prepare(
            address_id=uuid4(),
            native_identity_id=native_identity_id,
            kind="email",
            normalized_address=normalized,
            verification_id=token.token_id,
            token_digest=token.digest,
            token_fingerprint=token.fingerprint,
            expires_at=self._now() + self._verification_ttl,
        )
        if prepared is None:
            raise NativeRecoveryAddressInvalid("recovery address cannot be prepared")
        if not prepared.verification_created:
            return prepared
        if self._messenger is None:
            raise NativeRecoveryAddressDeliveryUnavailable(
                "recovery-address verification delivery is not configured"
            )
        try:
            outcome = await self._messenger.send_verification(
                secret=token.raw_token,
                destination_reference=normalized,
                idempotency_key=f"verify-recovery-address:{token.token_id}",
            )
        except (RecoveryDeliveryPermanent, RecoveryDeliveryRetryable) as exc:
            raise NativeRecoveryAddressDeliveryUnavailable(
                "recovery-address verification delivery is unavailable"
            ) from exc
        if outcome is DeliveryOutcome.FAILED:
            raise NativeRecoveryAddressDeliveryUnavailable(
                "recovery-address verification delivery was rejected"
            )
        return prepared

    async def verify(self, *, raw_token: str) -> UUID:
        try:
            parsed = parse_opaque_token(raw_token)
        except ValueError as exc:
            raise NativeRecoveryAddressInvalid("recovery-address proof is invalid") from exc
        identity_id = await self._store.verify(
            verification_id=parsed.token_id,
            token_digest=digest_opaque_secret(parsed.secret),
        )
        if identity_id is None:
            raise NativeRecoveryAddressInvalid("recovery-address proof is invalid")
        return identity_id

    async def list_for_identity(
        self, *, native_identity_id: UUID
    ) -> tuple[NativeRecoveryAddress, ...]:
        return await self._store.list_for_identity(native_identity_id=native_identity_id)

    async def revoke(self, *, native_identity_id: UUID, address_id: UUID) -> None:
        if not await self._store.revoke(
            native_identity_id=native_identity_id,
            address_id=address_id,
        ):
            raise NativeRecoveryAddressInvalid("recovery address is unavailable")

    async def request_recovery(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
    ) -> None:
        # Public callers always receive the same HTTP result. The request path
        # performs database-only enqueue work; provider and secret-store I/O belongs
        # to the fenced delivery worker so account existence cannot be inferred from
        # SMTP/OpenBao latency.
        try:
            normalized_handle = normalize_login_handle(login_handle)
        except ValueError:
            return
        await self._store.queue_recovery(
            identity_authority_id=identity_authority_id,
            login_handle=normalized_handle,
            request_id=uuid4(),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("recovery clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


def normalize_recovery_email(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not 3 <= len(normalized) <= 320:
        raise NativeRecoveryAddressInvalid("recovery email length is invalid")
    if normalized.count("@") != 1 or any(character.isspace() for character in normalized):
        raise NativeRecoveryAddressInvalid("recovery email is invalid")
    local, domain = normalized.split("@", 1)
    if not local or not domain or "." not in domain:
        raise NativeRecoveryAddressInvalid("recovery email is invalid")
    return normalized
