"""Typed errors for the tenancy party registry commands."""

from datetime import datetime
from uuid import UUID


class PartyRegistryError(Exception):
    """Base class for typed party registry command failures."""


class BootstrapAuthorityPartyInvalid(PartyRegistryError):
    """The requested bootstrap authority Party is not a usable tenant organization Party."""

    def __init__(self, party_id: UUID) -> None:
        super().__init__(f"Party {party_id} is not an active organization Party of this tenant")
        self.party_id = party_id


class PartyNotFound(PartyRegistryError):
    def __init__(self, party_id: UUID) -> None:
        super().__init__(f"Party {party_id} was not found")
        self.party_id = party_id


class PartyContactPointNotFound(PartyRegistryError):
    def __init__(
        self,
        party_id: UUID,
        contact_point_id: UUID | None = None,
        *,
        channel: str | None = None,
        normalized_value: str | None = None,
    ) -> None:
        identifier = (
            str(contact_point_id)
            if contact_point_id is not None
            else f"{channel} {normalized_value}"
        )
        super().__init__(f"Contact point {identifier} was not found on Party {party_id}")
        self.party_id = party_id
        self.contact_point_id = contact_point_id
        self.channel = channel
        self.normalized_value = normalized_value


class PartyContactPointExists(PartyRegistryError):
    def __init__(self, party_id: UUID, channel: str, normalized_value: str) -> None:
        super().__init__(
            f"Party {party_id} already has a {channel} contact point {normalized_value}"
        )
        self.party_id = party_id
        self.channel = channel
        self.normalized_value = normalized_value


class PartyDocumentConflict(PartyRegistryError):
    def __init__(
        self,
        reason: str,
        *,
        existing_party_id: UUID | None = None,
        existing_display_name: str | None = None,
    ) -> None:
        super().__init__(f"party identity document conflict: {reason}")
        self.reason = reason
        self.existing_party_id = existing_party_id
        self.existing_display_name = existing_display_name


class PartyRevisionNotFound(PartyRegistryError):
    def __init__(self, party_id: UUID, revision: int) -> None:
        super().__init__(f"Revision {revision} was not found on Party {party_id}")
        self.party_id = party_id
        self.revision = revision


class PartyRevisionTargetInvalid(PartyRegistryError):
    def __init__(self, party_id: UUID, target_revision: int, current_revision: int) -> None:
        super().__init__(
            f"Target revision {target_revision} is ahead of Party {party_id}"
            f" (current revision {current_revision})"
        )
        self.party_id = party_id
        self.target_revision = target_revision
        self.current_revision = current_revision


class PrincipalContactNotFound(PartyRegistryError):
    def __init__(self, principal_id: UUID, contact_id: UUID) -> None:
        super().__init__(
            f"Administrative contact {contact_id} was not found on Principal {principal_id}"
        )
        self.principal_id = principal_id
        self.contact_id = contact_id


class PrincipalContactExists(PartyRegistryError):
    def __init__(self, principal_id: UUID, channel: str, normalized_value: str) -> None:
        super().__init__(
            f"Principal {principal_id} already has an active {channel} contact {normalized_value}"
        )
        self.principal_id = principal_id
        self.channel = channel
        self.normalized_value = normalized_value


class VerificationCodeInvalid(PartyRegistryError):
    def __init__(self, attempts_remaining: int) -> None:
        super().__init__(
            f"verification code does not match ({attempts_remaining} attempts remaining)"
        )
        self.attempts_remaining = attempts_remaining


class VerificationCodeExpired(PartyRegistryError):
    def __init__(self) -> None:
        super().__init__("no pending verification code is valid for this contact")


class VerificationAlreadyPending(PartyRegistryError):
    def __init__(self, expires_at: datetime) -> None:
        super().__init__("an unexpired verification code is already pending for this contact")
        self.expires_at = expires_at


class VerificationAttemptsExhausted(PartyRegistryError):
    def __init__(self) -> None:
        super().__init__("verification attempts are exhausted; request a new code")


class StaffContactForbidden(PartyRegistryError):
    def __init__(self, principal_id: UUID) -> None:
        super().__init__(
            f"Principal {principal_id} is not a human operator and may not manage"
            " staff administrative contacts"
        )
        self.principal_id = principal_id
