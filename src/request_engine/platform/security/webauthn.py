"""Request Engine-owned WebAuthn ceremony mechanics (ADR 0014 §5.5).

This module wraps a maintained WebAuthn library (Yubico ``fido2``) so that CBOR,
COSE, signature, origin, RP-ID and user-verification handling stay out of Request
Engine's business code. It exposes Request Engine value types and a sign-count
policy that avoids false lockouts for authenticators with zero or non-global
counters while still rejecting a genuine regression on a single-device credential.

The service is stateless: challenges are persisted by the caller (digest only),
and verification is reconstructed from the caller-supplied expected challenge.
"""

from __future__ import annotations

import hashlib
import secrets
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from fido2 import cbor
from fido2.cose import CoseKey
from fido2.server import Fido2Server
from fido2.utils import websafe_encode
from fido2.webauthn import (
    AttestationConveyancePreference,
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorData,
    CredentialCreationOptions,
    CredentialRequestOptions,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialType,
    PublicKeyCredentialUserEntity,
    RegistrationResponse,
    UserVerificationRequirement,
)

CHALLENGE_BYTES = 32


class _CeremonyServer(Protocol):
    """The typed subset of the FIDO2 server surface Request Engine relies on.

    The library's ``extensions`` parameter is untyped, so binding a Protocol keeps
    strict type checking meaningful for every call Request Engine actually makes.
    """

    def register_begin(
        self,
        user: PublicKeyCredentialUserEntity,
        credentials: Sequence[PublicKeyCredentialDescriptor] | None = None,
        *,
        user_verification: UserVerificationRequirement | None = None,
        challenge: bytes | None = None,
    ) -> tuple[CredentialCreationOptions, object]: ...

    def register_complete(
        self,
        state: Mapping[str, object],
        response: Mapping[str, Any] | RegistrationResponse,
    ) -> AuthenticatorData: ...

    def authenticate_begin(
        self,
        credentials: Sequence[PublicKeyCredentialDescriptor] | None = None,
        *,
        user_verification: UserVerificationRequirement | None = None,
        challenge: bytes | None = None,
    ) -> tuple[CredentialRequestOptions, object]: ...

    def authenticate_complete(
        self,
        state: Mapping[str, object],
        credentials: Sequence[AttestedCredentialData],
        response: Mapping[str, Any] | AuthenticationResponse,
    ) -> AttestedCredentialData: ...


class WebAuthnError(Exception):
    """Base WebAuthn failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class WebAuthnVerificationError(WebAuthnError):
    pass


class WebAuthnInputError(WebAuthnError):
    pass


@dataclass(frozen=True, slots=True)
class WebAuthnPolicy:
    rp_id: str
    rp_name: str
    allowed_origins: frozenset[str]
    user_verification_required: bool = True
    challenge_ttl_seconds: int = 300
    attestation: str = "none"

    def __post_init__(self) -> None:
        if not self.rp_id.strip():
            raise ValueError("WebAuthn rp_id is required")
        if not self.allowed_origins:
            raise ValueError("WebAuthn allowed_origins cannot be empty")
        if self.challenge_ttl_seconds <= 0:
            raise ValueError("WebAuthn challenge_ttl_seconds must be positive")
        if self.attestation not in {"none", "indirect", "direct", "enterprise"}:
            raise ValueError("Unsupported WebAuthn attestation preference")
        if self.attestation != "none":
            # No attestation verifier is wired yet; accepting a non-``none``
            # preference would silently trust an unverified attestation.
            raise ValueError("WebAuthn attestation must be 'none' until a verifier is configured")


@dataclass(frozen=True, slots=True)
class RegistrationOptions:
    challenge: bytes
    public_key: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class VerifiedRegistration:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str
    backup_eligible: bool
    backup_state: bool
    user_verified: bool


@dataclass(frozen=True, slots=True)
class AuthenticationOptions:
    challenge: bytes
    public_key: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class VerifiedAuthentication:
    credential_id: bytes
    sign_count: int
    user_verified: bool
    backup_eligible: bool
    backup_state: bool


def generate_challenge() -> bytes:
    return secrets.token_bytes(CHALLENGE_BYTES)


def challenge_digest(challenge: bytes) -> bytes:
    return hashlib.sha256(challenge).digest()


# fido2's bundled CBOR decoder leaves its input parameter untyped.
_decode_cbor: Callable[[bytes], object] = cast(
    "Callable[[bytes], object]",
    cbor.decode,  # pyright: ignore[reportUnknownMemberType]
)

# Failures raised by fido2/COSE/CBOR for client input or stored credential material.
# ``NotImplementedError`` covers an unsupported-but-parseable COSE algorithm and
# ``IndexError``/``OverflowError``/``RecursionError`` cover malformed/over-nested
# CBOR that the bundled decoder does not bound.
_VERIFICATION_ERRORS = (
    KeyError,
    TypeError,
    ValueError,
    AttributeError,
    UnicodeError,
    NotImplementedError,
    IndexError,
    OverflowError,
    RecursionError,
    struct.error,
)


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast("Sequence[object]", value)
        return [_jsonable(item) for item in sequence]
    return value


def public_key_to_json(value: object) -> Any:
    """Recursively encode a WebAuthn public-key option tree for JSON transport.

    Raw ``bytes`` (challenge, credential ids) become websafe base64; mappings and
    sequences are preserved. The HTTP layer uses this for both setup and login so
    the wire shape stays identical across ceremonies.
    """

    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {str(key): public_key_to_json(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast("Sequence[object]", value)
        return [public_key_to_json(item) for item in sequence]
    if isinstance(value, (bytes, bytearray)):
        return websafe_encode(bytes(value))
    if isinstance(value, memoryview):
        return websafe_encode(value.tobytes())
    return value


def _user_verification(policy: WebAuthnPolicy) -> UserVerificationRequirement:
    if policy.user_verification_required:
        return UserVerificationRequirement.REQUIRED
    return UserVerificationRequirement.PREFERRED


# The fido2 ceremony state returned by ``register_begin``/``authenticate_begin``
# is an untyped, private data bag the library documents as "passed as is". Request
# Engine deliberately reconstructs exactly the two keys the library actually reads
# (verified against fido2 2.2.1) so raw challenges never reach durable storage.
# ``test_webauthn.py`` pins this contract against the installed library so a 2.x
# minor that changes the state shape fails loudly instead of silently weakening a
# check.
CEREMONY_STATE_KEYS = ("challenge", "user_verification")


def _ceremony_state(challenge: bytes, policy: WebAuthnPolicy) -> dict[str, object]:
    return {
        "challenge": websafe_encode(challenge),
        "user_verification": _user_verification(policy),
    }


def extract_registration_challenge(credential: Mapping[str, Any]) -> bytes:
    try:
        return RegistrationResponse.from_dict(credential).response.client_data.challenge
    except _VERIFICATION_ERRORS as exc:
        raise WebAuthnInputError(
            "webauthn_challenge_invalid", "Malformed registration credential"
        ) from exc


def extract_authentication_challenge(credential: Mapping[str, Any]) -> bytes:
    try:
        return AuthenticationResponse.from_dict(credential).response.client_data.challenge
    except _VERIFICATION_ERRORS as exc:
        raise WebAuthnInputError(
            "webauthn_challenge_invalid", "Malformed authentication credential"
        ) from exc


def extract_authentication_credential_id(credential: Mapping[str, Any]) -> bytes:
    try:
        return bytes(AuthenticationResponse.from_dict(credential).raw_id)
    except _VERIFICATION_ERRORS as exc:
        raise WebAuthnInputError(
            "webauthn_credential_invalid", "Malformed authentication credential"
        ) from exc


class WebAuthnService:
    """Provider-neutral WebAuthn registration/authentication verification."""

    def __init__(self, policy: WebAuthnPolicy) -> None:
        self._policy = policy
        self._server: _CeremonyServer = cast(
            _CeremonyServer,
            Fido2Server(
                PublicKeyCredentialRpEntity(name=policy.rp_name, id=policy.rp_id),
                attestation=AttestationConveyancePreference(policy.attestation),
                verify_origin=lambda origin: origin in policy.allowed_origins,
            ),
        )

    @property
    def policy(self) -> WebAuthnPolicy:
        return self._policy

    def begin_registration(
        self,
        *,
        user_handle: bytes,
        user_name: str,
        user_display_name: str | None = None,
        exclude_credential_ids: Sequence[bytes] = (),
        challenge: bytes | None = None,
    ) -> RegistrationOptions:
        if len(user_handle) < 16:
            raise WebAuthnInputError(
                "webauthn_input_invalid", "WebAuthn user handle must be >= 16 bytes"
            )
        raw_challenge = challenge or generate_challenge()
        user = PublicKeyCredentialUserEntity(
            name=user_name, id=user_handle, display_name=user_display_name
        )
        exclude = [
            PublicKeyCredentialDescriptor(type=PublicKeyCredentialType.PUBLIC_KEY, id=credential_id)
            for credential_id in exclude_credential_ids
        ]
        options, _state = self._server.register_begin(
            user,
            credentials=exclude or None,
            user_verification=_user_verification(self._policy),
            challenge=raw_challenge,
        )
        return RegistrationOptions(
            challenge=raw_challenge,
            public_key=cast(Mapping[str, Any], _jsonable(options.public_key)),
        )

    def verify_registration(
        self,
        *,
        credential: Mapping[str, Any],
        expected_challenge: bytes,
    ) -> VerifiedRegistration:
        state = _ceremony_state(expected_challenge, self._policy)
        try:
            auth_data = self._server.register_complete(state, credential)
        except _VERIFICATION_ERRORS as exc:
            raise WebAuthnVerificationError(
                "webauthn_verification_failed", "Registration verification failed"
            ) from exc
        credential_data = auth_data.credential_data
        if credential_data is None:
            raise WebAuthnVerificationError(
                "webauthn_verification_failed", "Registration lacks credential data"
            )
        if credential_data.public_key.ALGORITHM not in CoseKey.supported_algorithms():
            raise WebAuthnVerificationError(
                "webauthn_unsupported_algorithm",
                "Registration used an unsupported COSE algorithm",
            )
        return VerifiedRegistration(
            credential_id=bytes(credential_data.credential_id),
            public_key=cbor.encode(credential_data.public_key),
            sign_count=int(auth_data.counter),
            aaguid=bytes(credential_data.aaguid).hex(),
            backup_eligible=bool(auth_data.is_backup_eligible()),
            backup_state=bool(auth_data.is_backed_up()),
            user_verified=bool(auth_data.is_user_verified()),
        )

    def begin_authentication(
        self,
        *,
        allow_credential_ids: Sequence[bytes] = (),
        challenge: bytes | None = None,
    ) -> AuthenticationOptions:
        raw_challenge = challenge or generate_challenge()
        allow = [
            PublicKeyCredentialDescriptor(type=PublicKeyCredentialType.PUBLIC_KEY, id=credential_id)
            for credential_id in allow_credential_ids
        ]
        options, _state = self._server.authenticate_begin(
            credentials=allow or None,
            user_verification=_user_verification(self._policy),
            challenge=raw_challenge,
        )
        return AuthenticationOptions(
            challenge=raw_challenge,
            public_key=cast(Mapping[str, Any], _jsonable(options.public_key)),
        )

    def verify_authentication(
        self,
        *,
        credential: Mapping[str, Any],
        expected_challenge: bytes,
        credential_id: bytes,
        public_key: bytes,
        aaguid: str,
    ) -> VerifiedAuthentication:
        state = _ceremony_state(expected_challenge, self._policy)
        try:
            stored = AttestedCredentialData.create(
                bytes.fromhex(aaguid),
                credential_id,
                CoseKey.parse(cast("Mapping[int, Any]", _decode_cbor(public_key))),
            )
            self._server.authenticate_complete(state, [stored], credential)
            auth_data = AuthenticationResponse.from_dict(credential).response.authenticator_data
        except _VERIFICATION_ERRORS as exc:
            raise WebAuthnVerificationError(
                "webauthn_verification_failed", "Authentication verification failed"
            ) from exc

        return VerifiedAuthentication(
            credential_id=credential_id,
            sign_count=int(auth_data.counter),
            user_verified=bool(auth_data.is_user_verified()),
            backup_eligible=bool(auth_data.is_backup_eligible()),
            backup_state=bool(auth_data.is_backed_up()),
        )
