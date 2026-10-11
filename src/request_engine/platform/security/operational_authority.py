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


async def require_principal_serialized_operational_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    authority_party_id: UUID,
    scope_key: str,
) -> OperationalAuthorityGrant:
    """Resolve Representation without inverting its revision trigger's locks.

    Scoped standing-grant adopters call this after their Principal SHARE check.
    Reacquiring that root makes this connection independently safe to resolve;
    it does not replace the caller's standing-capability check. Every committed
    Representation INSERT/UPDATE/DELETE bumps the same Principal, so locking a
    Representation row here would invert a writer's row-before-trigger order.
    Party validity still needs its own SHARE root: Party writes do not bump P.
    """
    if not scope_key:
        raise ValueError("scope_key is required")
    parameters = {
        "org": organization_id,
        "principal": principal_id,
        "party": authority_party_id,
        "scope": scope_key,
    }
    principal = await session.execute(
        text(
            "SELECT id FROM request_engine.principals WHERE organization_id=:org "
            "AND id=:principal AND active FOR SHARE"
        ),
        parameters,
    )
    if principal.scalar_one_or_none() is None:
        raise OperationalAuthorityRequired(authority_party_id, scope_key)
    party = await session.execute(
        text(
            "SELECT id FROM request_engine.parties WHERE organization_id=:org "
            "AND id=:party AND active FOR SHARE"
        ),
        parameters,
    )
    if party.scalar_one_or_none() is None:
        raise OperationalAuthorityRequired(authority_party_id, scope_key)
    # A separate statement sees a revocation which won the Principal root. A
    # writer waiting behind our root cannot commit; its older committed row is
    # intentionally still admissible at this defined serialization point.
    representation = await session.execute(
        text("""
            SELECT r.id FROM request_engine.representations r
            CROSS JOIN LATERAL (SELECT clock_timestamp() AS db_now) clock
            WHERE r.organization_id=:org AND r.principal_id=:principal
              AND r.represented_party_id=:party AND r.scope_key=:scope AND r.status='active'
              AND r.valid_from<=clock.db_now
              AND (r.valid_until IS NULL OR r.valid_until>clock.db_now)
            ORDER BY r.valid_from DESC,r.id DESC LIMIT 1
        """),
        parameters,
    )
    representation_id = representation.scalar_one_or_none()
    if representation_id is None:
        raise OperationalAuthorityRequired(authority_party_id, scope_key)
    return OperationalAuthorityGrant(cast(UUID, representation_id), authority_party_id, scope_key)
