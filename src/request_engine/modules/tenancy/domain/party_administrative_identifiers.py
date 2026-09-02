"""Normalization rules for third-party Party administrative identifiers."""

import re
import unicodedata

from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifierKind,
)

_SPACE_RUN = re.compile(r"\s+")
_ALL_SPACE = re.compile(r"\s+")


def normalize_administrative_identifier_kind(value: str) -> PartyAdministrativeIdentifierKind:
    try:
        return PartyAdministrativeIdentifierKind(value.strip().lower())
    except ValueError as error:
        raise ValueError(f"unsupported administrative identifier kind: {value!r}") from error


def normalize_administrative_identifier_issuer(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = _SPACE_RUN.sub(" ", normalized).upper()
    if not normalized:
        raise ValueError("administrative identifier issuer is required")
    if len(normalized) > 128:
        raise ValueError("administrative identifier issuer exceeds 128 characters")
    return normalized


def normalize_administrative_identifier_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = _ALL_SPACE.sub("", normalized).upper()
    if not normalized:
        raise ValueError("administrative identifier value is required")
    if len(normalized) > 256:
        raise ValueError("administrative identifier value exceeds 256 characters")
    return normalized
