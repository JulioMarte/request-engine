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


def normalize_party_contact_value(channel: str, value: str) -> str:
    """Normalize a party contact point value, tolerating Dominican local formats.

    For phone/whatsapp, separators are stripped first; a leading "+" and a
    leading double-zero international prefix ("00 1 809 555 1234") are then
    dropped so a "+"/"00" candidate goes through the same NANP digit logic as
    a bare local format — "+8095551234" and "809-555-1234" converge to the
    same "+1"-prefixed identity. The contract floor (docs/v3/38 §3) applies
    after canonicalization: at least 10 digits, so "+596123456" is rejected.
    """

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


_DOCUMENT_SEPARATORS = re.compile(r"[\s.-]+")
_CEDULA = re.compile(r"[0-9]{11}")
_PASSPORT = re.compile(r"[A-Z0-9]{6,17}")


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
    """Return the accent-insensitive prefix-matching key for a display name.

    Lowercase + casefold, Unicode NFKD with combining marks stripped
    (accents fold to their ASCII base letter), whitespace runs collapsed.
    The stored-name SQL mirror in
    `party_registry_reader._match_name_prefix` folds the same accented
    Latin characters (a e i o u with grave/acute/umlaut/circumflex, plus
    ñ->n and ç->c) via translate(); the two maps must stay aligned.
    """

    decomposed = unicodedata.normalize("NFKD", display_name.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_marks.split())
