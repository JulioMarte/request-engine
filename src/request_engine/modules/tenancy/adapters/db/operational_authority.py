from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.contracts.operational_authority import (
    OperationalAuthorityGrant,
    OperationalAuthorityRequired,
)


async def require_operational_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    authority_party_id: UUID,
    scope_key: str,
) -> OperationalAuthorityGrant:
    if not scope_key:
        raise ValueError("scope_key is required")

    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT r.id AS representation_id
                    FROM request_engine.representations r
                    JOIN request_engine.principals p
                      ON p.organization_id = r.organization_id
                     AND p.id = r.principal_id
                    JOIN request_engine.parties party
                      ON party.organization_id = r.organization_id
                     AND party.id = r.represented_party_id
                    CROSS JOIN LATERAL (
                        SELECT clock_timestamp() AS db_now
                    ) clock
                    WHERE r.organization_id = :organization_id
                      AND r.principal_id = :principal_id
                      AND r.represented_party_id = :authority_party_id
                      AND r.scope_key = :scope_key
                      AND r.status = 'active'
                      AND p.active
                      AND party.active
                      AND r.valid_from <= clock.db_now
                      AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
                    ORDER BY r.valid_from DESC, r.id DESC
                    LIMIT 1
                    FOR SHARE OF r
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
