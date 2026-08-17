from dataclasses import dataclass
from typing import Any, Literal, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

PgConnection = Connection[Any]
AuthorityState = Literal[
    "future",
    "expired",
    "revoked",
    "inactive_principal",
    "inactive_party",
    "wrong_scope",
    "wrong_party",
]


@dataclass(frozen=True, slots=True)
class AuthorityCase:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    representation_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _case(
    conn: PgConnection,
    *,
    status: str = "active",
    valid_from: str = "-1 minute",
    valid_until: str | None = "1 day",
    principal_active: bool = True,
    party_active: bool = True,
) -> AuthorityCase:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"authority-state-{suffix}", f"Authority State {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject, active
        ) VALUES (%s, 'human', %s, %s)
        RETURNING id
        """,
        (organization_id, f"principal-{suffix}", principal_active),
    )
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name, active
        ) VALUES (%s, 'person', %s, %s)
        RETURNING id
        """,
        (organization_id, f"Party {suffix}", party_active),
    )
    representation_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            authority_kind,
            scope_key,
            status,
            valid_from,
            valid_until
        ) VALUES (
            %s, %s, %s, 'delegated', 'appointments.manage', %s,
            clock_timestamp() + %s::interval,
            CASE
                WHEN %s::text IS NULL THEN NULL
                ELSE clock_timestamp() + %s::interval
            END
        )
        RETURNING id
        """,
        (
            organization_id,
            principal_id,
            party_id,
            status,
            valid_from,
            valid_until,
            valid_until,
        ),
    )
    return AuthorityCase(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        representation_id=representation_id,
    )


def _app_connection(pg_conninfo: str, organization_id: UUID) -> PgConnection:
    conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    conn.execute("SET ROLE request_engine_app")
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    return conn


def _resolve_rows(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    scope_key: str,
) -> list[tuple[Any, ...]]:
    return conn.execute(
        """
        SELECT representation_id, authority_kind
        FROM request_engine.resolve_current_party_authority(%s, %s, %s, %s)
        """,
        (organization_id, principal_id, party_id, scope_key),
    ).fetchall()


def _lock_rows(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    scope_key: str,
) -> list[tuple[Any, ...]]:
    return conn.execute(
        """
        SELECT representation_id, authority_kind
        FROM request_engine.lock_current_party_authority(%s, %s, %s, %s)
        """,
        (organization_id, principal_id, party_id, scope_key),
    ).fetchall()


def _invalid_case(admin_conn: PgConnection, state: AuthorityState) -> AuthorityCase:
    if state == "future":
        return _case(admin_conn, valid_from="1 hour", valid_until="2 hours")
    if state == "expired":
        return _case(admin_conn, valid_from="-2 hours", valid_until="-1 hour")
    if state == "revoked":
        return _case(admin_conn, status="revoked", valid_until=None)
    if state == "inactive_principal":
        return _case(admin_conn, principal_active=False)
    if state == "inactive_party":
        return _case(admin_conn, party_active=False)
    return _case(admin_conn)


@pytest.mark.postgres
@pytest.mark.parametrize(
    "state",
    [
        "future",
        "expired",
        "revoked",
        "inactive_principal",
        "inactive_party",
        "wrong_scope",
        "wrong_party",
    ],
)
def test_invalid_party_authority_states_fail_closed_for_read_and_lock_primitives(
    admin_conn: PgConnection,
    pg_conninfo: str,
    state: AuthorityState,
) -> None:
    case = _invalid_case(admin_conn, state)
    lookup_party_id = case.party_id
    lookup_scope = "appointments.manage"
    if state == "wrong_scope":
        lookup_scope = "appointments.book"
    elif state == "wrong_party":
        lookup_party_id = _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.parties (
                organization_id, party_kind, display_name
            ) VALUES (%s, 'person', %s)
            RETURNING id
            """,
            (case.organization_id, f"Wrong Party {uuid4().hex}"),
        )

    app_conn = _app_connection(pg_conninfo, case.organization_id)
    try:
        assert _resolve_rows(
            app_conn,
            organization_id=case.organization_id,
            principal_id=case.principal_id,
            party_id=lookup_party_id,
            scope_key=lookup_scope,
        ) == []
        assert _lock_rows(
            app_conn,
            organization_id=case.organization_id,
            principal_id=case.principal_id,
            party_id=lookup_party_id,
            scope_key=lookup_scope,
        ) == []
    finally:
        app_conn.close()


@pytest.mark.postgres
def test_current_exact_scope_party_authority_is_visible_to_both_primitives(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    case = _case(admin_conn)
    app_conn = _app_connection(pg_conninfo, case.organization_id)
    try:
        expected = [(case.representation_id, "delegated")]
        assert _resolve_rows(
            app_conn,
            organization_id=case.organization_id,
            principal_id=case.principal_id,
            party_id=case.party_id,
            scope_key="appointments.manage",
        ) == expected
        assert _lock_rows(
            app_conn,
            organization_id=case.organization_id,
            principal_id=case.principal_id,
            party_id=case.party_id,
            scope_key="appointments.manage",
        ) == expected
    finally:
        app_conn.close()
