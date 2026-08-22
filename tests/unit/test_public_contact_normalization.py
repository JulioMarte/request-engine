import pytest

from request_engine.platform.public_contacts import (
    PublicContactValidationError,
    normalize_public_contact_value,
)


@pytest.mark.parametrize(
    ("channel", "raw", "expected"),
    [
        ("phone", "+1 (809) 555-0999", "+18095550999"),
        ("phone", " +1-809-555-0999 ", "+18095550999"),
        ("whatsapp", "+44 (20) 7946 0958", "+442079460958"),
        ("email", " Central@Example.Test ", "central@example.test"),
        ("email", "USER+Desk@Sub.Example.COM", "user+desk@sub.example.com"),
    ],
)
def test_public_contact_variants_have_one_canonical_value(
    channel: str,
    raw: str,
    expected: str,
) -> None:
    assert normalize_public_contact_value(channel, raw) == expected


@pytest.mark.parametrize(
    ("channel", "raw"),
    [
        ("phone", "809-555-0999"),
        ("phone", "+0123456789"),
        ("phone", "+1234567"),
        ("whatsapp", "+1234567890123456"),
        ("email", "person @example.com"),
        ("email", "person@@example.com"),
        ("email", "person@example"),
        ("email", "person@.example.com"),
        ("email", "person@example.com."),
        ("fax", "+18095550999"),
        ("phone", "   "),
    ],
)
def test_invalid_public_contacts_fail_closed(channel: str, raw: str) -> None:
    with pytest.raises(PublicContactValidationError):
        normalize_public_contact_value(channel, raw)
