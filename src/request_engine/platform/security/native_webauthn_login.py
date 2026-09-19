"""Post-claim native WebAuthn login orchestration (ADR 0014 §8).

The cryptographic ceremony is owned by :class:`NativeWebAuthnAuthService`; this
service only resolves a login handle to an active native identity and, when no
such identity exists, returns an indistinguishable decoy. It never issues a
second kind of challenge and never accepts caller-supplied assurance.

Account-enumeration resistance: an unknown handle, a known handle without an
active WebAuthn credential and a known handle with credentials all return a
challenge plus a single credential allow-list entry. The decoy credential id is
``HMAC(secret, normalized_handle)``; because the secret is deployment-owned, an
attacker cannot precompute it to tell a decoy from a real credential id. A real
ceremony persists its challenge bound to the identity, so a decoy challenge can
never be completed.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from request_engine.platform.security.native_auth import normalize_login_handle
from request_engine.platform.security.native_webauthn_auth import (
    NativeWebAuthnAuthService,
    NativeWebAuthnSessionIssued,
    WebAuthnCeremonyError,
    WebAuthnCeremonyStarted,
)


class NativeWebAuthnIdentityReader(Protocol):
    """Resolve an active native identity that owns an active WebAuthn credential."""

    async def read_active_webauthn_identity(
        self, *, identity_authority_id: UUID, login_handle: str
    ) -> UUID | None: ...


class NativeWebAuthnLoginService:
    """Expose the shared authentication ceremony for a login handle."""

    def __init__(
        self,
        *,
        webauthn: NativeWebAuthnAuthService,
        identities: NativeWebAuthnIdentityReader,
        decoy_key: bytes,
    ) -> None:
        if not decoy_key:
            raise ValueError("decoy_key is required")
        self._webauthn = webauthn
        self._identities = identities
        self._decoy_key = decoy_key

    async def begin_login(
        self, *, identity_authority_id: UUID, login_handle: str
    ) -> WebAuthnCeremonyStarted:
        identity_id = await self._resolve(identity_authority_id, login_handle)
        if identity_id is None:
            return await self._webauthn.begin_authentication_decoy(
                allow_credential_ids=[self._decoy_credential_id(login_handle)]
            )
        return await self._webauthn.begin_authentication(native_identity_id=identity_id)

    async def complete_login(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
        credential: Mapping[str, Any],
    ) -> NativeWebAuthnSessionIssued:
        identity_id = await self._resolve(identity_authority_id, login_handle)
        if identity_id is None:
            # Opaque: identical to a known identity whose assertion does not
            # verify. Never reveals that the handle is unknown.
            raise WebAuthnCeremonyError("webauthn_credential_unknown")
        return await self._webauthn.complete_authentication(
            native_identity_id=identity_id, credential=credential
        )

    async def _resolve(self, identity_authority_id: UUID, login_handle: str) -> UUID | None:
        return await self._identities.read_active_webauthn_identity(
            identity_authority_id=identity_authority_id,
            login_handle=normalize_login_handle(login_handle),
        )

    def _decoy_credential_id(self, login_handle: str) -> bytes:
        normalized = normalize_login_handle(login_handle)
        return hmac.new(self._decoy_key, normalized.encode("utf-8"), hashlib.sha256).digest()


__all__ = ["NativeWebAuthnIdentityReader", "NativeWebAuthnLoginService"]
