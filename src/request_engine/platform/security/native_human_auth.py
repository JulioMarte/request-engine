from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeGuard
from uuid import UUID, uuid4

from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    digest_opaque_secret,
    hash_password,
    issue_opaque_token,
    normalize_login_handle,
    parse_opaque_token,
    verify_password,
)
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityStatus,
)

_DEFAULT_SESSION_TTL = timedelta(hours=12)
_DEFAULT_RECOVERY_TTL = timedelta(minutes=30)


class NativeHumanAuthError(RuntimeError):
    """Base class for Native HUMAN lifecycle failures."""


class NativeIdentityAlreadyExists(NativeHumanAuthError):
    pass


class NativeIdentityNotFound(NativeHumanAuthError):
    pass


class RecoveryIntentInvalid(NativeHumanAuthError):
    pass


@dataclass(frozen=True, slots=True)
class NativePasswordCredentialSnapshot:
    native_identity_id: UUID
    credential_id: UUID
    verifier: str
    identity_status: NativeIdentityStatus
    credential_status: NativeCredentialStatus
    session_epoch: int
    identity_revision: int
    credential_revision: int

    def __post_init__(self) -> None:
        if self.session_epoch <= 0:
            raise ValueError("session_epoch must be positive")
        if self.identity_revision <= 0 or self.credential_revision <= 0:
            raise ValueError("credential revisions must be positive")


@dataclass(frozen=True, slots=True)
class NativeIdentityEnrollment:
    native_identity_id: UUID
    credential_id: UUID
    login_handle: str


@dataclass(frozen=True, slots=True)
class NativeSessionIssued:
    native_identity_id: UUID
    credential_id: UUID
    session_id: UUID
    raw_token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class NativeRecoveryIssued:
    native_identity_id: UUID
    recovery_id: UUID
    raw_token: str = field(repr=False)
    expires_at: datetime


class NativeHumanAuthStore(Protocol):
    async def read_password_credential(
        self, *, identity_authority_id: UUID, login_handle: str
    ) -> NativePasswordCredentialSnapshot | None: ...

    async def create_identity(
        self,
        *,
        identity_authority_id: UUID,
        native_identity_id: UUID,
        login_handle: str,
        credential_id: UUID,
        verifier: str,
    ) -> bool: ...

    async def create_session(
        self,
        *,
        native_identity_id: UUID,
        credential_id: UUID,
        session_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        expires_at: datetime,
    ) -> bool: ...

    async def revoke_session(
        self, *, native_identity_id: UUID, session_id: UUID, reason: str
    ) -> bool: ...

    async def revoke_all_sessions(self, *, native_identity_id: UUID, reason: str) -> bool: ...

    async def rotate_password(
        self,
        *,
        native_identity_id: UUID,
        expected_credential_id: UUID,
        new_credential_id: UUID,
        new_verifier: str,
        reason: str,
    ) -> bool: ...

    async def disable_identity(self, *, native_identity_id: UUID, reason: str) -> bool: ...

    async def create_recovery_intent(
        self,
        *,
        native_identity_id: UUID,
        recovery_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        expires_at: datetime,
    ) -> bool: ...

    async def consume_recovery_intent(
        self,
        *,
        recovery_id: UUID,
        token_digest: bytes,
        new_credential_id: UUID,
        new_verifier: str,
    ) -> UUID | None: ...


class NativeHumanAuthService:
    """Own providerless HUMAN credential/session semantics without business authority.

    Raw passwords and opaque tokens never cross the store boundary. Password
    hashing/verification is moved off the event loop. Principal authority is
    resolved independently for every protected request.
    """

    def __init__(
        self,
        *,
        store: NativeHumanAuthStore,
        clock: Callable[[], datetime] | None = None,
        session_ttl: timedelta = _DEFAULT_SESSION_TTL,
        recovery_ttl: timedelta = _DEFAULT_RECOVERY_TTL,
    ) -> None:
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        if recovery_ttl <= timedelta(0):
            raise ValueError("recovery_ttl must be positive")
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._session_ttl = session_ttl
        self._recovery_ttl = recovery_ttl

    async def enroll_password_identity(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
        password: str,
    ) -> NativeIdentityEnrollment:
        normalized = normalize_login_handle(login_handle)
        native_identity_id = uuid4()
        credential_id = uuid4()
        verifier = await asyncio.to_thread(hash_password, password)
        created = await self._store.create_identity(
            identity_authority_id=identity_authority_id,
            native_identity_id=native_identity_id,
            login_handle=normalized,
            credential_id=credential_id,
            verifier=verifier,
        )
        if not created:
            raise NativeIdentityAlreadyExists("native login handle is already enrolled")
        return NativeIdentityEnrollment(
            native_identity_id=native_identity_id,
            credential_id=credential_id,
            login_handle=normalized,
        )

    async def authenticate_password(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
        password: str,
    ) -> NativeSessionIssued:
        snapshot = await self._store.read_password_credential(
            identity_authority_id=identity_authority_id,
            login_handle=normalize_login_handle(login_handle),
        )
        if not _credential_is_usable(snapshot):
            raise CredentialInvalid("native credential is invalid")
        if not await asyncio.to_thread(verify_password, password, snapshot.verifier):
            raise CredentialInvalid("native credential is invalid")

        token = issue_opaque_token()
        expires_at = self._now() + self._session_ttl
        created = await self._store.create_session(
            native_identity_id=snapshot.native_identity_id,
            credential_id=snapshot.credential_id,
            session_id=token.token_id,
            token_digest=token.digest,
            token_fingerprint=token.fingerprint,
            expires_at=expires_at,
        )
        if not created:
            raise CredentialInvalid("native credential is no longer usable")
        return NativeSessionIssued(
            native_identity_id=snapshot.native_identity_id,
            credential_id=snapshot.credential_id,
            session_id=token.token_id,
            raw_token=token.raw_token,
            expires_at=expires_at,
        )

    async def revoke_session(
        self, *, native_identity_id: UUID, session_id: UUID, reason: str = "logout"
    ) -> None:
        await self._store.revoke_session(
            native_identity_id=native_identity_id,
            session_id=session_id,
            reason=_reason(reason),
        )

    async def revoke_all_sessions(
        self, *, native_identity_id: UUID, reason: str = "logout_all"
    ) -> None:
        revoked = await self._store.revoke_all_sessions(
            native_identity_id=native_identity_id,
            reason=_reason(reason),
        )
        if not revoked:
            raise NativeIdentityNotFound("native identity does not exist")

    async def rotate_password(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
        current_password: str,
        new_password: str,
    ) -> UUID:
        snapshot = await self._store.read_password_credential(
            identity_authority_id=identity_authority_id,
            login_handle=normalize_login_handle(login_handle),
        )
        if not _credential_is_usable(snapshot):
            raise CredentialInvalid("native credential is invalid")
        if not await asyncio.to_thread(verify_password, current_password, snapshot.verifier):
            raise CredentialInvalid("native credential is invalid")

        new_credential_id = uuid4()
        new_verifier = await asyncio.to_thread(hash_password, new_password)
        rotated = await self._store.rotate_password(
            native_identity_id=snapshot.native_identity_id,
            expected_credential_id=snapshot.credential_id,
            new_credential_id=new_credential_id,
            new_verifier=new_verifier,
            reason="credential_rotation",
        )
        if not rotated:
            raise CredentialInvalid("native credential is no longer usable")
        return new_credential_id

    async def disable_identity(
        self, *, native_identity_id: UUID, reason: str = "identity_disabled"
    ) -> None:
        disabled = await self._store.disable_identity(
            native_identity_id=native_identity_id,
            reason=_reason(reason),
        )
        if not disabled:
            raise NativeIdentityNotFound("native identity is not active")

    async def issue_recovery(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
    ) -> NativeRecoveryIssued | None:
        snapshot = await self._store.read_password_credential(
            identity_authority_id=identity_authority_id,
            login_handle=normalize_login_handle(login_handle),
        )
        if not _credential_is_usable(snapshot):
            return None
        token = issue_opaque_token()
        expires_at = self._now() + self._recovery_ttl
        created = await self._store.create_recovery_intent(
            native_identity_id=snapshot.native_identity_id,
            recovery_id=token.token_id,
            token_digest=token.digest,
            token_fingerprint=token.fingerprint,
            expires_at=expires_at,
        )
        if not created:
            return None
        return NativeRecoveryIssued(
            native_identity_id=snapshot.native_identity_id,
            recovery_id=token.token_id,
            raw_token=token.raw_token,
            expires_at=expires_at,
        )

    async def consume_recovery(self, *, raw_token: str, new_password: str) -> UUID:
        parsed = parse_opaque_token(raw_token)
        new_verifier = await asyncio.to_thread(hash_password, new_password)
        native_identity_id = await self._store.consume_recovery_intent(
            recovery_id=parsed.token_id,
            token_digest=digest_opaque_secret(parsed.secret),
            new_credential_id=uuid4(),
            new_verifier=new_verifier,
        )
        if native_identity_id is None:
            raise RecoveryIntentInvalid("recovery intent is invalid, expired, or already consumed")
        return native_identity_id

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise RuntimeError("Native auth clock must return timezone-aware datetimes")
        return value


def _credential_is_usable(
    snapshot: NativePasswordCredentialSnapshot | None,
) -> TypeGuard[NativePasswordCredentialSnapshot]:
    return bool(
        snapshot is not None
        and snapshot.identity_status is NativeIdentityStatus.ACTIVE
        and snapshot.credential_status is NativeCredentialStatus.ACTIVE
    )


def _reason(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise ValueError("revocation reason must contain between 1 and 200 characters")
    return normalized
