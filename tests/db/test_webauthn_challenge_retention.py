"""Real PostgreSQL retention, replay-window, and privilege proofs."""

import os
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy.engine import URL

from request_engine.platform.db.webauthn_challenge_retention import run_retention_pass

PgConnection = Connection[Any]
_CALLER_ROLE = "request_webauthn_retention"
_DEFINER_ROLE = "request_webauthn_retention_definer"
_FUNCTION = "request_auth.delete_retained_webauthn_challenges(integer,integer)"
_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def _challenge(
    conn: PgConnection,
    *,
    status: str,
    expires_at: datetime,
    consumed_at: datetime | None = None,
) -> UUID:
    challenge_id = uuid4()
    authority_id = uuid4()
    identity_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.identity_authorities "
        "(id,kind,issuer_or_environment) VALUES (%s,'native',%s)",
        (authority_id, f"challenge-retention-{uuid4().hex}"),
    )
    conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id,identity_authority_id,login_handle) VALUES (%s,%s,%s)",
        (identity_id, authority_id, f"{uuid4().hex}@example.test"),
    )
    conn.execute(
        "INSERT INTO request_engine.webauthn_challenges "
        "(id,purpose,native_identity_id,challenge_digest,status,created_at,expires_at,consumed_at) "
        "VALUES (%s,'authentication',%s,%s,%s,%s,%s,%s)",
        (
            challenge_id,
            identity_id,
            secrets.token_bytes(32),
            status,
            expires_at - timedelta(minutes=5),
            expires_at,
            consumed_at,
        ),
    )
    return challenge_id


def _run_batch(conn: PgConnection, retention_seconds: int = 604800, batch_size: int = 1000) -> int:
    with conn.transaction():
        conn.execute(f"SET LOCAL ROLE {_CALLER_ROLE}")
        row = conn.execute(
            "SELECT request_auth.delete_retained_webauthn_challenges(%s,%s)",
            (retention_seconds, batch_size),
        ).fetchone()
        assert row is not None
        return int(row[0])


@pytest.mark.postgres
def test_retention_deletes_only_old_terminal_or_expired_pending_challenges(
    admin_conn: PgConnection,
) -> None:
    now = datetime.now(UTC)
    old_consumed = _challenge(
        admin_conn,
        status="consumed",
        expires_at=now - timedelta(days=10),
        consumed_at=now - timedelta(days=8),
    )
    old_expired = _challenge(admin_conn, status="expired", expires_at=now - timedelta(days=8))
    old_pending_expired = _challenge(
        admin_conn, status="pending", expires_at=now - timedelta(days=8)
    )
    recent_expired = _challenge(admin_conn, status="expired", expires_at=now - timedelta(days=2))
    recent_consumed = _challenge(
        admin_conn,
        status="consumed",
        expires_at=now - timedelta(days=10),
        consumed_at=now - timedelta(days=2),
    )
    live_pending = _challenge(admin_conn, status="pending", expires_at=now + timedelta(hours=1))
    digest_row = admin_conn.execute(
        "SELECT challenge_digest FROM request_engine.webauthn_challenges WHERE id=%s",
        (old_consumed,),
    ).fetchone()
    assert digest_row is not None
    consumed_digest: bytes = bytes(digest_row[0])
    credentials_row = admin_conn.execute(
        "SELECT count(*) FROM request_engine.webauthn_credentials"
    ).fetchone()
    assert credentials_row is not None
    credentials_before = int(credentials_row[0])

    assert _run_batch(admin_conn) == 3
    remaining = {
        UUID(str(row[0]))
        for row in admin_conn.execute(
            "SELECT id FROM request_engine.webauthn_challenges"
        ).fetchall()
    }
    assert remaining == {recent_expired, recent_consumed, live_pending}
    assert old_consumed not in remaining
    assert old_expired not in remaining
    assert old_pending_expired not in remaining
    assert admin_conn.execute(
        "SELECT request_auth.finalize_webauthn_registration(%s,%s,%s,%s,0,%s,false,false,true)",
        (consumed_digest, uuid4(), secrets.token_bytes(32), secrets.token_bytes(77), "00" * 16),
    ).fetchone() == (False,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.webauthn_credentials"
    ).fetchone() == (credentials_before,)
    assert _run_batch(admin_conn) == 0


@pytest.mark.postgres
def test_retention_deletes_no_more_than_configured_batch_size(
    admin_conn: PgConnection,
) -> None:
    now = datetime.now(UTC)
    eligible = {
        _challenge(admin_conn, status="expired", expires_at=now - timedelta(days=10))
        for _ in range(2)
    }
    assert _run_batch(admin_conn, batch_size=1) == 1
    remaining = {
        UUID(str(row[0]))
        for row in admin_conn.execute(
            "SELECT id FROM request_engine.webauthn_challenges WHERE id = ANY(%s)",
            (list(eligible),),
        ).fetchall()
    }
    assert len(remaining) == 1
    assert _run_batch(admin_conn, batch_size=1) == 1
    assert _run_batch(admin_conn, batch_size=1) == 0


@pytest.mark.postgres
def test_invalid_retention_configuration_rolls_back_before_deletion(
    admin_conn: PgConnection,
) -> None:
    eligible = _challenge(
        admin_conn, status="expired", expires_at=datetime.now(UTC) - timedelta(days=10)
    )
    admin_conn.execute("BEGIN")
    try:
        admin_conn.execute(f"SET LOCAL ROLE {_CALLER_ROLE}")
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            admin_conn.execute(
                "SELECT request_auth.delete_retained_webauthn_challenges(%s,%s)",
                (86399, 1000),
            )
    finally:
        admin_conn.execute("ROLLBACK")
    assert admin_conn.execute(
        "SELECT status FROM request_engine.webauthn_challenges WHERE id=%s", (eligible,)
    ).fetchone() == ("expired",)


@pytest.mark.postgres
def test_app_cannot_execute_or_directly_delete_retained_challenges(
    app_role_conn: PgConnection,
) -> None:
    with app_role_conn.transaction():
        app_role_conn.execute("SET LOCAL ROLE request_engine_app")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), app_role_conn.transaction():
            app_role_conn.execute(
                "SELECT request_auth.delete_retained_webauthn_challenges(604800,1)"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), app_role_conn.transaction():
            app_role_conn.execute("DELETE FROM request_engine.webauthn_challenges WHERE false")


@pytest.mark.postgres
def test_retention_roles_have_only_function_and_required_column_authority(
    admin_conn: PgConnection,
) -> None:
    roles = admin_conn.execute(
        "SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole "
        "FROM pg_roles WHERE rolname = ANY(%s)",
        ([_CALLER_ROLE, _DEFINER_ROLE],),
    ).fetchall()
    assert set(roles) == {
        (_CALLER_ROLE, False, False, False, False, False),
        (_DEFINER_ROLE, False, False, False, False, False),
    }
    assert admin_conn.execute(
        "SELECT has_function_privilege(%s,%s,'EXECUTE'), "
        "has_function_privilege('request_engine_app',%s,'EXECUTE'), "
        "has_function_privilege('request_engine_worker',%s,'EXECUTE')",
        (_CALLER_ROLE, _FUNCTION, _FUNCTION, _FUNCTION),
    ).fetchone() == (True, False, False)
    assert admin_conn.execute(
        "SELECT NOT EXISTS (SELECT 1 FROM pg_proc p "
        "CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl, "
        "acldefault('f',p.proowner))) acl "
        "WHERE p.oid=%s::regprocedure AND acl.grantee=0 AND acl.privilege_type='EXECUTE')",
        (_FUNCTION,),
    ).fetchone() == (True,)
    assert admin_conn.execute(
        "SELECT has_table_privilege(%s,'request_engine.webauthn_challenges','DELETE'), "
        "has_any_column_privilege(%s,'request_engine.webauthn_challenges','SELECT'), "
        "has_table_privilege(%s,'request_engine.webauthn_challenges','DELETE')",
        (_CALLER_ROLE, _CALLER_ROLE, _DEFINER_ROLE),
    ).fetchone() == (False, False, True)
    definer_select = {
        (str(column), str(privilege))
        for column, privilege in admin_conn.execute(
            "SELECT a.attname, acl.privilege_type FROM pg_attribute a "
            "JOIN pg_class c ON c.oid=a.attrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "CROSS JOIN LATERAL aclexplode(a.attacl) acl "
            "WHERE n.nspname='request_engine' AND c.relname='webauthn_challenges' "
            "AND acl.grantee=(SELECT oid FROM pg_roles WHERE rolname=%s)",
            (_DEFINER_ROLE,),
        ).fetchall()
    }
    assert definer_select == {
        ("id", "SELECT"),
        ("id", "UPDATE"),
        ("status", "SELECT"),
        ("expires_at", "SELECT"),
        ("consumed_at", "SELECT"),
    }


@pytest.mark.postgres
def test_retention_skips_a_challenge_locked_by_another_transaction(
    admin_conn: PgConnection, pg_conninfo: str
) -> None:
    eligible = _challenge(
        admin_conn, status="expired", expires_at=datetime.now(UTC) - timedelta(days=10)
    )
    locker = psycopg.connect(pg_conninfo)
    cleaner = psycopg.connect(pg_conninfo)
    try:
        locker.execute(
            "SELECT id FROM request_engine.webauthn_challenges WHERE id=%s FOR UPDATE", (eligible,)
        )
        with cleaner.transaction():
            assert _run_batch(cleaner) == 0
        assert admin_conn.execute(
            "SELECT 1 FROM request_engine.webauthn_challenges WHERE id=%s", (eligible,)
        ).fetchone() == (1,)
        locker.rollback()
        with cleaner.transaction():
            assert _run_batch(cleaner) == 1
    finally:
        locker.close()
        cleaner.close()


@pytest.mark.postgres
def test_challenge_table_has_no_dependent_foreign_keys(admin_conn: PgConnection) -> None:
    assert admin_conn.execute(
        "SELECT count(*) FROM pg_constraint WHERE contype='f' "
        "AND confrelid='request_engine.webauthn_challenges'::regclass"
    ).fetchone() == (0,)


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("grantee", "object_name"),
    [
        (_CALLER_ROLE, "request_engine.native_sessions"),
        (_DEFINER_ROLE, "request_engine.webauthn_challenges"),
    ],
)
def test_upgrade_rejects_unexpected_shared_role_acl_without_rewriting_it(
    admin_conn: PgConnection,
    pg_conninfo: str,
    grantee: str,
    object_name: str,
) -> None:
    """A fresh database must not silently adopt cluster roles with extra ACLs."""

    database = f"re_webauthn_retention_acl_{uuid4().hex}"
    config = make_conninfo(pg_conninfo, dbname="postgres")
    with psycopg.connect(config, autocommit=True) as cluster_admin:
        cluster_admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    database_conninfo = make_conninfo(pg_conninfo, dbname=database)
    try:
        database_config = conninfo_to_dict(database_conninfo)
        migration_url = URL.create(
            "postgresql+psycopg",
            username=str(database_config["user"]),
            password=str(database_config["password"]),
            host=str(database_config["host"]),
            port=int(str(database_config["port"])),
            database=database,
        ).render_as_string(hide_password=False)
        environment = {**os.environ, "MIGRATION_DATABASE_URL": migration_url}
        baseline_upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0036_webauthn_deadline"],
            cwd=_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert baseline_upgrade.returncode == 0, baseline_upgrade.stdout + baseline_upgrade.stderr
        with psycopg.connect(database_conninfo, autocommit=True) as isolated:
            isolated.execute(
                sql.SQL("GRANT SELECT ON {} TO {}").format(
                    sql.Identifier(*object_name.split(".")), sql.Identifier(grantee)
                )
            )
        failed_upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert failed_upgrade.returncode != 0
        assert "unexpected direct ACLs" in failed_upgrade.stderr
        with psycopg.connect(database_conninfo) as isolated:
            assert isolated.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0036_webauthn_deadline",
            )
            assert isolated.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT')", (grantee, object_name)
            ).fetchone() == (True,)
            assert isolated.execute(
                "SELECT to_regclass('request_engine.webauthn_challenges_retention_scan_idx'), "
                "to_regprocedure(%s)",
                (_FUNCTION,),
            ).fetchone() == (None, None)
    finally:
        with psycopg.connect(config, autocommit=True) as cluster_admin:
            cluster_admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
            )


@pytest.mark.postgres
def test_cli_uses_only_a_dedicated_login_with_explicit_role_membership(
    admin_conn: PgConnection, pg_conninfo: str
) -> None:
    eligible = _challenge(
        admin_conn, status="expired", expires_at=datetime.now(UTC) - timedelta(days=10)
    )
    role_name = f"re_webauthn_retention_{uuid4().hex[:12]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(
        sql.SQL(
            "GRANT request_webauthn_retention TO {} WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
        ).format(sql.Identifier(role_name))
    )
    try:
        assert (
            run_retention_pass(
                make_conninfo(pg_conninfo, user=role_name, password=password),
                retention_seconds=604800,
                batch_size=100,
            )
            == 1
        )
    finally:
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
    assert (
        admin_conn.execute(
            "SELECT 1 FROM request_engine.webauthn_challenges WHERE id=%s", (eligible,)
        ).fetchone()
        is None
    )


@pytest.mark.postgres
@pytest.mark.parametrize("unsafe_membership", ["superuser", "additional_role"])
def test_cli_rejects_elevated_or_multi_role_maintenance_logins(
    admin_conn: PgConnection,
    pg_conninfo: str,
    unsafe_membership: str,
) -> None:
    eligible = _challenge(
        admin_conn, status="expired", expires_at=datetime.now(UTC) - timedelta(days=10)
    )
    role_name = f"re_webauthn_unsafe_{uuid4().hex[:12]}"
    password = uuid4().hex
    elevated = unsafe_membership == "superuser"
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT {} NOBYPASSRLS "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(
            sql.Identifier(role_name),
            sql.SQL("SUPERUSER") if elevated else sql.SQL("NOSUPERUSER"),
            sql.Literal(password),
        )
    )
    admin_conn.execute(
        sql.SQL(
            "GRANT request_webauthn_retention TO {} WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
        ).format(sql.Identifier(role_name))
    )
    if unsafe_membership == "additional_role":
        admin_conn.execute(
            sql.SQL(
                "GRANT request_engine_app TO {} WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
            ).format(sql.Identifier(role_name))
        )
    try:
        with pytest.raises(PermissionError, match="dedicated non-inheriting login"):
            run_retention_pass(
                make_conninfo(pg_conninfo, user=role_name, password=password),
                retention_seconds=604800,
                batch_size=100,
            )
    finally:
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
    assert admin_conn.execute(
        "SELECT 1 FROM request_engine.webauthn_challenges WHERE id=%s", (eligible,)
    ).fetchone() == (1,)
