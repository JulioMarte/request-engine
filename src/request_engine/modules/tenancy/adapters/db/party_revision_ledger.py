"""Append-only party identity revision ledger recording (docs/v3/38 §9.3)."""

import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.tenancy.adapters.db.party_registry_rows import (
    AttributedCommand,
    attribution_values,
    ledger_attribution,
)

_REGISTERED = "registered"
_PARTY_STATE_SQL = text(
    "SELECT identity_revision, display_name, active FROM request_engine.parties "
    "WHERE organization_id = :organization_id AND id = :party_id"
)
_ADVANCE_REVISION_SQL = text(
    "UPDATE request_engine.parties "
    "SET identity_revision = identity_revision + 1, updated_at = clock_timestamp() "
    "WHERE organization_id = :organization_id AND id = :party_id "
    "RETURNING identity_revision, display_name, active"
)
_CONTACTS_SQL = text(
    "SELECT id, channel, normalized_value, verified, active "
    "FROM request_engine.party_contact_points "
    "WHERE organization_id = :organization_id AND party_id = :party_id "
    "ORDER BY created_at, id"
)
_DOCUMENTS_SQL = text(
    "SELECT id, kind, authority, normalized_value, active "
    "FROM request_engine.party_identity_documents "
    "WHERE organization_id = :organization_id AND party_id = :party_id "
    "ORDER BY created_at, id"
)
_INSERT_REVISION_SQL = text(
    "INSERT INTO request_engine.party_identity_revisions "
    "(organization_id, party_id, revision, change_kind, display_name, active, state, "
    " actor_principal_id, attributed_operator_principal_id, source_kind, platform) "
    "VALUES (:organization_id, :party_id, :revision, :change_kind, :display_name, :active, "
    "CAST(:state AS jsonb), :actor_principal_id, :attributed_operator_principal_id, "
    ":source_kind, :platform) RETURNING revision"
)


async def record_party_revision(
    session: AsyncSession,
    *,
    command: AttributedCommand,
    organization_id: UUID,
    party_id: UUID,
    change_kind: str,
) -> int:
    scope = {"organization_id": organization_id, "party_id": party_id}
    if change_kind == _REGISTERED:
        state = (await session.execute(_PARTY_STATE_SQL, scope)).mappings().one()
    else:
        state = (await session.execute(_ADVANCE_REVISION_SQL, scope)).mappings().one()
    contacts = (await session.execute(_CONTACTS_SQL, scope)).mappings().all()
    documents = (await session.execute(_DOCUMENTS_SQL, scope)).mappings().all()
    snapshot = {
        "display_name": state["display_name"],
        "active": state["active"],
        "contact_points": [
            {
                "id": str(row["id"]),
                "channel": row["channel"],
                "normalized_value": row["normalized_value"],
                "verified": row["verified"],
                "active": row["active"],
            }
            for row in contacts
        ],
        "documents": [
            {
                "id": str(row["id"]),
                "kind": row["kind"],
                "authority": row["authority"],
                "normalized_value": row["normalized_value"],
                "active": row["active"],
            }
            for row in documents
        ],
    }
    revision = (
        await session.execute(
            _INSERT_REVISION_SQL,
            {
                "revision": state["identity_revision"],
                "change_kind": change_kind,
                "display_name": state["display_name"],
                "active": state["active"],
                "state": json.dumps(snapshot, separators=(",", ":")),
                **scope,
                **attribution_values(command),
                **ledger_attribution(command),
            },
        )
    ).scalar_one()
    return cast(int, revision)
