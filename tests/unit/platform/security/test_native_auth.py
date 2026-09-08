from uuid import uuid4

import pytest

from request_engine.platform.security.authentication import AuthenticatedSubjectClass
from request_engine.platform.security.native_auth import (
    PasswordPolicyViolation,
    SessionTokenInvalid,
    digest_opaque_secret,
    hash_password,
    issue_opaque_token,
    native_authenticated_subject,
    normalize_login_handle,
    parse_opaque_token,
    verify_opaque_secret,
    verify_password,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


def test_password_verifier_never_contains_raw_password() -> None:
    password = "correct horse battery staple"

    verifier = hash_password(password)

    assert verifier.startswith("scrypt$v=1$")
    assert password not in verifier
    assert verify_password(password, verifier)
    assert not verify_password("incorrect horse battery staple", verifier)


def test_password_hash_uses_fresh_salt() -> None:
    password = "a sufficiently long password"

    first = hash_password(password)
    second = hash_password(password)

    assert first != second
    assert verify_password(password, first)
    assert verify_password(password, second)


def test_password_policy_rejects_short_password() -> None:
    with pytest.raises(PasswordPolicyViolation):
        hash_password("too-short")


def test_malformed_password_verifier_fails_closed() -> None:
    assert not verify_password("some very long password", "not-a-verifier")
    assert not verify_password(
        "some very long password",
        "scrypt$v=1$n=1$r=8$p=1$YWJj$YWJj",
    )


def test_opaque_token_persists_only_digest_and_fingerprint() -> None:
    material = issue_opaque_token()
    parsed = parse_opaque_token(material.raw_token)

    assert parsed.token_id == material.token_id
    assert parsed.secret not in material.digest.hex()
    assert len(material.digest) == 32
    assert material.fingerprint == material.digest.hex()[:16]
    assert verify_opaque_secret(parsed.secret, material.digest)
    assert not verify_opaque_secret("wrong-secret", material.digest)


def test_digest_is_deterministic_for_verification() -> None:
    material = issue_opaque_token()
    parsed = parse_opaque_token(material.raw_token)

    assert digest_opaque_secret(parsed.secret) == material.digest


@pytest.mark.parametrize("raw_token", ["", "not-a-token", "not-a-uuid.secret", ".secret"])
def test_malformed_opaque_token_fails_closed(raw_token: str) -> None:
    with pytest.raises(SessionTokenInvalid):
        parse_opaque_token(raw_token)


def test_login_handle_normalization_is_deterministic() -> None:
    assert normalize_login_handle("  Julio.Example@Example.COM  ") == "julio.example@example.com"


def test_native_authentication_output_contains_no_authority_claims() -> None:
    authority_id = uuid4()
    identity_id = uuid4()

    subject = native_authenticated_subject(
        identity_authority_id=authority_id,
        native_identity_id=identity_id,
    )

    assert subject.authority_id == str(authority_id)
    assert subject.subject_id == str(identity_id)
    assert subject.subject_class is AuthenticatedSubjectClass.HUMAN
    assert "principal_id" not in subject.metadata
    assert "organization_id" not in subject.metadata
    assert "capabilities" not in subject.metadata
