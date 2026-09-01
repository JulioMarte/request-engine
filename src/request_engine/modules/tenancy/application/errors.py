"""Typed errors for the tenancy party registry commands."""

from uuid import UUID


class PartyRegistryError(Exception):
    """Base class for typed party registry command failures."""


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
