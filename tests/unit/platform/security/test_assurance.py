import pytest

from request_engine.platform.security.assurance import (
    AuthenticationAssurance,
    AuthenticationMethod,
    assurance_satisfies,
    classify_assurance,
)


def test_password_only_is_single_factor() -> None:
    assert (
        classify_assurance(frozenset({AuthenticationMethod.PASSWORD}))
        is AuthenticationAssurance.SINGLE_FACTOR
    )


def test_password_plus_totp_is_mfa() -> None:
    assert (
        classify_assurance(frozenset({AuthenticationMethod.PASSWORD, AuthenticationMethod.TOTP}))
        is AuthenticationAssurance.MFA
    )


def test_lone_totp_is_not_mfa() -> None:
    assert (
        classify_assurance(frozenset({AuthenticationMethod.TOTP}))
        is AuthenticationAssurance.SINGLE_FACTOR
    )


def test_webauthn_is_phishing_resistant() -> None:
    assert (
        classify_assurance(frozenset({AuthenticationMethod.WEBAUTHN}))
        is AuthenticationAssurance.PHISHING_RESISTANT
    )


def test_recovery_derived_is_recovery_even_with_strong_methods() -> None:
    assert (
        classify_assurance(
            frozenset({AuthenticationMethod.WEBAUTHN, AuthenticationMethod.PASSWORD}),
            recovery_derived=True,
        )
        is AuthenticationAssurance.RECOVERY
    )


def test_recovery_does_not_satisfy_mfa_or_phishing_resistant() -> None:
    assert assurance_satisfies(
        AuthenticationAssurance.RECOVERY, AuthenticationAssurance.SINGLE_FACTOR
    )
    assert not assurance_satisfies(AuthenticationAssurance.RECOVERY, AuthenticationAssurance.MFA)
    assert not assurance_satisfies(
        AuthenticationAssurance.RECOVERY, AuthenticationAssurance.PHISHING_RESISTANT
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


def test_empty_methods_is_single_factor() -> None:
    assert classify_assurance(frozenset()) is AuthenticationAssurance.SINGLE_FACTOR


@pytest.mark.parametrize("required", list(AuthenticationAssurance))
def test_single_factor_satisfies_only_single_factor(
    required: AuthenticationAssurance,
) -> None:
    expected = required is AuthenticationAssurance.SINGLE_FACTOR
    assert assurance_satisfies(AuthenticationAssurance.SINGLE_FACTOR, required) is expected
