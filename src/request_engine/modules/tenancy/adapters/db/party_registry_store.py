"""SQL write/lock helpers for the tenancy party registry command transactions."""

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.application.errors import PartyNotFound

_INSERT_PARTY_SQL = text(
    """
    INSERT INTO request_engine.parties
        (organization_id, party_kind, display_name, created_by_principal_id, source_kind,
         platform, relay_principal_id)
    VALUES (:organization_id, :party_kind, :display_name, :principal_id, :source_kind,
            :platform, :relay_principal_id)
    RETURNING id
    """
)
_INSERT_CONTACT_POINT_SQL = text(
    """
    INSERT INTO request_engine.party_contact_points
        (organization_id, party_id, channel, normalized_value, verified, source_kind,
         platform, relay_principal_id, created_by_principal_id)
    VALUES (:organization_id, :party_id, :channel, :normalized_value, :verified, :source_kind,
            :platform, :relay_principal_id, :principal_id)
    RETURNING id
    """
)
_INSERT_DOCUMENT_SQL = text(
    """
    INSERT INTO request_engine.party_identity_documents
        (organization_id, party_id, kind, authority, normalized_value, created_by_principal_id,
         source_kind, platform, relay_principal_id)
    VALUES (:organization_id, :party_id, :kind, :authority, :normalized_value, :principal_id,
            :source_kind, :platform, :relay_principal_id)
    RETURNING id
    """
)
_LOCK_PARTY_SQL = text(
    "SELECT active, party_kind FROM request_engine.parties "
    "WHERE organization_id = :organization_id AND id = :party_id FOR UPDATE"
)
_LOCK_CONTACT_POINT_SQL = text(
    "SELECT verified FROM request_engine.party_contact_points "
    "WHERE organization_id = :organization_id AND id = :contact_point_id AND party_id = :party_id "
    "FOR UPDATE"
)
_CONFIRM_CONTACT_POINT_SQL = text(
    "UPDATE request_engine.party_contact_points "
    "SET verified = true, updated_at = clock_timestamp() "
    "WHERE organization_id = :organization_id AND id = :contact_point_id AND verified = false"
)


async def insert_party(
    session: AsyncSession,
    *,
    organization_id: UUID,
    party_kind: str,
    display_name: str,
    principal_id: UUID,
    attribution: dict[str, object],
) -> UUID:
    result = await session.execute(
        _INSERT_PARTY_SQL,
        {
            "organization_id": organization_id,
            "party_kind": party_kind,
            "display_name": display_name,
            "principal_id": principal_id,
            **attribution,
        },
    )
    return cast(UUID, result.mappings().one()["id"])


async def insert_contact_points(
    session: AsyncSession,
    rows: list[dict[str, object]],
) -> list[RowMapping]:
    return [
        (await session.execute(_INSERT_CONTACT_POINT_SQL, row)).mappings().one() for row in rows
    ]


async def insert_documents(
    session: AsyncSession,
    rows: list[dict[str, object]],
) -> list[RowMapping]:
    return [(await session.execute(_INSERT_DOCUMENT_SQL, row)).mappings().one() for row in rows]


async def lock_party(session: AsyncSession, organization_id: UUID, party_id: UUID) -> str:
    result = await session.execute(
        _LOCK_PARTY_SQL,
        {"organization_id": organization_id, "party_id": party_id},
    )
    row = result.mappings().first()
    if row is None or not cast(bool, row["active"]):
        raise PartyNotFound(party_id)
    return cast(str, row["party_kind"])


async def lock_contact_point(
    session: AsyncSession,
    organization_id: UUID,
    party_id: UUID,
    contact_point_id: UUID,
) -> RowMapping | None:
    result = await session.execute(
        _LOCK_CONTACT_POINT_SQL,
        {
            "organization_id": organization_id,
            "party_id": party_id,
            "contact_point_id": contact_point_id,
        },
    )
    return result.mappings().first()


async def confirm_contact_point(
    session: AsyncSession, organization_id: UUID, contact_point_id: UUID
) -> None:
    await session.execute(
        _CONFIRM_CONTACT_POINT_SQL,
        {"organization_id": organization_id, "contact_point_id": contact_point_id},
    )
