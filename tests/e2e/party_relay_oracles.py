"""Raw-SQL oracles for the party relay e2e proofs (never production readers)."""

from typing import Any
from uuid import UUID

from .operational_support import PgConnection


def contact_point_facts(
    conn: PgConnection, organization_id: UUID, contact_point_id: UUID
) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT verified, source_kind, platform, relay_principal_id, created_by_principal_id"
        " FROM request_engine.party_contact_points WHERE organization_id = %s AND id = %s",
        (organization_id, contact_point_id),
    ).fetchone()
    assert row is not None
    return tuple(row)


def party_count(conn: PgConnection, organization_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.parties WHERE organization_id = %s",
        (organization_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def latest_revision(conn: PgConnection, organization_id: UUID, party_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT actor_principal_id, attributed_operator_principal_id, source_kind, platform"
        " FROM request_engine.party_identity_revisions"
        " WHERE organization_id = %s AND party_id = %s ORDER BY revision DESC LIMIT 1",
        (organization_id, party_id),
    ).fetchone()
    assert row is not None
    return tuple(row)
