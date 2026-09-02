"""Typed failures for Party administrative identifier mutations."""

from uuid import UUID


class PartyAdministrativeIdentifierConflict(Exception):
    def __init__(
        self,
        *,
        kind: str,
        issuer: str,
        normalized_value: str,
        existing_party_id: UUID,
    ) -> None:
        super().__init__(
            f"{kind} identifier {normalized_value!r} from {issuer!r} "
            f"belongs to Party {existing_party_id}"
        )
        self.kind = kind
        self.issuer = issuer
        self.normalized_value = normalized_value
        self.existing_party_id = existing_party_id
