from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MANAGE_OPERATIONAL_PROFILE_SCOPE = "operations.manage_profile"
MANAGE_CONTEXTUAL_SUPPLY_SCOPE = "operations.manage_supply"
MANAGE_COMMERCIAL_TERMS_SCOPE = "operations.manage_terms"
MANAGE_DISCOVERY_SCOPE = "operations.manage_discovery"


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


async def require_operational_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    authority_party_id: UUID,
    scope_key: str,
) -> OperationalAuthorityGrant:
    """Require current exact-scope Representation authority inside the caller transaction."""
    if not scope_key:
        raise ValueError("scope_key is required")

    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT representation_id
                    FROM request_engine.lock_current_party_authority(
                        :organization_id,
                        :principal_id,
                        :authority_party_id,
                        :scope_key
                    )
                    """
                ),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "authority_party_id": authority_party_id,
                    "scope_key": scope_key,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise OperationalAuthorityRequired(authority_party_id, scope_key)
    return OperationalAuthorityGrant(
        representation_id=cast(UUID, row["representation_id"]),
        authority_party_id=authority_party_id,
        scope_key=scope_key,
    )
