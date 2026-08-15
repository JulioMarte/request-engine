from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]


def _organization(conn: PgConnection, label: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"function-isolation-{label}-{uuid4().hex}", f"Function isolation {label}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _principal(conn: PgConnection, organization_id: UUID, label: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"function-principal-{label}-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _app_connection(pg_conninfo: str, organization_id: UUID) -> PgConnection:
    conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    conn.execute("SET ROLE request_engine_app")
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    return conn


def _acquire_idempotency(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    key: str,
) -> UUID:
    row = conn.execute(
        """
        SELECT idempotency_id
        FROM request_cmd.acquire_idempotency(%s, %s, %s, %s, %s)
        """,
        (organization_id, principal_id, "test.function", key, "fingerprint-v1"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.postgres
def test_tenant_scoped_idempotency_function_rejects_foreign_organization_context(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _organization(admin_conn, "a")
    tenant_b = _organization(admin_conn, "b")
    principal_a = _principal(admin_conn, tenant_a, "a")
    principal_b = _principal(admin_conn, tenant_b, "b")

    app_a = _app_connection(pg_conninfo, tenant_a)
    try:
        own_id = _acquire_idempotency(
            app_a,
            organization_id=tenant_a,
            principal_id=principal_a,
            key=f"own-{uuid4().hex}",
        )
        assert own_id is not None

        with pytest.raises(Error) as foreign_context:
            _acquire_idempotency(
                app_a,
                organization_id=tenant_b,
                principal_id=principal_b,
                key=f"foreign-{uuid4().hex}",
            )
        assert foreign_context.value.sqlstate == "42501"

        with pytest.raises(Error) as nonexistent_context:
            _acquire_idempotency(
                app_a,
                organization_id=uuid4(),
                principal_id=uuid4(),
                key=f"nonexistent-{uuid4().hex}",
            )
        assert nonexistent_context.value.sqlstate == "42501"
    finally:
        app_a.close()


@pytest.mark.postgres
def test_complete_idempotency_hides_foreign_records_like_nonexistent_records(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    tenant_a = _organization(admin_conn, "complete-a")
    tenant_b = _organization(admin_conn, "complete-b")
    principal_a = _principal(admin_conn, tenant_a, "complete-a")
    principal_b = _principal(admin_conn, tenant_b, "complete-b")

    app_a = _app_connection(pg_conninfo, tenant_a)
    app_b = _app_connection(pg_conninfo, tenant_b)
    try:
        own_id = _acquire_idempotency(
            app_a,
            organization_id=tenant_a,
            principal_id=principal_a,
            key=f"complete-own-{uuid4().hex}",
        )
        foreign_id = _acquire_idempotency(
            app_b,
            organization_id=tenant_b,
            principal_id=principal_b,
            key=f"complete-foreign-{uuid4().hex}",
        )

        assert app_a.execute(
            "SELECT request_cmd.complete_idempotency(%s, '{}'::jsonb)",
            (own_id,),
        ).fetchone() == (True,)
        assert app_a.execute(
            "SELECT request_cmd.complete_idempotency(%s, '{}'::jsonb)",
            (foreign_id,),
        ).fetchone() == (False,)
        assert app_a.execute(
            "SELECT request_cmd.complete_idempotency(%s, '{}'::jsonb)",
            (uuid4(),),
        ).fetchone() == (False,)
        assert (
            app_a.execute(
                "SELECT id FROM request_engine.idempotency_records WHERE id = %s",
                (foreign_id,),
            ).fetchall()
            == []
        )
    finally:
        app_a.close()
        app_b.close()

    foreign_state = admin_conn.execute(
        """
        SELECT status, result_data
        FROM request_engine.idempotency_records
        WHERE id = %s
        """,
        (foreign_id,),
    ).fetchone()
    assert foreign_state == ("in_progress", None)
