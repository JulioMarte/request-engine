"""Real-crypto software WebAuthn authenticator for tests (plan §24).

It builds genuine attestation objects and assertions with an EC P-256 key using
the same maintained library the server verifies with. Tests therefore exercise
real CBOR/COSE/signature verification; they never mock ``verified=true``.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import websafe_encode
from fido2.webauthn import (
    AttestationObject,
    AttestedCredentialData,
    AuthenticatorData,
    CollectedClientData,
)

DEFAULT_AAGUID = b"\x00" * 16


@dataclass
class SoftwareAuthenticator:
    """A deterministic-key, in-process FIDO2 authenticator."""

    rp_id: str
    origin: str
    aaguid: bytes = DEFAULT_AAGUID
    backup_eligible: bool = False
    backup_state: bool = False
    _private_key: ec.EllipticCurvePrivateKey = field(init=False, repr=False)
    credential_id: bytes = field(init=False)
    user_handle: bytes = field(init=False)
    sign_count: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(32)
        self.user_handle = secrets.token_bytes(32)
        self.sign_count = 0
        self._rp_id_hash = hashlib.sha256(self.rp_id.encode("utf-8")).digest()

    def _flags(self, *, user_verified: bool, attested: bool) -> AuthenticatorData.FLAG:
        flags = AuthenticatorData.FLAG.UP
        if user_verified:
            flags |= AuthenticatorData.FLAG.UV
        if attested:
            flags |= AuthenticatorData.FLAG.AT
        if self.backup_eligible:
            flags |= AuthenticatorData.FLAG.BE
        if self.backup_state:
            flags |= AuthenticatorData.FLAG.BS
        return flags

    def registration_credential(
        self, *, challenge: bytes, user_verified: bool = True
    ) -> dict[str, Any]:
        cose_key = ES256.from_cryptography_key(self._private_key.public_key())
        credential_data = AttestedCredentialData.create(self.aaguid, self.credential_id, cose_key)
        auth_data = AuthenticatorData.create(  # pyright: ignore[reportUnknownMemberType]
            self._rp_id_hash,
            self._flags(user_verified=user_verified, attested=True),
            self.sign_count,
            credential_data=bytes(credential_data),
        )
        attestation_object = AttestationObject.create("none", auth_data, {})
        client_data = CollectedClientData.create(  # pyright: ignore[reportUnknownMemberType]
            "webauthn.create", challenge, self.origin
        )
        return {
            "id": websafe_encode(self.credential_id),
            "rawId": websafe_encode(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(bytes(client_data)),
                "attestationObject": websafe_encode(bytes(attestation_object)),
            },
        }

    def authentication_credential(
        self,
        *,
        challenge: bytes,
        user_verified: bool = True,
        increment: int = 1,
    ) -> dict[str, Any]:
        self.sign_count += increment
        auth_data = AuthenticatorData.create(  # pyright: ignore[reportUnknownMemberType]
            self._rp_id_hash,
            self._flags(user_verified=user_verified, attested=False),
            self.sign_count,
        )
        client_data = CollectedClientData.create(  # pyright: ignore[reportUnknownMemberType]
            "webauthn.get", challenge, self.origin
        )
        signature = self._private_key.sign(
            bytes(auth_data) + hashlib.sha256(bytes(client_data)).digest(),
            ec.ECDSA(hashes.SHA256()),
        )
        return {
            "id": websafe_encode(self.credential_id),
            "rawId": websafe_encode(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(bytes(client_data)),
                "authenticatorData": websafe_encode(bytes(auth_data)),
                "signature": websafe_encode(signature),
                "userHandle": websafe_encode(self.user_handle),
            },
        }
