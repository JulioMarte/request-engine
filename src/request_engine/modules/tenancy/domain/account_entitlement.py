"""Self-service business owner account rules (ADR 0021).

An account entitlement is neither tenant nor platform authority: it only lets one
native identity create a bounded number of organizations it will control.
"""

import re
import unicodedata
from enum import StrEnum
from zoneinfo import available_timezones

ACCOUNT_ORGANIZATION_CREATE = "account.organization.create"
DEFAULT_TIMEZONE = "America/Santo_Domingo"
DEFAULT_LOCALE = "es-DO"
DEFAULT_CURRENCY = "DOP"
MAX_ORGANIZATIONS_PER_INVITATION = 10

_KEY_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountInvitationDelivery(StrEnum):
    EMAIL = "email"
    SHARED_CODE = "shared_code"


class AccountRuleViolation(ValueError):
    """A self-service account input violates the published rules."""


def normalize_account_email(value: str) -> str:
    normalized = value.strip().lower()
    if not 3 <= len(normalized) <= 254 or not normalized.isascii():
        raise AccountRuleViolation("email must be one ASCII mailbox of 3 to 254 characters")
    if _EMAIL_RE.fullmatch(normalized) is None:
        raise AccountRuleViolation("email must be one mailbox")
    return normalized


def validate_organization_key(value: str) -> str:
    if not 3 <= len(value) <= 63 or _KEY_RE.fullmatch(value) is None:
        raise AccountRuleViolation(
            "organization_key must be 3-63 lowercase letters, digits and single hyphens"
        )
    return value


def derive_organization_key(display_name: str, suffix: str) -> str:
    """Readable slug of the display name plus a deterministic disambiguating suffix."""
    if re.fullmatch(r"[0-9a-f]{6}", suffix) is None:
        raise AccountRuleViolation("organization key suffix must be six lowercase hex digits")
    ascii_name = (
        unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:48].strip("-")
    return validate_organization_key(f"{slug}-{suffix}" if slug else f"negocio-{suffix}")


def validate_timezone(value: str) -> str:
    if value not in available_timezones():
        raise AccountRuleViolation("timezone must be an IANA time zone name")
    return value


def validate_locale(value: str) -> str:
    if _LOCALE_RE.fullmatch(value) is None:
        raise AccountRuleViolation("locale must look like es-DO")
    return value


def validate_currency(value: str) -> str:
    if _CURRENCY_RE.fullmatch(value) is None:
        raise AccountRuleViolation("currency must be an ISO 4217 code such as DOP")
    return value


def validate_display_name(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise AccountRuleViolation("display_name must contain 1 to 200 characters")
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise AccountRuleViolation("display_name must not contain control characters")
    return normalized
