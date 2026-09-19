from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)

_NATIVE_AUTHORITY_KIND = "native"
_SCRYPT_VERSION = "1"
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_PREFIX = "scrypt$"
# OWASP-recommended Argon2id minimum (19 MiB, t=2, p=1).
_ARGON2_TIME_COST = 2
_ARGON2_MEMORY_COST = 19456
_ARGON2_PARALLELISM = 1
_ARGON2_HASH_LEN = 32
_ARGON2_SALT_LEN = 16
_ARGON2ID_PREFIX = "$argon2id$"
_MIN_PASSWORD_LENGTH = 12
_MAX_PASSWORD_BYTES = 1024
_SECRET_BYTES = 32

_ARGON2_HASHER = PasswordHasher(
    time_cost=_ARGON2_TIME_COST,
    memory_cost=_ARGON2_MEMORY_COST,
    parallelism=_ARGON2_PARALLELISM,
    hash_len=_ARGON2_HASH_LEN,
    salt_len=_ARGON2_SALT_LEN,
)


class NativeAuthenticationError(RuntimeError):
    """Base class for typed Native authentication failures."""


class CredentialInvalid(NativeAuthenticationError):
    pass


class SessionTokenInvalid(NativeAuthenticationError):
    pass


class PasswordPolicyViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OpaqueTokenMaterial:
    """One-time raw token plus persistence-safe verification material."""

    token_id: UUID
    raw_token: str = field(repr=False)
    digest: bytes
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ParsedOpaqueToken:
    token_id: UUID
    secret: str = field(repr=False)


def normalize_login_handle(value: str) -> str:
    """Canonicalize a Native login handle without guessing its semantic type."""

    normalized = value.strip().casefold()
    if not normalized or len(normalized) > 320:
        raise ValueError("login handle must contain between 1 and 320 characters")
    return normalized


def hash_password(password: str) -> str:
    """Hash a password with the current versioned verifier (Argon2id)."""

    password_bytes = _validate_password(password)
    return _ARGON2_HASHER.hash(password_bytes)


def hash_password_scrypt(password: str) -> str:
    """Create a legacy scrypt verifier.

    New verifiers always use Argon2id; this exists for transitional fixtures and
    for proving legacy verification/opportunistic rehash.
    """

    password_bytes = _validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password_bytes,
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return "$".join(
        (
            "scrypt",
            f"v={_SCRYPT_VERSION}",
            f"n={_SCRYPT_N}",
            f"r={_SCRYPT_R}",
            f"p={_SCRYPT_P}",
            _b64(salt),
            _b64(digest),
        )
    )


def verify_password(password: str, verifier: str) -> bool:
    """Verify a password against any supported versioned verifier.

    Legacy scrypt verifiers remain verifiable; unknown schemes fail closed.
    """

    if verifier.startswith(_SCRYPT_PREFIX):
        return _verify_scrypt(password, verifier)
    if verifier.startswith(_ARGON2ID_PREFIX):
        return _verify_argon2id(password, verifier)
    return False


def password_needs_rehash(verifier: str) -> bool:
    """Return whether a verifier should be upgraded to the current parameters."""

    if verifier.startswith(_SCRYPT_PREFIX):
        return True
    if verifier.startswith(_ARGON2ID_PREFIX):
        try:
            return _ARGON2_HASHER.check_needs_rehash(verifier)
        except InvalidHashError:
            return True
    return True


def _verify_scrypt(password: str, verifier: str) -> bool:
    try:
        password_bytes = password.encode("utf-8")
        algorithm, version, n_value, r_value, p_value, salt_value, digest_value = verifier.split(
            "$"
        )
        if algorithm != "scrypt" or version != f"v={_SCRYPT_VERSION}":
            return False
        n = _parse_parameter(n_value, "n")
        r = _parse_parameter(r_value, "r")
        p = _parse_parameter(p_value, "p")
        if (n, r, p) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
            return False
        salt = _unb64(salt_value)
        expected = _unb64(digest_value)
        if len(expected) != _SCRYPT_DKLEN:
            return False
        actual = hashlib.scrypt(
            password_bytes,
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (UnicodeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _verify_argon2id(password: str, verifier: str) -> bool:
    try:
        return _ARGON2_HASHER.verify(verifier, password.encode("utf-8"))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def issue_opaque_token(*, token_id: UUID | None = None) -> OpaqueTokenMaterial:
    resolved_id = token_id or uuid4()
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    raw_token = f"{resolved_id}.{secret}"
    digest = digest_opaque_secret(secret)
    return OpaqueTokenMaterial(
        token_id=resolved_id,
        raw_token=raw_token,
        digest=digest,
        fingerprint=digest.hex()[:16],
    )


def parse_opaque_token(raw_token: str) -> ParsedOpaqueToken:
    try:
        token_id_value, secret = raw_token.split(".", maxsplit=1)
        token_id = UUID(token_id_value)
    except (ValueError, AttributeError) as exc:
        raise SessionTokenInvalid("opaque token is malformed") from exc
    if not secret or len(secret) > 256:
        raise SessionTokenInvalid("opaque token is malformed")
    return ParsedOpaqueToken(token_id=token_id, secret=secret)


def digest_opaque_secret(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def verify_opaque_secret(secret: str, expected_digest: bytes) -> bool:
    if len(expected_digest) != hashlib.sha256().digest_size:
        return False
    return hmac.compare_digest(digest_opaque_secret(secret), expected_digest)


def native_authenticated_subject(
    *, identity_authority_id: UUID, native_identity_id: UUID
) -> AuthenticatedSubject:
    """Return provider-neutral output after Native credential/session verification."""

    return AuthenticatedSubject(
        authority_id=str(identity_authority_id),
        subject_id=str(native_identity_id),
        subject_class=AuthenticatedSubjectClass.HUMAN,
        metadata={"authentication_authority_kind": _NATIVE_AUTHORITY_KIND},
    )


def _validate_password(password: str) -> bytes:
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise PasswordPolicyViolation(
            f"password must contain at least {_MIN_PASSWORD_LENGTH} characters"
        )
    try:
        password_bytes = password.encode("utf-8")
    except UnicodeError as exc:
        raise PasswordPolicyViolation("password must be valid UTF-8") from exc
    if len(password_bytes) > _MAX_PASSWORD_BYTES:
        raise PasswordPolicyViolation("password is too large")
    return password_bytes


def _parse_parameter(value: str, name: str) -> int:
    prefix = f"{name}="
    if not value.startswith(prefix):
        raise ValueError("invalid verifier parameter")
    return int(value.removeprefix(prefix))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
