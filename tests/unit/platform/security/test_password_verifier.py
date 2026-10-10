import pytest

from request_engine.platform.security.native_auth import (
    hash_password,
    hash_password_scrypt,
    hash_provision_password_intent_v1,
    password_needs_rehash,
    verify_password,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

PASSWORD = "correct horse battery staple"


def test_argon2id_is_the_current_verifier() -> None:
    verifier = hash_password(PASSWORD)
    assert verifier.startswith("$argon2id$")
    assert verify_password(PASSWORD, verifier) is True


def test_argon2id_rejects_wrong_password() -> None:
    verifier = hash_password(PASSWORD)
    assert verify_password("wrong password entirely", verifier) is False


def test_legacy_scrypt_verifier_still_verifies() -> None:
    verifier = hash_password_scrypt(PASSWORD)
    assert verifier.startswith("scrypt$")
    assert verify_password(PASSWORD, verifier) is True
    assert verify_password("wrong password entirely", verifier) is False


def test_needs_rehash_upgrades_legacy_and_keeps_current() -> None:
    assert password_needs_rehash(hash_password_scrypt(PASSWORD)) is True
    assert password_needs_rehash(hash_password(PASSWORD)) is False


def test_unknown_verifier_scheme_fails_closed() -> None:
    assert verify_password(PASSWORD, "bcrypt$whatever") is False
    assert password_needs_rehash("bcrypt$whatever") is True


def test_argon2id_hashes_are_salted() -> None:
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_password_policy_is_still_enforced() -> None:
    with pytest.raises(ValueError):
        hash_password("short")


def test_provision_intent_profile_is_pinned_and_operation_scoped() -> None:
    first = hash_provision_password_intent_v1(PASSWORD, salt=b"a" * 16)
    assert first == hash_provision_password_intent_v1(PASSWORD, salt=b"a" * 16)
    assert first != hash_provision_password_intent_v1(PASSWORD, salt=b"b" * 16)
    assert "$argon2id$v=19$m=19456,t=2,p=1$" in first
    with pytest.raises(ValueError):
        hash_provision_password_intent_v1("short", salt=b"a" * 16)
