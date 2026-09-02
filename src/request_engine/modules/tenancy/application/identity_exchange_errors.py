"""Typed S0d identity-exchange failures."""

from uuid import UUID


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


class IdentityExchangeAlreadyAdopted(IdentityExchangeError):
    """Another adoption already bound this portable person in the destination tenant."""

    def __init__(self, existing_party_id: UUID) -> None:
        self.existing_party_id = existing_party_id
        super().__init__("portable identity is already adopted by this organization")
