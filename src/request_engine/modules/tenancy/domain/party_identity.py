import re
import unicodedata
from enum import StrEnum

from request_engine.platform.public_contacts import normalize_public_contact_value


class PartyIdentityValidationError(ValueError):
    """Raised when a party identity value cannot be normalized."""


class PartyDocumentKind(StrEnum):
    CEDULA = "cedula"
    PASSPORT = "passport"


_PHONE_SEPARATORS = re.compile(r"[\s().-]+")
_NANP_LOCAL = re.compile(r"[2-9][0-9]{9}")
_NANP_COUNTRY = re.compile(r"1[2-9][0-9]{9}")
_DOCUMENT_SEPARATORS = re.compile(r"[\s.-]+")
_CEDULA = re.compile(r"[0-9]{11}")
_PASSPORT = re.compile(r"[A-Z0-9]{6,17}")


def normalize_party_contact_value(channel: str, value: str) -> str:
    """Normalize a party contact point value, tolerating Dominican local formats."""

    cleaned = value.strip()
    if channel in {"phone", "whatsapp"} and not cleaned.startswith("+"):
        local = _PHONE_SEPARATORS.sub("", cleaned)
        if _NANP_LOCAL.fullmatch(local):
            return normalize_public_contact_value(channel, f"+1{local}")
        if _NANP_COUNTRY.fullmatch(local):
            return normalize_public_contact_value(channel, f"+{local}")
    return normalize_public_contact_value(channel, value)


def normalize_identity_document(kind: str, value: str) -> str:
    """Normalize an identity document value for its kind."""

    try:
        document_kind = PartyDocumentKind(kind)
    except ValueError:
        raise PartyIdentityValidationError(f"unsupported identity document kind: {kind}") from None
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
