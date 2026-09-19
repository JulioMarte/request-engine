import pytest

from request_engine.platform.security.assurance import (
    AuthenticationAssurance,
    AuthenticationEvidence,
    AuthenticationMethod,
    InvalidAuthenticationEvidence,
    assurance_satisfies,
    classify_assurance,
)


def test_password_only_is_single_factor() -> None:
    assert (
        classify_assurance(AuthenticationEvidence.password())
        is AuthenticationAssurance.SINGLE_FACTOR
    )


def test_password_plus_totp_is_mfa() -> None:
    evidence = AuthenticationEvidence.password().combined_with(AuthenticationEvidence.totp())
    assert classify_assurance(evidence) is AuthenticationAssurance.MFA


def test_lone_totp_is_not_mfa() -> None:
    assert (
        classify_assurance(AuthenticationEvidence.totp()) is AuthenticationAssurance.SINGLE_FACTOR
    )


def test_verified_webauthn_is_phishing_resistant() -> None:
    assert (
        classify_assurance(AuthenticationEvidence.webauthn(user_verified=True))
        is AuthenticationAssurance.PHISHING_RESISTANT
    )


def test_webauthn_without_user_verification_is_not_phishing_resistant() -> None:
    assert (
        classify_assurance(AuthenticationEvidence.webauthn(user_verified=False))
        is AuthenticationAssurance.SINGLE_FACTOR
    )


def test_webauthn_without_user_verification_plus_password_is_mfa_only() -> None:
    evidence = AuthenticationEvidence.password().combined_with(
        AuthenticationEvidence.webauthn(user_verified=False)
    )
    assert classify_assurance(evidence) is AuthenticationAssurance.MFA


def test_empty_evidence_is_invalid() -> None:
    with pytest.raises(InvalidAuthenticationEvidence):
        classify_assurance(AuthenticationEvidence())


def test_password_plus_recovery_code_is_recovery_not_mfa() -> None:
    evidence = AuthenticationEvidence.password().combined_with(
        AuthenticationEvidence.recovery_code()
    )
    assert evidence.recovery_derived
    assert classify_assurance(evidence) is AuthenticationAssurance.RECOVERY


def test_recovery_plus_webauthn_is_recovery_not_phishing_resistant() -> None:
    evidence = AuthenticationEvidence.recovery_code().combined_with(
        AuthenticationEvidence.webauthn(user_verified=True)
    )
    assert classify_assurance(evidence) is AuthenticationAssurance.RECOVERY


def test_recovery_derived_never_helps_satisfy_mfa_or_phishing_resistant() -> None:
    recovery = AuthenticationEvidence.password().combined_with(
        AuthenticationEvidence.recovery_code()
    )
    assurance = classify_assurance(recovery)
    assert assurance_satisfies(assurance, AuthenticationAssurance.SINGLE_FACTOR)
    assert not assurance_satisfies(assurance, AuthenticationAssurance.MFA)
    assert not assurance_satisfies(assurance, AuthenticationAssurance.PHISHING_RESISTANT)


def test_duplicate_methods_do_not_create_mfa() -> None:
    evidence = AuthenticationEvidence.password().combined_with(AuthenticationEvidence.password())
    assert len(evidence.methods) == 1
    assert classify_assurance(evidence) is AuthenticationAssurance.SINGLE_FACTOR


def test_webauthn_user_verified_flag_requires_webauthn_method() -> None:
    with pytest.raises(InvalidAuthenticationEvidence):
        AuthenticationEvidence(
            frozenset({AuthenticationMethod.PASSWORD}), webauthn_user_verified=True
        )


def test_assurance_ordering() -> None:
    assert assurance_satisfies(
        AuthenticationAssurance.PHISHING_RESISTANT, AuthenticationAssurance.MFA
    )
    assert assurance_satisfies(AuthenticationAssurance.MFA, AuthenticationAssurance.SINGLE_FACTOR)
    assert not assurance_satisfies(
        AuthenticationAssurance.MFA, AuthenticationAssurance.PHISHING_RESISTANT
    )
    assert not assurance_satisfies(
        AuthenticationAssurance.SINGLE_FACTOR, AuthenticationAssurance.MFA
    )


def test_method_values_are_stable_and_sorted() -> None:
    evidence = AuthenticationEvidence.webauthn(user_verified=True).combined_with(
        AuthenticationEvidence.password()
    )
    assert evidence.method_values == ("password", "webauthn")


@pytest.mark.parametrize("required", list(AuthenticationAssurance))
def test_single_factor_satisfies_only_single_factor(
    required: AuthenticationAssurance,
) -> None:
    expected = required is AuthenticationAssurance.SINGLE_FACTOR
    assert assurance_satisfies(AuthenticationAssurance.SINGLE_FACTOR, required) is expected
