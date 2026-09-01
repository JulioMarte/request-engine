"""Realistic tenancy world for the S0b party registry PostgreSQL proofs.

Only valid prerequisites are created with direct SQL: one organization, one
human operator principal and one bot (intermediary) principal. Parties,
contact points and identity documents are never seeded here: they are the
durable outcomes of the real `parties.*` commands under test.
"""

from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class PartyRegistryWorld:
    organization_id: UUID
    operator_principal_id: UUID
    bot_principal_id: UUID


def _uuid_row(
    conn: PgConnection,
    statement: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_party_registry_world(conn: PgConnection, *, prefix: str) -> PartyRegistryWorld:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.organizations (organization_key, display_name)"
        " VALUES (%s, %s) RETURNING id",
        (f"{prefix}-{suffix}", f"{prefix} clinic {suffix[:8]}"),
    )
    operator_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals (organization_id, principal_kind,"
        " external_subject) VALUES (%s, 'human', %s) RETURNING id",
        (organization_id, f"front-desk-{suffix}"),
    )
    bot_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals (organization_id, principal_kind,"
        " external_subject) VALUES (%s, 'integration', %s) RETURNING id",
        (organization_id, f"chatwoot-bot-{suffix}"),
    )
    return PartyRegistryWorld(organization_id, operator_id, bot_id)


def create_tenant_principal(conn: PgConnection, organization_id: UUID, subject: str) -> UUID:
    return _uuid_row(
        conn,
        "INSERT INTO request_engine.principals (organization_id, principal_kind,"
        " external_subject) VALUES (%s, 'human', %s) RETURNING id",
        (organization_id, subject),
    )
