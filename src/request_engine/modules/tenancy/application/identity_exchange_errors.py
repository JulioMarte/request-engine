"""Typed S0d identity-exchange failures."""


class IdentityExchangeError(Exception):
    """Base failure for the federated identity surface."""


class IdentityExchangeUnavailable(IdentityExchangeError):
    """Deployment did not configure the keyed identity fingerprint secret."""


class IdentityExchangeOperatorRequired(IdentityExchangeError):
    """The asserted proof requires effective human-operator authority."""


class IdentityExchangeCandidateInvalid(IdentityExchangeError):
    """Candidate is missing, expired, consumed or does not match the witnessed document."""


class IdentityExchangeProfileInvalid(IdentityExchangeError):
    """Portable profile cannot satisfy the requested adoption."""
