import pytest

from request_engine.modules.tenancy.domain.party_identity import (
    PartyIdentityValidationError,
    name_search_key,
    normalize_identity_document,
    normalize_identity_document_authority,
    normalize_party_contact_value,
)
from request_engine.platform.public_contacts import PublicContactValidationError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(809) 555-1234", "+18095551234"),
        ("809-555-1234", "+18095551234"),
        ("1 809 555 1234", "+18095551234"),
        ("18295551234", "+18295551234"),
        ("(849) 555-9876", "+18495559876"),
        ("+18095551234", "+18095551234"),
        ("+1 809 555 1234", "+18095551234"),
        ("+8095551234", "+18095551234"),
        ("00 1 809 555 1234", "+18095551234"),
    ],
)
def test_phone_channels_normalize_nanp_formats(raw: str, expected: str) -> None:
    assert normalize_party_contact_value("phone", raw) == expected
    assert normalize_party_contact_value("whatsapp", raw) == expected


@pytest.mark.parametrize("raw", ["809555123", "55512345", "809555abcd", "+596123456"])
def test_phone_channels_reject_invalid_values(raw: str) -> None:
    with pytest.raises(PublicContactValidationError):
        normalize_party_contact_value("phone", raw)


def test_phone_channels_enforce_ten_digit_floor() -> None:
    with pytest.raises(PublicContactValidationError):
        normalize_party_contact_value("whatsapp", "+596123456")


def test_email_delegates_to_platform_helper() -> None:
    assert normalize_party_contact_value("email", "Patient.Cruz@Example.COM") == (
        "patient.cruz@example.com"
    )


def test_email_rejects_invalid_address() -> None:
    with pytest.raises(PublicContactValidationError):
        normalize_party_contact_value("email", "patient example.com")


def test_cedula_normalizes_separators() -> None:
    assert normalize_identity_document("cedula", "402-1234567-8") == "40212345678"
    assert normalize_identity_document("cedula", "40212345678") == "40212345678"


@pytest.mark.parametrize("raw", ["4021234567", "402123456789", "402x2345678"])
def test_cedula_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(PartyIdentityValidationError):
        normalize_identity_document("cedula", raw)


def test_rnc_normalizes_separators_and_defaults_to_dgii() -> None:
    assert normalize_identity_document("rnc", "1-01-85004-3") == "101850043"
    assert normalize_identity_document_authority("rnc", None) == "DO:DGII"
    assert normalize_identity_document_authority("rnc", "do:dgii") == "DO:DGII"


@pytest.mark.parametrize("raw", ["10185004", "1018500430", "10A850043"])
def test_rnc_rejects_non_nine_digit_values(raw: str) -> None:
    with pytest.raises(PartyIdentityValidationError):
        normalize_identity_document("rnc", raw)


def test_rnc_rejects_wrong_authority() -> None:
    with pytest.raises(PartyIdentityValidationError):
        normalize_identity_document_authority("rnc", "DO:JCE")


def test_passport_normalizes_to_uppercase() -> None:
    assert normalize_identity_document("passport", "ab1234") == "AB1234"


@pytest.mark.parametrize("raw", ["ab123", "ab1234567890123456", "AB-1234"])
def test_passport_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(PartyIdentityValidationError):
        normalize_identity_document("passport", raw)


def test_unsupported_document_kind_is_rejected() -> None:
    with pytest.raises(PartyIdentityValidationError):
        normalize_identity_document("license", "AB1234")


def test_name_search_key_strips_accents_and_collapses_whitespace() -> None:
    assert name_search_key("José  Ramírez-De La Cruz") == "jose ramirez-de la cruz"
