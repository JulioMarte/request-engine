from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from request_engine.platform.security.native_auth import (
    OpaqueTokenMaterial,
    digest_opaque_secret,
    hash_password,
    issue_opaque_token,
    normalize_login_handle,
    parse_opaque_token,
)


class PlatformBootstrapError(RuntimeError):
    """Base class for deployment-trust bootstrap failures."""


class PlatformBootstrapRejected(PlatformBootstrapError):
    """Bootstrap evidence was invalid, expired, consumed, or otherwise unusable."""


class PlatformRootAlreadyExists(PlatformBootstrapError):
    """The one-time initial Platform root has already been established."""


@dataclass(frozen=True, slots=True)
class PlatformBootstrapIntentMaterial:
    intent_id: UUID
    raw_token: str
    token_digest: bytes
    token_fingerprint: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformRootMaterial:
    native_identity_id: UUID
    credential_id: UUID
    principal_id: UUID
    binding_id: UUID
    login_handle: str
    password_verifier: str


def issue_platform_bootstrap_material(
    *,
    ttl: timedelta = timedelta(minutes=15),
    now: datetime | None = None,
) -> PlatformBootstrapIntentMaterial:
    if ttl <= timedelta(0):
        raise ValueError("platform bootstrap TTL must be positive")
    issued_at = now or datetime.now(UTC)
    token: OpaqueTokenMaterial = issue_opaque_token()
    return PlatformBootstrapIntentMaterial(
        intent_id=token.token_id,
        raw_token=token.raw_token,
        token_digest=token.digest,
        token_fingerprint=token.fingerprint,
        expires_at=issued_at + ttl,
    )


def prepare_platform_root(*, login_handle: str, password: str) -> PlatformRootMaterial:
    return PlatformRootMaterial(
        native_identity_id=uuid4(),
        credential_id=uuid4(),
        principal_id=uuid4(),
        binding_id=uuid4(),
        login_handle=normalize_login_handle(login_handle),
        password_verifier=hash_password(password),
    )


def parse_platform_bootstrap_token(raw_token: str) -> tuple[UUID, bytes]:
    parsed = parse_opaque_token(raw_token)
    return parsed.token_id, digest_opaque_secret(parsed.secret)
