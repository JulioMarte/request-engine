from typing import Any, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


def platform_principal(conn: PgConnection, *, subject: str | None = None) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.principals "
        "(principal_plane, principal_kind, external_subject) "
        "VALUES ('platform', 'human', %s) RETURNING id",
        (subject or f"platform-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def platform_grant(
    conn: PgConnection, *, principal_id: UUID, capability: str, delegable: bool
) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants "
        "(principal_id, principal_plane, authority_plane, capability_key, "
        "delegable, provenance_kind, provenance_reference) "
        "VALUES (%s, 'platform', 'platform', %s, %s, 'trust_bootstrap', %s)",
        (principal_id, capability, delegable, f"proof:{uuid4().hex}"),
    )


def principal_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])
