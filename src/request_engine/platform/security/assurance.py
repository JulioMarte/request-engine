"""Trusted authentication evidence and assurance classification (ADR 0014 §11).

Assurance is derived from the authentication ceremony that produced or refreshed
a session, never from the mere presence of a credential record and never from
caller-supplied metadata. Callers build :class:`AuthenticationEvidence` only from
trusted verification output (a verified password, a verified WebAuthn assertion,
a verified TOTP, a consumed recovery code).

The model is deliberately small and Pydantic-free so tenant and platform actors
share one policy vocabulary. Classification is fail-closed:

- no completed method -> invalid, no authenticated assurance can be produced;
- any recovery-derived ceremony -> ``RECOVERY`` and recovery never satisfies MFA
  or phishing-resistant requirements;
- WebAuthn only becomes ``PHISHING_RESISTANT`` when user verification was
  actually accepted, never merely because the method is present;
- two or more independent non-recovery factors -> ``MFA``;
- anything else -> ``SINGLE_FACTOR``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "AuthenticationAssurance",
    "AuthenticationEvidence",
    "AuthenticationMethod",
    "InvalidAuthenticationEvidence",
    "assurance_satisfies",
    "classify_assurance",
    "evidence_from_values",
]


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


class InvalidAuthenticationEvidence(ValueError):
    """Raised when evidence cannot prove any authenticated ceremony."""


_INDEPENDENT_FACTORS = frozenset(
    {
        AuthenticationMethod.PASSWORD,
        AuthenticationMethod.WEBAUTHN,
        AuthenticationMethod.TOTP,
    }
)

_ASSURANCE_RANK: dict[AuthenticationAssurance, int] = {
    AuthenticationAssurance.SINGLE_FACTOR: 0,
    AuthenticationAssurance.MFA: 1,
    AuthenticationAssurance.PHISHING_RESISTANT: 2,
}


def _empty_methods() -> frozenset[AuthenticationMethod]:
    return frozenset()


@dataclass(frozen=True, slots=True)
class AuthenticationEvidence:
    """Trusted facts about the authentication ceremonies proven for a session.

    ``webauthn_user_verified`` may only be set from a WebAuthn verification result
    whose user-verification requirement was actually satisfied. It is not a hint
    or a policy toggle; a WebAuthn method without accepted UV is a possession
    factor, not phishing resistance.
    """

    methods: frozenset[AuthenticationMethod] = field(default_factory=_empty_methods)
    webauthn_user_verified: bool = False

    def __post_init__(self) -> None:
        if self.webauthn_user_verified and AuthenticationMethod.WEBAUTHN not in self.methods:
            raise InvalidAuthenticationEvidence(
                "webauthn_user_verified requires a completed WebAuthn method"
            )

    @classmethod
    def password(cls) -> AuthenticationEvidence:
        return cls(frozenset({AuthenticationMethod.PASSWORD}))

    @classmethod
    def webauthn(cls, *, user_verified: bool) -> AuthenticationEvidence:
        return cls(
            frozenset({AuthenticationMethod.WEBAUTHN}),
            webauthn_user_verified=user_verified,
        )

    @classmethod
    def totp(cls) -> AuthenticationEvidence:
        return cls(frozenset({AuthenticationMethod.TOTP}))

    @classmethod
    def recovery_code(cls) -> AuthenticationEvidence:
        return cls(frozenset({AuthenticationMethod.RECOVERY_CODE}))

    @property
    def recovery_derived(self) -> bool:
        return AuthenticationMethod.RECOVERY_CODE in self.methods

    @property
    def method_values(self) -> tuple[str, ...]:
        return tuple(sorted(method.value for method in self.methods))

    def combined_with(self, other: AuthenticationEvidence) -> AuthenticationEvidence:
        """Return evidence for a ceremony that proved both sets of methods."""

        return AuthenticationEvidence(
            self.methods | other.methods,
            webauthn_user_verified=self.webauthn_user_verified or other.webauthn_user_verified,
        )


def classify_assurance(evidence: AuthenticationEvidence) -> AuthenticationAssurance:
    """Classify the strongest assurance the completed ceremonies actually prove."""

    methods = evidence.methods
    if not methods:
        raise InvalidAuthenticationEvidence("no completed authentication methods")
    if AuthenticationMethod.RECOVERY_CODE in methods:
        return AuthenticationAssurance.RECOVERY
    if AuthenticationMethod.WEBAUTHN in methods and evidence.webauthn_user_verified:
        return AuthenticationAssurance.PHISHING_RESISTANT
    if len(methods & _INDEPENDENT_FACTORS) >= 2:
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
    return _ASSURANCE_RANK[actual] >= _ASSURANCE_RANK[required]


def evidence_from_values(
    methods: Iterable[str],
    *,
    user_verified: bool = False,
    recovery_derived: bool = False,
) -> AuthenticationEvidence:
    """Rebuild trusted evidence from persisted method values, failing closed.

    An unknown method value raises rather than being silently ignored, so a
    corrupted or future session row cannot be downgraded to a weaker assurance.
    """

    parsed = frozenset(AuthenticationMethod(value) for value in methods)
    if recovery_derived and AuthenticationMethod.RECOVERY_CODE not in parsed:
        parsed = parsed | {AuthenticationMethod.RECOVERY_CODE}
    return AuthenticationEvidence(parsed, webauthn_user_verified=user_verified)
