"""Authentication method/assurance classification (ADR 0014 §11).

Assurance is derived from the authentication ceremony that produced or refreshed
a session, never from the mere presence of a credential record. The classes are
deliberately small and Pydantic-free so both tenant and platform actors can share
one policy vocabulary.
"""

from __future__ import annotations

from enum import Enum


class AuthenticationMethod(Enum):
    PASSWORD = "password"
    WEBAUTHN = "webauthn"
    TOTP = "totp"
    RECOVERY_CODE = "recovery_code"


class AuthenticationAssurance(Enum):
    SINGLE_FACTOR = "single_factor"
    MFA = "mfa"
    PHISHING_RESISTANT = "phishing_resistant"
    RECOVERY = "recovery"


_ASSURANCE_ORDER: dict[AuthenticationAssurance, int] = {
    AuthenticationAssurance.SINGLE_FACTOR: 0,
    AuthenticationAssurance.MFA: 1,
    AuthenticationAssurance.PHISHING_RESISTANT: 2,
}


def classify_assurance(
    methods: frozenset[AuthenticationMethod],
    *,
    recovery_derived: bool = False,
) -> AuthenticationAssurance:
    """Classify the strongest assurance a completed ceremony actually proves.

    - recovery-derived sessions are ``RECOVERY`` regardless of other factors;
    - a verified WebAuthn ceremony is ``PHISHING_RESISTANT``;
    - two or more independent factors are ``MFA``;
    - anything else (including a lone TOTP or password) is ``SINGLE_FACTOR``.
    """

    if recovery_derived:
        return AuthenticationAssurance.RECOVERY
    if AuthenticationMethod.WEBAUTHN in methods:
        return AuthenticationAssurance.PHISHING_RESISTANT
    if len(methods) >= 2:
        return AuthenticationAssurance.MFA
    return AuthenticationAssurance.SINGLE_FACTOR


def assurance_satisfies(
    actual: AuthenticationAssurance,
    required: AuthenticationAssurance,
) -> bool:
    """Return whether ``actual`` meets ``required`` for a high-risk operation.

    ``RECOVERY`` is not a stronger class than ``SINGLE_FACTOR``: a recovery-derived
    session must not satisfy an MFA or phishing-resistant step-up requirement.
    """

    if required is AuthenticationAssurance.RECOVERY:
        return actual is AuthenticationAssurance.RECOVERY
    if actual is AuthenticationAssurance.RECOVERY:
        return required is AuthenticationAssurance.SINGLE_FACTOR
    return _ASSURANCE_ORDER[actual] >= _ASSURANCE_ORDER[required]
