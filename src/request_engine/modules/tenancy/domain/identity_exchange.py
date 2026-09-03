"""Pure S0d identity-exchange normalization and keyed matching rules."""

import hashlib
import hmac
from dataclasses import dataclass

from request_engine.modules.tenancy.domain.party_identity import (
    normalize_identity_document,
    normalize_identity_document_authority,
)

_ALLOWED_FIELDS = frozenset({"display_name", "phone", "email", "insurance_member"})
_REQUIRED_ADOPTION_FIELDS = frozenset({"display_name"})
_NAMESPACE = "identity-exchange:v1|document"
_MINIMUM_KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class ScopedIdentityDocument:
    kind: str
    authority: str
    value: str


def normalize_portable_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in fields if item.strip()))
    if not normalized:
        raise ValueError("at least one portable field is required")
    unsupported = set(normalized) - _ALLOWED_FIELDS
    if unsupported:
        raise ValueError(f"unsupported portable fields: {', '.join(sorted(unsupported))}")
    return normalized


def require_adoptable_fields(
    fields: tuple[str, ...],
    *,
    allow_insurance_member: bool = True,
) -> tuple[str, ...]:
    normalized = normalize_portable_fields(fields)
    if _REQUIRED_ADOPTION_FIELDS - set(normalized):
        raise ValueError("display_name consent is required for automatic adoption")
    if not allow_insurance_member and "insurance_member" in normalized:
        raise ValueError("insurance_member is only portable for person Parties")
    return normalized


def normalize_witnessed_document(
    kind: str, authority: str | None, value: str
) -> ScopedIdentityDocument:
    return ScopedIdentityDocument(
        kind=kind,
        authority=normalize_identity_document_authority(kind, authority),
        value=normalize_identity_document(kind, value),
    )


def identity_document_fingerprint(
    key: bytes | None,
    document: ScopedIdentityDocument,
) -> str:
    """Build a keyed equality fingerprint over kind + issuer + normalized document value."""

    if key is None or len(key) < _MINIMUM_KEY_BYTES:
        raise RuntimeError("identity exchange key must contain at least 32 bytes")
    message = (f"{_NAMESPACE}|{document.kind}|{document.authority}|{document.value}").encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()
