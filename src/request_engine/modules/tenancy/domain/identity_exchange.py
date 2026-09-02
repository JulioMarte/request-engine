"""Pure S0d identity-exchange normalization and keyed matching rules."""

import hashlib
import hmac

from request_engine.modules.tenancy.domain.party_identity import normalize_identity_document

_ALLOWED_FIELDS = frozenset({"display_name", "phone", "email", "insurance_member"})
_REQUIRED_ADOPTION_FIELDS = frozenset({"display_name"})
_NAMESPACE = "identity-exchange:v1|document|DO:JCE|cedula|"
_MINIMUM_KEY_BYTES = 32


def normalize_portable_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    """Return stable, duplicate-free portable fields or reject unsupported consent."""

    normalized = tuple(dict.fromkeys(item.strip() for item in fields if item.strip()))
    if not normalized:
        raise ValueError("at least one portable field is required")
    unsupported = set(normalized) - _ALLOWED_FIELDS
    if unsupported:
        raise ValueError(f"unsupported portable fields: {', '.join(sorted(unsupported))}")
    return normalized


def require_adoptable_fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    normalized = normalize_portable_fields(fields)
    missing = _REQUIRED_ADOPTION_FIELDS - set(normalized)
    if missing:
        raise ValueError("display_name consent is required for automatic adoption")
    return normalized


def normalize_witnessed_cedula(value: str) -> str:
    return normalize_identity_document("cedula", value)


def cedula_fingerprint(key: bytes | None, normalized_cedula: str) -> str:
    """Build a non-enumerable equality fingerprint; there is intentionally no default key."""

    if key is None or len(key) < _MINIMUM_KEY_BYTES:
        raise RuntimeError("identity exchange key must contain at least 32 bytes")
    message = f"{_NAMESPACE}{normalized_cedula}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()
