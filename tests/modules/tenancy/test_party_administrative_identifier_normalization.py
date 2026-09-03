import pytest

from request_engine.modules.tenancy.contracts.party_administrative_identifiers import (
    PartyAdministrativeIdentifierKind,
)
from request_engine.modules.tenancy.domain.party_administrative_identifiers import (
    normalize_administrative_identifier_issuer,
    normalize_administrative_identifier_kind,
    normalize_administrative_identifier_value,
)


def test_insurance_member_kind_is_explicit() -> None:
    assert (
        normalize_administrative_identifier_kind(" INSURANCE_MEMBER ")
        is PartyAdministrativeIdentifierKind.INSURANCE_MEMBER
    )


def test_issuer_is_unicode_normalized_case_folded_and_space_bounded() -> None:
    assert normalize_administrative_identifier_issuer("  ars   primera  ") == "ARS PRIMERA"


def test_member_value_preserves_punctuation_but_removes_space_noise() -> None:
    assert normalize_administrative_identifier_value(" ab-12 34 ") == "AB-1234"


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_identifier_parts_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_administrative_identifier_issuer(value)
    with pytest.raises(ValueError):
        normalize_administrative_identifier_value(value)


def test_unknown_identifier_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported administrative identifier kind"):
        normalize_administrative_identifier_kind("policy_balance")
