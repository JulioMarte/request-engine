from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.assurance import (
    AuthenticationAssurance,
    classify_assurance,
    evidence_from_values,
)
from request_engine.platform.security.authentication import AuthenticatedSubject
from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    SessionTokenInvalid,
    native_authenticated_subject,
    parse_opaque_token,
    verify_opaque_secret,
)

_ACTIVITY_TOUCH_INTERVAL_SECONDS = 60


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
    """Method-neutral durable session facts read through the auth boundary.

    Exactly one initial authenticator is present (password or WebAuthn) and its
    current status is exposed so the authenticator can fail closed if it is
    revoked. Assurance is the assurance actually achieved by the ceremony, not a
    value derived from the mere presence of a credential row.
    """

    session_id: UUID
    native_identity_id: UUID
    identity_authority_id: UUID
    password_credential_id: UUID | None
    password_credential_status: NativeCredentialStatus | None
    webauthn_credential_id: UUID | None
    webauthn_credential_status: NativeCredentialStatus | None
    token_digest: bytes
    session_epoch: int
    current_session_epoch: int
    session_status: NativeSessionStatus
    identity_status: NativeIdentityStatus
    authority_status: NativeIdentityAuthorityStatus
    authentication_methods: tuple[str, ...]
    authentication_assurance: AuthenticationAssurance
    user_verified: bool
    recovery_derived: bool
    recovery_restricted: bool
    expires_at: datetime
    created_at: datetime
    last_seen_at: datetime | None
    authenticated_at: datetime

    def __post_init__(self) -> None:
        if self.session_epoch <= 0 or self.current_session_epoch <= 0:
            raise ValueError("session epochs must be positive")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if (self.password_credential_id is None) == (self.webauthn_credential_id is None):
            raise ValueError("exactly one initial authenticator is required")
        if not self.authentication_methods:
            raise ValueError("authentication_methods cannot be empty")
        if self.password_credential_id is not None and self.password_credential_status is None:
            raise ValueError("password credential status is required when a credential is bound")
        if self.webauthn_credential_id is not None and self.webauthn_credential_status is None:
            raise ValueError("webauthn credential status is required when a credential is bound")
        # The snapshot is the declared trust boundary; persisted evidence must be
        # internally consistent rather than trusted column-by-column.
        evidence = evidence_from_values(
            self.authentication_methods,
            user_verified=self.user_verified,
            recovery_derived=self.recovery_derived,
        )
        if classify_assurance(evidence) is not self.authentication_assurance:
            raise ValueError("session assurance does not match its proven methods")

    @property
    def initial_credential_id(self) -> UUID:
        if self.password_credential_id is not None:
            return self.password_credential_id
        assert self.webauthn_credential_id is not None
        return self.webauthn_credential_id


class NativeSessionReader(Protocol):
    async def read_native_session(self, *, session_id: UUID) -> NativeSessionSnapshot | None: ...


class NativeSessionToucher(Protocol):
    async def touch_native_session(
        self, *, session_id: UUID, min_interval_seconds: int
    ) -> bool: ...


class NativeSessionAuthenticator:
    """Provider-neutral authenticator for opaque RE Native session credentials.

    An optional ``session_toucher`` records bounded activity after a successful
    authentication; it is best-effort and never changes the authentication
    outcome. An optional ``idle_timeout`` additionally rejects a session whose
    recorded activity is too old; it is disabled unless a deployment enables it.
    """

    def __init__(
        self,
        *,
        session_reader: NativeSessionReader,
        session_toucher: NativeSessionToucher | None = None,
        idle_timeout: timedelta | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if idle_timeout is not None and idle_timeout <= timedelta(0):
            raise ValueError("idle_timeout must be positive")
        self._session_reader = session_reader
        self._session_toucher = session_toucher
        self._idle_timeout = idle_timeout
        self._clock = clock or (lambda: datetime.now(UTC))

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
        if (
            session.password_credential_status is NativeCredentialStatus.REVOKED
            or session.webauthn_credential_status is NativeCredentialStatus.REVOKED
        ):
            raise NativeCredentialRevoked("native session authenticator is revoked")
        if session.session_epoch != session.current_session_epoch:
            raise SessionRevoked("native session was globally invalidated")
        now = self._clock()
        if now >= session.expires_at:
            raise SessionExpired("native session is expired")
        if (
            self._idle_timeout is not None
            and session.last_seen_at is not None
            and now - session.last_seen_at > self._idle_timeout
        ):
            raise SessionExpired("native session is idle")
        await self._touch_activity(session.session_id)
        subject = native_authenticated_subject(
            identity_authority_id=session.identity_authority_id,
            native_identity_id=session.native_identity_id,
        )
        return replace(
            subject,
            metadata={
                **subject.metadata,
                "authenticated_at": session.authenticated_at.isoformat(),
                "credential_id": str(session.initial_credential_id),
                "authentication_methods": ",".join(session.authentication_methods),
                "authentication_assurance": session.authentication_assurance.value,
                "user_verified": "true" if session.user_verified else "false",
                "recovery_derived": "true" if session.recovery_derived else "false",
                "recovery_restricted": (
                    "true" if session.recovery_restricted else "false"
                ),
            },
        )

    async def _touch_activity(self, session_id: UUID) -> None:
        if self._session_toucher is None:
            return
        try:
            await self._session_toucher.touch_native_session(
                session_id=session_id,
                min_interval_seconds=_ACTIVITY_TOUCH_INTERVAL_SECONDS,
            )
        except Exception:
            return
