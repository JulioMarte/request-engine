"""Snapshot restoration for `parties.rollback_identity` (docs/v3/38 §9.3).

Applying a prior revision's snapshot restores the full recorded identity
state as the party's current state: display name, the `active` flag,
contact-point `active` states and document `active` states — including
deactivating facts that did not exist in the target snapshot. `verified` is
never touched: verification is monotone upward (I-S0b-4), and the contact
point guard would reject a downward flip anyway.
"""

from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_RESTORE_PARTY_SQL = text(
    "UPDATE request_engine.parties"
    " SET display_name = :display_name, active = :active, updated_at = clock_timestamp()"
    " WHERE organization_id = :organization_id AND id = :party_id"
)

_RESTORE_CONTACTS_SQL = text(
    "UPDATE request_engine.party_contact_points"
    " SET active = :active, updated_at = clock_timestamp()"
    " WHERE organization_id = :organization_id AND id = :contact_point_id"
)

_RESTORE_DOCUMENTS_SQL = text(
    "UPDATE request_engine.party_identity_documents"
    " SET active = :active, updated_at = clock_timestamp()"
    " WHERE organization_id = :organization_id AND id = :document_id"
)

_CURRENT_CONTACTS_SQL = text(
    "SELECT id FROM request_engine.party_contact_points"
    " WHERE organization_id = :organization_id AND party_id = :party_id"
)

_CURRENT_DOCUMENTS_SQL = text(
    "SELECT id FROM request_engine.party_identity_documents"
    " WHERE organization_id = :organization_id AND party_id = :party_id"
)


async def restore_snapshot(
    session: AsyncSession, organization_id: UUID, party_id: UUID, snapshot: object
) -> None:
    """Apply the recorded snapshot as the party's full current identity state."""

    state = cast(dict[str, object], snapshot)
    contacts = {
        cast(str, item["id"]): cast(bool, item["active"])
        for item in cast(list[dict[str, object]], state["contact_points"])
    }
    documents = {
        cast(str, item["id"]): cast(bool, item["active"])
        for item in cast(list[dict[str, object]], state["documents"])
    }
    await session.execute(
        _RESTORE_PARTY_SQL,
        {
            "organization_id": organization_id,
            "party_id": party_id,
            "display_name": state["display_name"],
            "active": state["active"],
        },
    )
    contact_rows = (
        await session.execute(_CURRENT_CONTACTS_SQL, _scope(organization_id, party_id))
    ).fetchall()
    for (contact_id,) in contact_rows:
        await session.execute(
            _RESTORE_CONTACTS_SQL,
            {
                "organization_id": organization_id,
                "contact_point_id": contact_id,
                "active": contacts.get(str(contact_id), False),
            },
        )
    document_rows = (
        await session.execute(_CURRENT_DOCUMENTS_SQL, _scope(organization_id, party_id))
    ).fetchall()
    for (document_id,) in document_rows:
        await session.execute(
            _RESTORE_DOCUMENTS_SQL,
            {
                "organization_id": organization_id,
                "document_id": document_id,
                "active": documents.get(str(document_id), False),
            },
        )


def _scope(organization_id: UUID, party_id: UUID) -> dict[str, object]:
    return {"organization_id": organization_id, "party_id": party_id}
