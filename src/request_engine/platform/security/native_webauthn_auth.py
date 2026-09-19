"""Internal native WebAuthn ceremony orchestration (ADR 0014 §5.5).

This is the application-facing operation layer P4 will consume. It performs the
full ceremony:

    begin  -> issue a bounded, single-purpose challenge (digest stored only)
    verify -> cryptographic verification in Python, outside authoritative locks
    finalize -> one request_auth transaction consumes the challenge and writes
                the credential, the session or the step-up fact

Assurance is derived only from the verified ceremony result; the HTTP layer never
supplies it. A failed verification cannot consume the challenge, and a concurrent
replay yields exactly one winner.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from request_engine.platform.security.assurance import (
    AuthenticationAssurance,
    AuthenticationEvidence,
    classify_assurance,
)
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.webauthn import (
    WebAuthnError,
    WebAuthnPolicy,
    WebAuthnService,
    challenge_digest,
    extract_authentication_challenge,
    extract_authentication_credential_id,
    extract_registration_challenge,
    generate_challenge,
)

_DEFAULT_SESSION_TTL = timedelta(hours=12)
_USER_HANDLE_PREFIX = b"request-engine:native:"


class WebAuthnCeremonyError(WebAuthnError):
    """The ceremony could not be finalized (expired, replayed or rejected)."""


@dataclass(frozen=True, slots=True)
class WebAuthnChallengeScope:
    native_identity_id: UUID | None
    session_id: UUID | None
    setup_session_id: UUID | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class WebAuthnCredentialRecord:
    id: UUID
    native_identity_id: UUID
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str
    backup_eligible: bool
    backup_state: bool
    user_verified: bool
    status: str


@dataclass(frozen=True, slots=True)
class WebAuthnCeremonyStarted:
    challenge: bytes
    public_key: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NativeWebAuthnSessionIssued:
    native_identity_id: UUID
    credential_row_id: UUID
    session_id: UUID
    raw_token: str = field(repr=False)
    expires_at: datetime
    assurance: AuthenticationAssurance


class WebAuthnCeremonyStore(Protocol):
    """Least-privilege persistence port implemented by the PostgreSQL adapter."""

    async def create_challenge(
        self,
        *,
        challenge_id: UUID,
        purpose: str,
        challenge_digest: bytes,
        expires_at: datetime,
        native_identity_id: UUID | None = None,
        session_id: UUID | None = None,
        setup_session_id: UUID | None = None,
    ) -> bool: ...

    async def read_challenge(
        self, *, challenge_digest: bytes, purpose: str
    ) -> WebAuthnChallengeScope | None: ...

    async def read_credential(self, *, credential_id: bytes) -> WebAuthnCredentialRecord | None: ...

    async def read_credentials(
        self, *, native_identity_id: UUID
    ) -> tuple[WebAuthnCredentialRecord, ...]: ...

    async def finalize_registration(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        aaguid: str,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
    ) -> bool: ...

    async def finalize_authentication(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        native_identity_id: UUID,
        sign_count: int,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
        session_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        expires_at: datetime,
    ) -> bool: ...

    async def finalize_step_up(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        session_id: UUID,
        native_identity_id: UUID,
        sign_count: int,
        backup_eligible: bool,
        user_verified: bool,
    ) -> bool: ...

    async def finalize_setup_registration(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        aaguid: str,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
        setup_session_id: UUID,
    ) -> bool: ...


class NativeWebAuthnAuthService:
    """Complete internal passkey registration/authentication/step-up ceremonies."""

    def __init__(
        self,
        *,
        policy: WebAuthnPolicy,
        store: WebAuthnCeremonyStore,
        webauthn: WebAuthnService | None = None,
        clock: Callable[[], datetime] | None = None,
        session_ttl: timedelta = _DEFAULT_SESSION_TTL,
    ) -> None:
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        self._policy = policy
        self._store = store
        self._webauthn = webauthn or WebAuthnService(policy)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._session_ttl = session_ttl

    async def begin_registration(self, *, native_identity_id: UUID) -> WebAuthnCeremonyStarted:
        existing = await self._store.read_credentials(native_identity_id=native_identity_id)
        options = self._webauthn.begin_registration(
            user_handle=_user_handle(native_identity_id),
            user_name=f"native-{native_identity_id}",
            exclude_credential_ids=[
                record.credential_id for record in existing if record.status == "active"
            ],
        )
        await self._persist_challenge(
            purpose="registration",
            challenge=options.challenge,
            native_identity_id=native_identity_id,
        )
        return WebAuthnCeremonyStarted(challenge=options.challenge, public_key=options.public_key)

    async def complete_registration(self, *, credential: Mapping[str, Any]) -> UUID:
        challenge = extract_registration_challenge(credential)
        digest = challenge_digest(challenge)
        scope = await self._store.read_challenge(challenge_digest=digest, purpose="registration")
        if scope is None or scope.native_identity_id is None:
            raise WebAuthnCeremonyError("webauthn_challenge_unknown")

        verified = self._webauthn.verify_registration(
            credential=credential, expected_challenge=challenge
        )
        credential_row_id = uuid4()
        finalized = await self._store.finalize_registration(
            challenge_digest=digest,
            credential_row_id=credential_row_id,
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            sign_count=verified.sign_count,
            aaguid=verified.aaguid,
            backup_eligible=verified.backup_eligible,
            backup_state=verified.backup_state,
            user_verified=verified.user_verified,
        )
        if not finalized:
            raise WebAuthnCeremonyError("webauthn_registration_rejected")
        return credential_row_id

    async def begin_authentication(self, *, native_identity_id: UUID) -> WebAuthnCeremonyStarted:
        existing = await self._store.read_credentials(native_identity_id=native_identity_id)
        options = self._webauthn.begin_authentication(
            allow_credential_ids=[
                record.credential_id for record in existing if record.status == "active"
            ],
        )
        await self._persist_challenge(
            purpose="authentication",
            challenge=options.challenge,
            native_identity_id=native_identity_id,
        )
        return WebAuthnCeremonyStarted(challenge=options.challenge, public_key=options.public_key)

    async def begin_authentication_decoy(
        self, *, allow_credential_ids: Sequence[bytes]
    ) -> WebAuthnCeremonyStarted:
        """Return non-persisted authentication options for an unknown identity.

        The challenge is never stored, so it can never be completed. It exists
        only so that an authentication-options response for an unknown or
        credential-less login handle is structurally indistinguishable from a
        real ceremony for a credential this authenticator does not hold. Without
        it, an empty allow-list would be a reliable account-enumeration oracle.
        """

        options = self._webauthn.begin_authentication(
            allow_credential_ids=list(allow_credential_ids)
        )
        return WebAuthnCeremonyStarted(challenge=options.challenge, public_key=options.public_key)

    async def complete_authentication(
        self, *, native_identity_id: UUID, credential: Mapping[str, Any]
    ) -> NativeWebAuthnSessionIssued:
        challenge = extract_authentication_challenge(credential)
        digest = challenge_digest(challenge)
        scope = await self._store.read_challenge(challenge_digest=digest, purpose="authentication")
        if scope is None or scope.native_identity_id != native_identity_id:
            raise WebAuthnCeremonyError("webauthn_challenge_unknown")

        record = await self._resolve_credential(
            credential=credential, native_identity_id=native_identity_id
        )
        verified = self._webauthn.verify_authentication(
            credential=credential,
            expected_challenge=challenge,
            credential_id=record.credential_id,
            public_key=record.public_key,
            aaguid=record.aaguid,
        )
        token = issue_opaque_token()
        expires_at = self._now() + self._session_ttl
        finalized = await self._store.finalize_authentication(
            challenge_digest=digest,
            credential_row_id=record.id,
            native_identity_id=native_identity_id,
            sign_count=verified.sign_count,
            backup_eligible=verified.backup_eligible,
            backup_state=verified.backup_state,
            user_verified=verified.user_verified,
            session_id=token.token_id,
            token_digest=token.digest,
            token_fingerprint=token.fingerprint,
            expires_at=expires_at,
        )
        if not finalized:
            raise WebAuthnCeremonyError("webauthn_authentication_rejected")
        return NativeWebAuthnSessionIssued(
            native_identity_id=native_identity_id,
            credential_row_id=record.id,
            session_id=token.token_id,
            raw_token=token.raw_token,
            expires_at=expires_at,
            assurance=classify_assurance(
                AuthenticationEvidence.webauthn(user_verified=verified.user_verified)
            ),
        )

    async def begin_step_up(self, *, session_id: UUID) -> WebAuthnCeremonyStarted:
        challenge = generate_challenge()
        options = self._webauthn.begin_authentication(challenge=challenge)
        await self._persist_challenge(purpose="step_up", challenge=challenge, session_id=session_id)
        return WebAuthnCeremonyStarted(challenge=challenge, public_key=options.public_key)

    async def complete_step_up(
        self,
        *,
        session_id: UUID,
        native_identity_id: UUID,
        credential: Mapping[str, Any],
    ) -> None:
        challenge = extract_authentication_challenge(credential)
        digest = challenge_digest(challenge)
        scope = await self._store.read_challenge(challenge_digest=digest, purpose="step_up")
        if scope is None or scope.session_id != session_id:
            raise WebAuthnCeremonyError("webauthn_challenge_unknown")

        record = await self._resolve_credential(
            credential=credential, native_identity_id=native_identity_id
        )
        verified = self._webauthn.verify_authentication(
            credential=credential,
            expected_challenge=challenge,
            credential_id=record.credential_id,
            public_key=record.public_key,
            aaguid=record.aaguid,
        )
        finalized = await self._store.finalize_step_up(
            challenge_digest=digest,
            credential_row_id=record.id,
            session_id=session_id,
            native_identity_id=native_identity_id,
            sign_count=verified.sign_count,
            backup_eligible=verified.backup_eligible,
            user_verified=verified.user_verified,
        )
        if not finalized:
            raise WebAuthnCeremonyError("webauthn_step_up_rejected")

    async def _persist_challenge(
        self,
        *,
        purpose: str,
        challenge: bytes,
        native_identity_id: UUID | None = None,
        session_id: UUID | None = None,
        setup_session_id: UUID | None = None,
    ) -> None:
        created = await self._store.create_challenge(
            challenge_id=uuid4(),
            purpose=purpose,
            challenge_digest=challenge_digest(challenge),
            expires_at=self._now() + timedelta(seconds=self._policy.challenge_ttl_seconds),
            native_identity_id=native_identity_id,
            session_id=session_id,
            setup_session_id=setup_session_id,
        )
        if not created:
            raise WebAuthnCeremonyError("webauthn_challenge_not_created")

    async def begin_setup_registration(self, *, setup_session_id: UUID) -> WebAuthnCeremonyStarted:
        challenge = generate_challenge()
        options = self._webauthn.begin_registration(
            user_handle=_setup_user_handle(setup_session_id),
            user_name=f"setup-{setup_session_id}",
            challenge=challenge,
        )
        await self._persist_challenge(
            purpose="registration",
            challenge=challenge,
            setup_session_id=setup_session_id,
        )
        return WebAuthnCeremonyStarted(challenge=challenge, public_key=options.public_key)

    async def complete_setup_registration(
        self, *, setup_session_id: UUID, credential: Mapping[str, Any]
    ) -> bool:
        challenge = extract_registration_challenge(credential)
        digest = challenge_digest(challenge)
        scope = await self._store.read_challenge(challenge_digest=digest, purpose="registration")
        if scope is None or scope.setup_session_id != setup_session_id:
            # The presented SetupSession must be the ceremony that owns the
            # challenge; another valid bearer is never sufficient.
            raise WebAuthnCeremonyError("webauthn_challenge_unknown")
        verified = self._webauthn.verify_registration(
            credential=credential, expected_challenge=challenge
        )
        return await self._store.finalize_setup_registration(
            challenge_digest=digest,
            credential_row_id=uuid4(),
            credential_id=verified.credential_id,
            public_key=verified.public_key,
            sign_count=verified.sign_count,
            aaguid=verified.aaguid,
            backup_eligible=verified.backup_eligible,
            backup_state=verified.backup_state,
            user_verified=verified.user_verified,
            setup_session_id=setup_session_id,
        )

    async def _resolve_credential(
        self, *, credential: Mapping[str, Any], native_identity_id: UUID
    ) -> WebAuthnCredentialRecord:
        credential_id = extract_authentication_credential_id(credential)
        record = await self._store.read_credential(credential_id=credential_id)
        if (
            record is None
            or record.native_identity_id != native_identity_id
            or record.status != "active"
        ):
            raise WebAuthnCeremonyError("webauthn_credential_unknown")
        return record

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise RuntimeError("WebAuthn clock must return timezone-aware datetimes")
        return value


def _user_handle(native_identity_id: UUID) -> bytes:
    return hashlib.sha256(_USER_HANDLE_PREFIX + native_identity_id.bytes).digest()


def _setup_user_handle(setup_session_id: UUID) -> bytes:
    return hashlib.sha256(b"request-engine:setup:" + setup_session_id.bytes).digest()


__all__ = [
    "NativeWebAuthnAuthService",
    "NativeWebAuthnSessionIssued",
    "WebAuthnCeremonyError",
    "WebAuthnCeremonyStarted",
    "WebAuthnCeremonyStore",
    "WebAuthnChallengeScope",
    "WebAuthnCredentialRecord",
]
