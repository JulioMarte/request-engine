"""Party registry view assembly: authoritative rows in, RegisteredParty out."""

from collections.abc import Callable
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_registry_codec import view_from_rows
from request_engine.modules.tenancy.contracts.party_registry import (
    PartyContactPoint,
    PartyIdentityDocument,
    RegisteredParty,
)


async def load_party_views(
    session: AsyncSession, organization_id: UUID, party_ids: list[UUID]
) -> list[RegisteredParty]:
    if not party_ids:
        return []
    party_rows = (
        await session.execute(
            text(
                "SELECT id AS party_id, organization_id, party_kind, display_name, active "
                "FROM request_engine.parties "
                "WHERE organization_id = :organization_id AND id = ANY(:party_ids)"
            ),
            {"organization_id": organization_id, "party_ids": party_ids},
        )
    ).mappings()
    party_by_id = {cast(UUID, row["party_id"]): row for row in party_rows}
    contact_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id, party_id, channel, normalized_value, verified, source_kind "
                    "FROM request_engine.party_contact_points "
                    "WHERE organization_id = :organization_id AND active "
                    "AND party_id = ANY(:party_ids) ORDER BY created_at, id"
                ),
                {"organization_id": organization_id, "party_ids": party_ids},
            )
        ).mappings()
    )
    document_rows = list(
        (
            await session.execute(
                text(
                    "SELECT id, party_id, kind, authority, normalized_value "
                    "FROM request_engine.party_identity_documents "
                    "WHERE organization_id = :organization_id AND active "
                    "AND party_id = ANY(:party_ids) ORDER BY created_at, id"
                ),
                {"organization_id": organization_id, "party_ids": party_ids},
            )
        ).mappings()
    )
    return [
        view_from_rows(
            party_by_id[party_id],
            [row for row in contact_rows if row["party_id"] == party_id],
            [row for row in document_rows if row["party_id"] == party_id],
        )
        for party_id in party_ids
        if party_id in party_by_id
    ]


def document_by_id(state: RegisteredParty, document_id: UUID) -> PartyIdentityDocument | None:
    return next(
        (document for document in state.documents if document.document_id == document_id), None
    )


def document_by_identity(
    state: RegisteredParty, kind: str, authority: str, normalized_value: str
) -> PartyIdentityDocument | None:
    return next(
        (
            document
            for document in state.documents
            if document.kind == kind
            and document.authority == authority
            and document.normalized_value == normalized_value
        ),
        None,
    )


def contact_point_by_id(state: RegisteredParty, contact_point_id: UUID) -> PartyContactPoint | None:
    return _find_contact_point(state, lambda c: c.contact_point_id == contact_point_id)


def contact_point_by_value(
    state: RegisteredParty, channel: str, normalized_value: str
) -> PartyContactPoint | None:
    return _find_contact_point(
        state, lambda c: c.channel == channel and c.normalized_value == normalized_value
    )


def _find_contact_point(
    state: RegisteredParty, predicate: Callable[[PartyContactPoint], bool]
) -> PartyContactPoint | None:
    return next((contact for contact in state.contact_points if predicate(contact)), None)
