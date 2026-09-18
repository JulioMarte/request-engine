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
    new_sign_count: int
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


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast("Sequence[object]", value)
        return [_jsonable(item) for item in sequence]
    return value


def _user_verification(policy: WebAuthnPolicy) -> UserVerificationRequirement:
    if policy.user_verification_required:
        return UserVerificationRequirement.REQUIRED
    return UserVerificationRequirement.PREFERRED


def extract_registration_challenge(credential: Mapping[str, Any]) -> bytes:
    try:
        return RegistrationResponse.from_dict(credential).response.client_data.challenge
    except (KeyError, TypeError, ValueError) as exc:
        raise WebAuthnInputError(
            "webauthn_challenge_invalid", "Malformed registration credential"
        ) from exc


def extract_authentication_challenge(credential: Mapping[str, Any]) -> bytes:
    try:
        return AuthenticationResponse.from_dict(credential).response.client_data.challenge
    except (KeyError, TypeError, ValueError) as exc:
        raise WebAuthnInputError(
            "webauthn_challenge_invalid", "Malformed authentication credential"
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
        state = {
            "challenge": websafe_encode(expected_challenge),
            "user_verification": _user_verification(self._policy),
        }
        try:
            auth_data = self._server.register_complete(state, credential)
        except (KeyError, TypeError, ValueError) as exc:
            raise WebAuthnVerificationError(
                "webauthn_verification_failed", "Registration verification failed"
            ) from exc
        credential_data = auth_data.credential_data
        if credential_data is None:
            raise WebAuthnVerificationError(
                "webauthn_verification_failed", "Registration lacks credential data"
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
        current_sign_count: int,
    ) -> VerifiedAuthentication:
        state = {
            "challenge": websafe_encode(expected_challenge),
            "user_verification": _user_verification(self._policy),
        }
        try:
            stored = AttestedCredentialData.create(
                bytes.fromhex(aaguid),
                credential_id,
                CoseKey.parse(cast("Mapping[int, Any]", _decode_cbor(public_key))),
            )
            self._server.authenticate_complete(state, [stored], credential)
            auth_data = AuthenticationResponse.from_dict(credential).response.authenticator_data
        except (KeyError, TypeError, ValueError) as exc:
            raise WebAuthnVerificationError(
                "webauthn_verification_failed", "Authentication verification failed"
            ) from exc

        backup_eligible = bool(auth_data.is_backup_eligible())
        new_sign_count = self._advance_sign_count(
            current=current_sign_count,
            new=int(auth_data.counter),
            backup_eligible=backup_eligible,
        )
        return VerifiedAuthentication(
            credential_id=credential_id,
            new_sign_count=new_sign_count,
            user_verified=bool(auth_data.is_user_verified()),
            backup_eligible=backup_eligible,
            backup_state=bool(auth_data.is_backed_up()),
        )

    @staticmethod
    def _advance_sign_count(*, current: int, new: int, backup_eligible: bool) -> int:
        """Return the sign count to persist, rejecting a real regression.

        WebAuthn sign counters are optional and are not global for multi-device
        (backed-up) credentials. A regression is only meaningful for a
        single-device credential whose counter is non-zero.
        """

        if backup_eligible or new == 0 or current == 0:
            return new
        if new <= current:
            raise WebAuthnVerificationError(
                "webauthn_sign_count_regression",
                "WebAuthn sign count regressed for a single-device credential",
            )
        return new
