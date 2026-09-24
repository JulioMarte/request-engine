from datetime import UTC, datetime, timedelta

import pytest

from request_engine.platform.security.appointment_option_keyring import (
    create_appointment_option_keyring,
    parse_appointment_option_keyring,
    rotate_appointment_option_keyring,
)

_NOW = datetime(2030, 1, 1, 12, tzinfo=UTC)
_KEY_ONE = b"appointment-option-key-one-000000000000000"
_KEY_TWO = b"appointment-option-key-two-000000000000000"
_KEY_THREE = b"appointment-option-key-three-0000000000000"


@pytest.mark.unit
def test_create_keyring_never_serializes_plaintext_outside_secret_payload_contract() -> None:
    encoded = create_appointment_option_keyring("k1", key=_KEY_ONE)
    parsed = parse_appointment_option_keyring(encoded)

    assert parsed.active_key_id == "k1"
    assert parsed.active_key == _KEY_ONE
    assert parsed.accepted_keys(now=_NOW) == {"k1": _KEY_ONE}
    assert "appointment-option-key-one" not in encoded


@pytest.mark.unit
def test_rotation_keeps_previous_active_only_for_bounded_token_overlap() -> None:
    initial = create_appointment_option_keyring("k1", key=_KEY_ONE)
    rotated = rotate_appointment_option_keyring(
        initial,
        new_key_id="k2",
        now=_NOW,
        token_ttl=timedelta(minutes=10),
        clock_skew=timedelta(seconds=30),
        new_key=_KEY_TWO,
    )
    parsed = parse_appointment_option_keyring(rotated)

    assert parsed.active_key_id == "k2"
    assert parsed.active_key == _KEY_TWO
    assert parsed.accepted_keys(now=_NOW) == {"k2": _KEY_TWO, "k1": _KEY_ONE}
    assert parsed.accepted_keys(now=_NOW + timedelta(minutes=10, seconds=31)) == {
        "k2": _KEY_TWO
    }


@pytest.mark.unit
def test_second_rotation_prunes_expired_retiring_key() -> None:
    initial = create_appointment_option_keyring("k1", key=_KEY_ONE)
    first = rotate_appointment_option_keyring(
        initial,
        new_key_id="k2",
        now=_NOW,
        new_key=_KEY_TWO,
    )
    second = rotate_appointment_option_keyring(
        first,
        new_key_id="k3",
        now=_NOW + timedelta(minutes=11),
        new_key=_KEY_THREE,
    )
    parsed = parse_appointment_option_keyring(second)

    assert {item.key_id for item in parsed.keys} == {"k2", "k3"}
    assert parsed.accepted_keys(now=_NOW + timedelta(minutes=11)) == {
        "k3": _KEY_THREE,
        "k2": _KEY_TWO,
    }


@pytest.mark.unit
def test_keyring_rejects_duplicate_rotation_id_and_unbounded_retiring_key() -> None:
    initial = create_appointment_option_keyring("k1", key=_KEY_ONE)
    with pytest.raises(ValueError, match="already exists"):
        rotate_appointment_option_keyring(initial, new_key_id="k1", now=_NOW)

    malformed = (
        '{"active_key_id":"k1","keys":{'
        '"k1":{"key":"YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE","verify_until":null},'
        '"k0":{"key":"YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmI","verify_until":null}'
        '},"version":1}'
    )
    with pytest.raises(ValueError, match="non-active"):
        parse_appointment_option_keyring(malformed)


@pytest.mark.unit
def test_keyring_rejects_short_or_invalid_key_material() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        create_appointment_option_keyring("k1", key=b"short")

    malformed = (
        '{"active_key_id":"k1","keys":{'
        '"k1":{"key":"not!base64","verify_until":null}'
        '},"version":1}'
    )
    with pytest.raises(ValueError, match="malformed"):
        parse_appointment_option_keyring(malformed)
