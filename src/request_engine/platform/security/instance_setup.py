"""Instance setup / claim application service (ADR 0014 §6-§9).

This is the installation ceremony surface. It is deliberately separate from
ordinary Principal/capability authorization: while the Instance is UNCLAIMED the
only authority is a SetupSession bearer plus deployment configuration, and no
Principal exists yet. It never accepts tenant/actor headers or caller-selected
capability/principal claims.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from request_engine.platform.security.native_auth import (
    SessionTokenInvalid,
    digest_opaque_secret,
    hash_password,
    issue_opaque_token,
    parse_opaque_token,
)
from request_engine.platform.security.native_webauthn_auth import (
    NativeWebAuthnAuthService,
    WebAuthnCeremonyStarted,
)
from request_engine.platform.security.recovery_codes import NativeRecoveryCodeService

_DEFAULT_SETUP_TTL_SECONDS = 1800
_DEFAULT_SETUP_MODE = "interactive"


class InstanceSetupError(RuntimeError):
    """Base class for setup-ceremony failures."""


class SetupSessionUnusable(InstanceSetupError):
    pass


class SetupStepInvalid(InstanceSetupError):
    pass


@dataclass(frozen=True, slots=True)
class InstanceSnapshot:
    instance_id: UUID
    state: str
    claimed_at: datetime | None
    initial_owner_principal_id: UUID | None
    built_in_native_authority_id: UUID
    built_in_workload_authority_id: UUID


@dataclass(frozen=True, slots=True)
class SetupSessionIssued:
    setup_session_id: UUID
    raw_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SetupSessionSnapshot:
    setup_session_id: UUID
    status: str
    is_usable: bool
    expires_at: datetime
    instance_state: str


@dataclass(frozen=True, slots=True)
class ClaimReadiness:
    setup_status: str
    setup_usable: bool
    instance_state: str
    has_identity: bool
    verified_webauthn_count: int
    has_recovery_codes: bool
    policy_key: str


@dataclass(frozen=True, slots=True)
class InstanceClaimResult:
    instance_id: UUID
    owner_principal_id: UUID
    native_identity_id: UUID
    setup_session_id: UUID
    policy_key: str


class InstanceSetupStore(Protocol):
    async def read_instance(self) -> InstanceSnapshot | None: ...

    async def create_setup_session(
        self,
        *,
        setup_session_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        mode: str,
        ttl_seconds: int,
    ) -> UUID | None: ...

    async def read_setup_session(self, *, token_digest: bytes) -> SetupSessionSnapshot | None: ...

    async def set_pending_identity(
        self,
        *,
        native_identity_id: UUID,
        setup_session_id: UUID,
        login_handle: str,
        verifier: str,
    ) -> bool: ...

    async def read_claim_readiness(self, *, setup_session_id: UUID) -> ClaimReadiness | None: ...

    async def finalize_claim(
        self,
        *,
        setup_session_id: UUID,
        idempotency_key_digest: str,
        intent_digest: str,
        claim_provenance: str,
        actor_authentication_method: str,
        correlation_id: UUID | None,
    ) -> InstanceClaimResult | None: ...

    async def read_installation_claim(
        self, *, idempotency_key_digest: str, intent_digest: str
    ) -> InstanceClaimResult | None: ...


class InstanceSetupService:
    """Drive the first-run setup ceremony and the atomic Instance claim."""

    def __init__(
        self,
        *,
        store: InstanceSetupStore,
        webauthn: NativeWebAuthnAuthService,
        recovery_codes: NativeRecoveryCodeService,
        setup_ttl_seconds: int = _DEFAULT_SETUP_TTL_SECONDS,
        setup_mode: str = _DEFAULT_SETUP_MODE,
    ) -> None:
        if setup_ttl_seconds < 60 or setup_ttl_seconds > 3600:
            raise ValueError("setup session TTL must be between 60 and 3600 seconds")
        if setup_mode not in {"interactive", "protected", "automated"}:
            raise ValueError("unsupported setup mode")
        self._store = store
        self._webauthn = webauthn
        self._recovery_codes = recovery_codes
        self._setup_ttl_seconds = setup_ttl_seconds
        self._setup_mode = setup_mode

    async def read_instance(self) -> InstanceSnapshot | None:
        return await self._store.read_instance()

    async def create_setup_session(self) -> SetupSessionIssued:
        token = issue_opaque_token()
        created = await self._store.create_setup_session(
            setup_session_id=token.token_id,
            token_digest=token.digest,
            token_fingerprint=token.fingerprint,
            mode=self._setup_mode,
            ttl_seconds=self._setup_ttl_seconds,
        )
        if created is None:
            raise SetupSessionUnusable("setup is not available")
        session = await self._store.read_setup_session(token_digest=token.digest)
        if session is None:
            raise SetupSessionUnusable("setup session was not found")
        return SetupSessionIssued(
            setup_session_id=token.token_id,
            raw_token=token.raw_token,
            expires_at=session.expires_at,
        )

    async def resolve_setup_session(self, *, raw_token: str) -> SetupSessionSnapshot:
        """Resolve a SetupSession bearer for an enrollment/finalize operation.

        A consumed session is returned as-is so the caller can distinguish an
        exact finalize replay (idempotency receipt lookup) from a new claim; it
        never reactivates setup authority.
        """
        try:
            parsed = parse_opaque_token(raw_token)
        except SessionTokenInvalid as error:
            raise SetupSessionUnusable("setup session token is malformed") from error
        session = await self._store.read_setup_session(
            token_digest=digest_opaque_secret(parsed.secret)
        )
        if session is None or session.setup_session_id != parsed.token_id:
            raise SetupSessionUnusable("setup session was not found")
        return session

    async def set_pending_identity(
        self, *, setup_session_id: UUID, login_handle: str, password: str
    ) -> None:
        verifier = hash_password(password)
        created = await self._store.set_pending_identity(
            native_identity_id=uuid4(),
            setup_session_id=setup_session_id,
            login_handle=login_handle,
            verifier=verifier,
        )
        if not created:
            raise SetupStepInvalid("setup identity could not be recorded")

    async def begin_webauthn_registration(
        self, *, setup_session_id: UUID
    ) -> WebAuthnCeremonyStarted:
        return await self._webauthn.begin_setup_registration(setup_session_id=setup_session_id)

    async def complete_webauthn_registration(
        self, *, setup_session_id: UUID, credential: Mapping[str, Any]
    ) -> None:
        registered = await self._webauthn.complete_setup_registration(
            setup_session_id=setup_session_id, credential=credential
        )
        if not registered:
            raise SetupStepInvalid("setup WebAuthn registration was rejected")

    async def issue_recovery_codes(self, *, setup_session_id: UUID) -> tuple[str, ...]:
        return await self._recovery_codes.issue_for_setup_session(setup_session_id=setup_session_id)

    async def read_readiness(self, *, setup_session_id: UUID) -> ClaimReadiness:
        readiness = await self._store.read_claim_readiness(setup_session_id=setup_session_id)
        if readiness is None:
            raise SetupSessionUnusable("setup session was not found")
        return readiness

    async def finalize(
        self,
        *,
        setup_session_id: UUID,
        idempotency_key: str,
        claim_provenance: str,
        actor_authentication_method: str = "setup_session",
        correlation_id: UUID | None = None,
    ) -> InstanceClaimResult:
        key_digest = hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()
        intent_digest = claim_intent_digest(
            setup_session_id=setup_session_id, claim_provenance=claim_provenance
        )
        result = await self._store.finalize_claim(
            setup_session_id=setup_session_id,
            idempotency_key_digest=key_digest,
            intent_digest=intent_digest,
            claim_provenance=claim_provenance,
            actor_authentication_method=actor_authentication_method,
            correlation_id=correlation_id,
        )
        if result is None:
            raise SetupStepInvalid("instance claim was rejected")
        return result

    async def lookup_claim(
        self,
        *,
        setup_session_id: UUID,
        idempotency_key: str,
        claim_provenance: str,
    ) -> InstanceClaimResult | None:
        """Return the receipt only for the exact original request.

        A consumed SetupSession plus the same idempotency key is not enough: the
        request fingerprint must also match, so reusing a key with different
        provenance (or another session) is a conflict, never a foreign receipt.
        """
        key_digest = hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()
        intent_digest = claim_intent_digest(
            setup_session_id=setup_session_id, claim_provenance=claim_provenance
        )
        return await self._store.read_installation_claim(
            idempotency_key_digest=key_digest, intent_digest=intent_digest
        )


def claim_intent_digest(*, setup_session_id: UUID, claim_provenance: str) -> str:
    """Fingerprint the exact finalize request, not just its idempotency key.

    The digest covers the operation, the SetupSession and the provenance so that
    a key reused with different request content is detected as a conflict rather
    than replayed as the earlier receipt.
    """
    payload = "\x1f".join(
        (
            "finalize-instance-claim-v1",
            str(setup_session_id),
            claim_provenance.strip(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
