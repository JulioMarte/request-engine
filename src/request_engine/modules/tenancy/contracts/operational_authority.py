from dataclasses import dataclass
from uuid import UUID


MANAGE_OPERATIONAL_PROFILE_SCOPE = "operations.manage_profile"
MANAGE_CONTEXTUAL_SUPPLY_SCOPE = "operations.manage_supply"
MANAGE_COMMERCIAL_TERMS_SCOPE = "operations.manage_terms"


class OperationalAuthorityRequired(PermissionError):
    def __init__(self, authority_party_id: UUID, scope_key: str) -> None:
        super().__init__(f"operational authority required for scope {scope_key}")
        self.authority_party_id = authority_party_id
        self.scope_key = scope_key


@dataclass(frozen=True, slots=True)
class OperationalAuthorityGrant:
    representation_id: UUID
    authority_party_id: UUID
    scope_key: str

    def audit_details(self) -> dict[str, str]:
        return {
            "representation_id": str(self.representation_id),
            "authority_party_id": str(self.authority_party_id),
            "scope_key": self.scope_key,
        }
