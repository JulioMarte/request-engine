import re
import unicodedata
from enum import StrEnum

from request_engine.platform.public_contacts import (
    PublicContactValidationError,
    normalize_public_contact_value,
)


class PartyIdentityValidationError(ValueError):
    """Raised when a party identity value cannot be normalized."""


class PartyDocumentKind(StrEnum):
    CEDULA = "cedula"
    PASSPORT = "passport"


_PHONE_SEPARATORS = re.compile(r"[\s().-]+")
_NANP_LOCAL = re.compile(r"[2-9][0-9]{9}")
_NANP_COUNTRY = re.compile(r"1[2-9][0-9]{9}")
_PHONE_MIN_DIGITS = 10
_DOCUMENT_SEPARATORS = re.compile(r"[\s.-]+")
_CEDULA = re.compile(r"[0-9]{11}")
_PASSPORT = re.compile(r"[A-Z0-9]{6,17}")
_PASSPORT_AUTHORITY = re.compile(r"[A-Z]{2}")
_CEDULA_AUTHORITY = "DO:JCE"


def normalize_party_contact_value(channel: str, value: str) -> str:
    """Normalize a party contact point value, tolerating Dominican local formats."""

    cleaned = value.strip()
    if channel not in {"phone", "whatsapp"}:
        return normalize_public_contact_value(channel, value)
    digits = _PHONE_SEPARATORS.sub("", cleaned)
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("00"):
        digits = digits[2:]
    if _NANP_LOCAL.fullmatch(digits):
        return normalize_public_contact_value(channel, f"+1{digits}")
    if _NANP_COUNTRY.fullmatch(digits):
        return normalize_public_contact_value(channel, f"+{digits}")
    canonical = normalize_public_contact_value(channel, f"+{digits}")
    if len(digits) < _PHONE_MIN_DIGITS:
        raise PublicContactValidationError(
            f"{channel} must carry at least {_PHONE_MIN_DIGITS} digits"
        )
    return canonical


def _document_kind(kind: str) -> PartyDocumentKind:
    try:
        return PartyDocumentKind(kind)
    except ValueError:
        raise PartyIdentityValidationError(f"unsupported identity document kind: {kind}") from None


def normalize_identity_document_authority(kind: str, authority: str | None) -> str:
    """Canonicalize the issuer namespace used to distinguish document identities."""

    document_kind = _document_kind(kind)
    candidate = authority.strip().upper() if authority is not None else ""
    if document_kind is PartyDocumentKind.CEDULA:
        if candidate and candidate != _CEDULA_AUTHORITY:
            raise PartyIdentityValidationError("cedula authority must be DO:JCE")
        return _CEDULA_AUTHORITY
    if not candidate:
        raise PartyIdentityValidationError("passport issuing authority is required")
    if not _PASSPORT_AUTHORITY.fullmatch(candidate):
        raise PartyIdentityValidationError(
            "passport issuing authority must be a 2-letter ISO country code"
        )
    return candidate


def normalize_identity_document(kind: str, value: str) -> str:
    """Normalize an identity document value for its kind."""

    document_kind = _document_kind(kind)
    cleaned = value.strip()
    if document_kind is PartyDocumentKind.CEDULA:
        digits = _DOCUMENT_SEPARATORS.sub("", cleaned)
        if not _CEDULA.fullmatch(digits):
            raise PartyIdentityValidationError("cedula must be exactly 11 digits")
        return digits
    candidate = cleaned.upper()
    if not _PASSPORT.fullmatch(candidate):
        raise PartyIdentityValidationError("passport must be 6-17 letters and digits")
    return candidate


def name_search_key(display_name: str) -> str:
    """Return the accent-insensitive prefix-matching key for a display name."""

    decomposed = unicodedata.normalize("NFKD", display_name.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.split())
