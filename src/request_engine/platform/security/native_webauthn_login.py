"""Post-claim native WebAuthn login orchestration (ADR 0014 §8).

The cryptographic ceremony is owned by :class:`NativeWebAuthnAuthService`; this
service enforces an optional intended login handle at completion, before the
authoritative session transaction. It never accepts caller-supplied assurance.

Every begin response uses one unbound discoverable challenge and an empty
allow-list. Neither credential cardinality nor credential-id length can reveal
whether a handle exists. Legacy non-discoverable credentials are retained but
must be replaced through the supported password/recovery registration journey.
"""

from __future__ import annotations

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

    async def begin_login(
        self, *, identity_authority_id: UUID, login_handle: str | None
    ) -> WebAuthnCeremonyStarted:
        if login_handle is None or not login_handle.strip():
            # Usernameless/discoverable: no handle to enumerate, so no decoy is
            # needed. The ceremony is the same authentication primitive; only the
            # allow-list is empty and the identity is resolved at completion.
            return await self._webauthn.begin_authentication_discoverable()
        # Never expose stored credential ids/cardinality/length for a supplied
        # handle. All login options use the same unbound discoverable ceremony.
        # The intended handle is enforced at completion, before the transaction.
        return await self._webauthn.begin_authentication_discoverable()

    async def complete_login(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str | None,
        credential: Mapping[str, Any],
    ) -> NativeWebAuthnSessionIssued:
        if login_handle is None or not login_handle.strip():
            return await self._webauthn.complete_discoverable_authentication(credential=credential)
        identity_id = await self._resolve(identity_authority_id, login_handle)
        if identity_id is None:
            # Opaque: identical to a known identity whose assertion does not
            # verify. Never reveals that the handle is unknown.
            raise WebAuthnCeremonyError("webauthn_credential_unknown")
        return await self._webauthn.complete_discoverable_authentication(
            expected_native_identity_id=identity_id, credential=credential
        )

    async def _resolve(self, identity_authority_id: UUID, login_handle: str) -> UUID | None:
        return await self._identities.read_active_webauthn_identity(
            identity_authority_id=identity_authority_id,
            login_handle=normalize_login_handle(login_handle),
        )


__all__ = ["NativeWebAuthnIdentityReader", "NativeWebAuthnLoginService"]
