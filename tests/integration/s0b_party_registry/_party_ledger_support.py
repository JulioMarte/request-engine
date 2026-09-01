"""Shared world builders and raw-SQL oracles for the revision ledger proofs."""

from typing import Any
from uuid import UUID

from psycopg import Connection

PgConnection = Connection[Any]


def identity_state(conn: PgConnection, organization_id: UUID, party_id: UUID) -> dict[str, object]:
    """Raw-SQL oracle: the full identity state of one Party right now."""

    party = conn.execute(
        "SELECT display_name, active FROM request_engine.parties"
        " WHERE organization_id = %s AND id = %s",
        (organization_id, party_id),
    ).fetchone()
    assert party is not None
    contacts = conn.execute(
        "SELECT id, channel, normalized_value, verified, active"
        " FROM request_engine.party_contact_points"
        " WHERE organization_id = %s AND party_id = %s ORDER BY created_at, id",
        (organization_id, party_id),
    ).fetchall()
    documents = conn.execute(
        "SELECT id, kind, normalized_value, active"
        " FROM request_engine.party_identity_documents"
        " WHERE organization_id = %s AND party_id = %s ORDER BY created_at, id",
        (organization_id, party_id),
    ).fetchall()
    return {
        "display_name": party[0],
        "active": party[1],
        "contact_points": [
            {
                "id": str(row[0]),
                "channel": row[1],
                "normalized_value": row[2],
                "verified": row[3],
                "active": row[4],
            }
            for row in contacts
        ],
        "documents": [
            {"id": str(row[0]), "kind": row[1], "normalized_value": row[2], "active": row[3]}
            for row in documents
        ],
    }


def ledger_rows(conn: PgConnection, organization_id: UUID) -> list[tuple[Any, ...]]:
    """All ledger rows of one organization ordered by revision."""

    return conn.execute(
        "SELECT revision, change_kind, display_name, active, state"
        " FROM request_engine.party_identity_revisions"
        " WHERE organization_id = %s ORDER BY revision",
        (organization_id,),
    ).fetchall()
