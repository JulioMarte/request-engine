from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"authority-{suffix}", f"Authority {suffix}"),
    )


def _principal(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"principal-{uuid4().hex}"),
    )


def _party(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Party {uuid4().hex}"),
    )


@pytest.mark.postgres
def test_every_tenant_local_foreign_key_carries_organization_id(
    admin_conn: PgConnection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT
            c.conname,
            src.relname AS source_table,
            dst.relname AS target_table,
            EXISTS (
                SELECT 1
                FROM pg_attribute a
                WHERE a.attrelid = c.conrelid
                  AND a.attname = 'organization_id'
                  AND NOT a.attisdropped
            ) AS source_is_tenant_owned,
            EXISTS (
                SELECT 1
                FROM pg_attribute a
                WHERE a.attrelid = c.confrelid
                  AND a.attname = 'organization_id'
                  AND NOT a.attisdropped
            ) AS target_is_tenant_owned,
            ARRAY(
                SELECT a.attname
                FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid
                 AND a.attnum = k.attnum
                ORDER BY k.ord
            ) AS source_columns,
            ARRAY(
                SELECT a.attname
                FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                JOIN pg_attribute a
                  ON a.attrelid = c.confrelid
                 AND a.attnum = k.attnum
                ORDER BY k.ord
            ) AS target_columns
        FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_class dst ON dst.oid = c.confrelid
        JOIN pg_namespace n ON n.oid = src.relnamespace
        WHERE c.contype = 'f'
          AND n.nspname = 'request_engine'
        ORDER BY src.relname, c.conname
        """
    ).fetchall()

    violations: list[str] = []
    for row in rows:
        (
            constraint_name,
            source_table,
            target_table,
            source_is_tenant_owned,
            target_is_tenant_owned,
            source_columns,
            target_columns,
        ) = row
        if not source_is_tenant_owned or not target_is_tenant_owned:
            continue
        if target_table == "organizations":
            continue
        if "organization_id" not in source_columns or "organization_id" not in target_columns:
            violations.append(
                f"{source_table}.{constraint_name} -> {target_table}: "
                f"{source_columns} -> {target_columns}"
            )

    assert not violations, "Tenant-local FK can cross Organization boundary:\n" + "\n".join(
        violations
    )


@pytest.mark.postgres
def test_representation_has_explicit_provenance_and_no_persisted_expired_state(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    principal_id = _principal(admin_conn, organization_id)
    party_id = _party(admin_conn, organization_id)

    representation_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            authority_kind,
            scope_key,
            valid_until
        ) VALUES (
            %s, %s, %s, 'guardian', 'appointments.manage',
            clock_timestamp() + interval '1 day'
        )
        RETURNING id
        """,
        (organization_id, principal_id, party_id),
    )
    assert representation_id

    with pytest.raises(Error) as expired_error:
        admin_conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, status
            ) VALUES (%s, %s, %s, 'delegated', 'appointments.manage', 'expired')
            """,
            (organization_id, principal_id, party_id),
        )
    assert expired_error.value.sqlstate == "23514"

    with pytest.raises(Error) as kind_error:
        admin_conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key
            ) VALUES (%s, %s, %s, 'staff', 'appointments.manage')
            """,
            (organization_id, principal_id, party_id),
        )
    assert kind_error.value.sqlstate == "23514"


@pytest.mark.postgres
def test_representation_cannot_cross_tenant_boundary(admin_conn: PgConnection) -> None:
    organization_a = _organization(admin_conn)
    organization_b = _organization(admin_conn)
    principal_a = _principal(admin_conn, organization_a)
    party_b = _party(admin_conn, organization_b)

    with pytest.raises(Error) as exc_info:
        admin_conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key
            ) VALUES (%s, %s, %s, 'delegated', 'appointments.manage')
            """,
            (organization_a, principal_a, party_b),
        )
    assert exc_info.value.sqlstate == "23503"


@pytest.mark.postgres
def test_current_representation_is_derived_from_status_and_database_time(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    principal_id = _principal(admin_conn, organization_id)
    party_id = _party(admin_conn, organization_id)

    def insert_window(
        scope: str,
        status: str,
        from_delta: str,
        until_delta: str | None,
    ) -> UUID:
        return _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, status, valid_from, valid_until
            ) VALUES (
                %s, %s, %s, 'delegated', %s, %s,
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
                scope,
                status,
                from_delta,
                until_delta,
                until_delta,
            ),
        )

    current_id = insert_window("appointments.manage", "active", "-1 hour", "1 hour")
    insert_window("queue.manage", "active", "1 hour", "2 hours")
    insert_window("requests.submit", "active", "-2 hours", "-1 hour")
    insert_window("reminders.manage", "revoked", "-1 hour", None)

    rows = admin_conn.execute(
        """
        SELECT r.id
        FROM request_engine.representations r
        JOIN request_engine.principals p
          ON p.organization_id = r.organization_id
         AND p.id = r.principal_id
        JOIN request_engine.parties party
          ON party.organization_id = r.organization_id
         AND party.id = r.represented_party_id
        CROSS JOIN LATERAL (SELECT clock_timestamp() AS db_now) clock
        WHERE r.organization_id = %s
          AND r.principal_id = %s
          AND r.represented_party_id = %s
          AND r.scope_key = 'appointments.manage'
          AND r.status = 'active'
          AND p.active
          AND party.active
          AND r.valid_from <= clock.db_now
          AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
        """,
        (organization_id, principal_id, party_id),
    ).fetchall()

    assert rows == [(current_id,)]
