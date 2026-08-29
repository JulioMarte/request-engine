from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class TenantFixture:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID
    representation_id: UUID


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_tenant_fixture(
    conn: PgConnection,
    *,
    scope_key: str = "appointments.manage",
) -> TenantFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"adversarial-{suffix}", f"Adversarial {suffix}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"principal-{suffix}"),
    )
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Party {suffix}"),
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
            valid_from,
            valid_until
        ) VALUES (
            %s, %s, %s, 'guardian', %s,
            clock_timestamp() - interval '1 minute',
            clock_timestamp() + interval '1 day'
        )
        RETURNING id
        """,
        (organization_id, principal_id, party_id, scope_key),
    )
    return TenantFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        representation_id=representation_id,
    )


def _set_app_context(conn: PgConnection, organization_id: UUID | None) -> None:
    conn.execute("SET ROLE request_engine_app")
    if organization_id is not None:
        conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )


def _app_connection(pg_conninfo: str, organization_id: UUID) -> PgConnection:
    conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    _set_app_context(conn, organization_id)
    return conn


def _resolve_authority(
    conn: PgConnection,
    fixture: TenantFixture,
    *,
    organization_id: UUID | None = None,
    principal_id: UUID | None = None,
    party_id: UUID | None = None,
    scope_key: str = "appointments.manage",
) -> list[tuple[Any, ...]]:
    return conn.execute(
        """
        SELECT representation_id, authority_kind
        FROM request_engine.resolve_current_party_authority(%s, %s, %s, %s)
        """,
        (
            organization_id or fixture.organization_id,
            principal_id or fixture.principal_id,
            party_id or fixture.party_id,
            scope_key,
        ),
    ).fetchall()


@pytest.mark.postgres
def test_every_tenant_table_has_rls_policy_and_runtime_roles_cannot_bypass_rls(
    admin_conn: PgConnection,
) -> None:
    runtime_roles = admin_conn.execute(
        """
        SELECT rolname, rolbypassrls
        FROM pg_roles
        WHERE rolname IN ('request_engine_app', 'request_engine_worker')
        ORDER BY rolname
        """
    ).fetchall()
    assert runtime_roles == [
        ("request_engine_app", False),
        ("request_engine_worker", False),
    ]

    tables = admin_conn.execute(
        """
        SELECT c.relname, c.relrowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_engine'
          AND c.relkind = 'r'
          AND EXISTS (
              SELECT 1
              FROM pg_attribute a
              WHERE a.attrelid = c.oid
                AND a.attname = 'organization_id'
                AND NOT a.attisdropped
          )
        ORDER BY c.relname
        """
    ).fetchall()
    assert tables

    def _bound(qual: str | None, wc: str | None) -> bool:
        tenant = "current_organization_id()" in (qual or "")
        return tenant and (wc is None or "current_organization_id()" in wc)

    policies: dict[str, list[tuple[str | None, str | None, set[str]]]] = {}
    for table_name, qual, wc, roles in admin_conn.execute(
        "SELECT tablename, qual, with_check AS wc, roles FROM pg_policies"
        " WHERE schemaname = 'request_engine' ORDER BY tablename"
    ).fetchall():
        row = (qual, wc, {str(role) for role in roles})
        policies.setdefault(cast(str, table_name), []).append(row)

    violations: list[str] = []
    for table_name, rls_enabled in tables:
        name = cast(str, table_name)
        if not rls_enabled:
            violations.append(f"{name}: RLS disabled")
            continue
        if not any(_bound(qual, wc) for qual, wc, _roles in policies.get(name, [])):
            violations.append(f"{name}: missing tenant policy")
            continue
        for qual, wc, roles in policies.get(name, []):
            runtime_exposed = roles & {"request_engine_app", "request_engine_worker", "public"}
            if runtime_exposed and not _bound(qual, wc):
                violations.append(f"{name}: runtime policy is not tenant-bound")

    assert not violations, "Tenant RLS catalog violations:\n" + "\n".join(violations)


@pytest.mark.postgres
def test_app_role_fails_closed_and_cannot_read_or_mutate_foreign_tenant_rows(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _create_tenant_fixture(admin_conn)
    tenant_b = _create_tenant_fixture(admin_conn)

    no_context: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        _set_app_context(no_context, None)
        assert no_context.execute(
            "SELECT count(*) FROM request_engine.organizations"
        ).fetchone() == (0,)
        assert no_context.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (
            0,
        )
        assert no_context.execute("SELECT count(*) FROM request_engine.parties").fetchone() == (0,)
        assert no_context.execute(
            "SELECT count(*) FROM request_engine.representations"
        ).fetchone() == (0,)
        with pytest.raises(Error) as missing_context_error:
            no_context.execute(
                """
                INSERT INTO request_engine.principals (
                    organization_id, principal_kind, external_subject
                ) VALUES (%s, 'human', %s)
                """,
                (tenant_a.organization_id, f"missing-context-{uuid4().hex}"),
            )
        assert missing_context_error.value.sqlstate == "42501"
    finally:
        no_context.close()

    app_a = _app_connection(pg_conninfo, tenant_a.organization_id)
    try:
        assert app_a.execute(
            "SELECT id FROM request_engine.organizations ORDER BY id"
        ).fetchall() == [(tenant_a.organization_id,)]
        assert app_a.execute("SELECT id FROM request_engine.principals ORDER BY id").fetchall() == [
            (tenant_a.principal_id,)
        ]
        assert app_a.execute("SELECT id FROM request_engine.parties ORDER BY id").fetchall() == [
            (tenant_a.party_id,)
        ]
        assert app_a.execute(
            "SELECT id FROM request_engine.representations ORDER BY id"
        ).fetchall() == [(tenant_a.representation_id,)]

        foreign_lookup = app_a.execute(
            "SELECT id FROM request_engine.principals WHERE id = %s",
            (tenant_b.principal_id,),
        ).fetchall()
        nonexistent_lookup = app_a.execute(
            "SELECT id FROM request_engine.principals WHERE id = %s",
            (uuid4(),),
        ).fetchall()
        assert foreign_lookup == nonexistent_lookup == []

        update_cursor = app_a.execute(
            "UPDATE request_engine.principals SET active = false WHERE id = %s",
            (tenant_b.principal_id,),
        )
        assert update_cursor.rowcount == 0

        with pytest.raises(Error) as foreign_insert_error:
            app_a.execute(
                """
                INSERT INTO request_engine.principals (
                    organization_id, principal_kind, external_subject
                ) VALUES (%s, 'human', %s)
                """,
                (tenant_b.organization_id, f"cross-tenant-{uuid4().hex}"),
            )
        assert foreign_insert_error.value.sqlstate == "42501"
    finally:
        app_a.close()

    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s",
        (tenant_b.principal_id,),
    ).fetchone() == (True,)


@pytest.mark.postgres
def test_security_invoker_read_surface_does_not_bypass_tenant_rls(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _create_tenant_fixture(admin_conn)
    tenant_b = _create_tenant_fixture(admin_conn)

    view_options = admin_conn.execute(
        """
        SELECT c.relname, COALESCE(c.reloptions, ARRAY[]::text[])
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'request_read'
          AND c.relkind = 'v'
        ORDER BY c.relname
        """
    ).fetchall()
    assert view_options
    assert all("security_invoker=true" in options for _, options in view_options)

    app_a = _app_connection(pg_conninfo, tenant_a.organization_id)
    try:
        business_rows = app_a.execute(
            """
            SELECT organization_id
            FROM request_read.business_info_v1
            ORDER BY organization_id
            """
        ).fetchall()
        assert business_rows == [(tenant_a.organization_id,)]
        assert (
            app_a.execute(
                """
                SELECT organization_id
                FROM request_read.business_info_v1
                WHERE organization_id = %s
                """,
                (tenant_b.organization_id,),
            ).fetchall()
            == []
        )
    finally:
        app_a.close()


@pytest.mark.postgres
def test_authority_resolution_hides_foreign_and_nonexistent_identifiers_equally(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _create_tenant_fixture(admin_conn)
    tenant_b = _create_tenant_fixture(admin_conn)

    app_a = _app_connection(pg_conninfo, tenant_a.organization_id)
    try:
        own = _resolve_authority(app_a, tenant_a)
        assert own == [(tenant_a.representation_id, "guardian")]

        foreign_tenant = _resolve_authority(
            app_a,
            tenant_b,
            organization_id=tenant_b.organization_id,
        )
        foreign_party = _resolve_authority(
            app_a,
            tenant_a,
            party_id=tenant_b.party_id,
        )
        nonexistent = _resolve_authority(
            app_a,
            tenant_a,
            principal_id=uuid4(),
            party_id=uuid4(),
        )
        wrong_scope = _resolve_authority(app_a, tenant_a, scope_key="queue.manage")

        assert foreign_tenant == nonexistent == []
        assert foreign_party == []
        assert wrong_scope == []
    finally:
        app_a.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_representation_revocation_serializes_with_authority_lock(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant = _create_tenant_fixture(admin_conn)
    command_conn = _app_connection(pg_conninfo, tenant.organization_id)
    revoke_conn = _app_connection(pg_conninfo, tenant.organization_id)
    command_conn.autocommit = False
    revoke_conn.autocommit = False

    try:
        locked = command_conn.execute(
            """
            SELECT representation_id
            FROM request_engine.lock_current_party_authority(%s, %s, %s, %s)
            """,
            (
                tenant.organization_id,
                tenant.principal_id,
                tenant.party_id,
                "appointments.manage",
            ),
        ).fetchall()
        assert locked == [(tenant.representation_id,)]

        revoke_conn.execute("SET LOCAL lock_timeout = '250ms'")
        with pytest.raises(Error) as blocked_revoke:
            revoke_conn.execute(
                """
                UPDATE request_engine.representations
                SET status = 'revoked'
                WHERE id = %s
                """,
                (tenant.representation_id,),
            )
        assert blocked_revoke.value.sqlstate == "55P03"
        revoke_conn.rollback()

        command_conn.commit()

        updated = revoke_conn.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked'
            WHERE id = %s
            """,
            (tenant.representation_id,),
        )
        assert updated.rowcount == 1
        revoke_conn.commit()

        assert _resolve_authority(command_conn, tenant) == []
        command_conn.commit()
    finally:
        command_conn.close()
        revoke_conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
def test_revocation_that_wins_first_blocks_new_authority_acquisition(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant = _create_tenant_fixture(admin_conn)
    revoke_conn = _app_connection(pg_conninfo, tenant.organization_id)
    command_conn = _app_connection(pg_conninfo, tenant.organization_id)
    revoke_conn.autocommit = False
    command_conn.autocommit = False

    try:
        updated = revoke_conn.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked'
            WHERE id = %s
            """,
            (tenant.representation_id,),
        )
        assert updated.rowcount == 1

        command_conn.execute("SET LOCAL lock_timeout = '250ms'")
        with pytest.raises(Error) as blocked_command:
            command_conn.execute(
                """
                SELECT representation_id
                FROM request_engine.lock_current_party_authority(%s, %s, %s, %s)
                """,
                (
                    tenant.organization_id,
                    tenant.principal_id,
                    tenant.party_id,
                    "appointments.manage",
                ),
            )
        assert blocked_command.value.sqlstate == "55P03"
        command_conn.rollback()

        revoke_conn.commit()

        assert _resolve_authority(command_conn, tenant) == []
        command_conn.commit()
    finally:
        revoke_conn.close()
        command_conn.close()


@pytest.mark.postgres
@pytest.mark.parametrize("endpoint", ["principal", "party"])
def test_inactive_authority_endpoint_invalidates_representation(
    admin_conn: PgConnection,
    pg_conninfo: str,
    endpoint: str,
) -> None:
    tenant = _create_tenant_fixture(admin_conn)
    app_conn = _app_connection(pg_conninfo, tenant.organization_id)
    try:
        assert _resolve_authority(app_conn, tenant) == [(tenant.representation_id, "guardian")]
        if endpoint == "principal":
            assert (
                app_conn.execute(
                    "UPDATE request_engine.principals SET active = false WHERE id = %s",
                    (tenant.principal_id,),
                ).rowcount
                == 1
            )
        else:
            assert (
                app_conn.execute(
                    "UPDATE request_engine.parties SET active = false WHERE id = %s",
                    (tenant.party_id,),
                ).rowcount
                == 1
            )
        assert _resolve_authority(app_conn, tenant) == []
    finally:
        app_conn.close()
