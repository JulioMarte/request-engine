from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


def uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_principal(conn: PgConnection, organization_id: UUID) -> UUID:
    return uuid_row(
        conn,
        "INSERT INTO request_engine.principals "
        "(organization_id,principal_kind,external_subject) "
        "VALUES (%s,'human',%s) RETURNING id",
        (organization_id, f"customer-{uuid4().hex}"),
    )


def create_representation(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
) -> UUID:
    return uuid_row(
        conn,
        "INSERT INTO request_engine.representations "
        "(organization_id,principal_id,represented_party_id,authority_kind,scope_key,"
        "valid_from,valid_until) VALUES (%s,%s,%s,'self','queue.manage',"
        "clock_timestamp()-interval '1 minute',clock_timestamp()+interval '1 day') "
        "RETURNING id",
        (organization_id, principal_id, party_id),
    )
