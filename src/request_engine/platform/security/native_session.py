from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.authentication import AuthenticatedSubject
from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    SessionTokenInvalid,
    native_authenticated_subject,
    parse_opaque_token,
    verify_opaque_secret,
)


class NativeSessionStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class NativeIdentityStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class NativeCredentialStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class NativeIdentityAuthorityStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class SessionExpired(SessionTokenInvalid):
    pass


class SessionRevoked(SessionTokenInvalid):
    pass


class NativeIdentityDisabled(SessionTokenInvalid):
    pass


class NativeCredentialRevoked(SessionTokenInvalid):
    pass


class NativeIdentityAuthorityDisabled(SessionTokenInvalid):
    pass


@dataclass(frozen=True, slots=True)
class NativeSessionEvidence:
    raw_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.raw_token:
            raise ValueError("raw_token is required")


@dataclass(frozen=True, slots=True)
class NativeSessionSnapshot:
    session_id: UUID
    native_identity_id: UUID
    identity_authority_id: UUID
    credential_id: UUID
    token_digest: bytes
    session_epoch: int
    current_session_epoch: int
    session_status: NativeSessionStatus
    identity_status: NativeIdentityStatus
    credential_status: NativeCredentialStatus
    expires_at: datetime
    authority_status: NativeIdentityAuthorityStatus = NativeIdentityAuthorityStatus.ACTIVE

    def __post_init__(self) -> None:
        if self.session_epoch <= 0 or self.current_session_epoch <= 0:
            raise ValueError("session epochs must be positive")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")


class NativeSessionReader(Protocol):
    async def read_native_session(self, *, session_id: UUID) -> NativeSessionSnapshot | None: ...


class NativeSessionAuthenticator:
    """Provider-neutral authenticator for opaque RE Native session credentials."""

    def __init__(
        self,
        *,
        session_reader: NativeSessionReader,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_reader = session_reader
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def authenticate(self, evidence: NativeSessionEvidence) -> AuthenticatedSubject:
        parsed = parse_opaque_token(evidence.raw_token)
        session = await self._session_reader.read_native_session(session_id=parsed.token_id)
        if session is None or not verify_opaque_secret(parsed.secret, session.token_digest):
            raise CredentialInvalid("native session credential is invalid")
        if session.authority_status is NativeIdentityAuthorityStatus.DISABLED:
            raise NativeIdentityAuthorityDisabled("native identity authority is disabled")
        if session.session_status is NativeSessionStatus.REVOKED:
            raise SessionRevoked("native session is revoked")
        if session.identity_status is NativeIdentityStatus.DISABLED:
            raise NativeIdentityDisabled("native identity is disabled")
        if session.credential_status is NativeCredentialStatus.REVOKED:
            raise NativeCredentialRevoked("native credential is revoked")
        if session.session_epoch != session.current_session_epoch:
            raise SessionRevoked("native session was globally invalidated")
        if self._clock() >= session.expires_at:
            raise SessionExpired("native session is expired")
        return native_authenticated_subject(
            identity_authority_id=session.identity_authority_id,
            native_identity_id=session.native_identity_id,
        )
