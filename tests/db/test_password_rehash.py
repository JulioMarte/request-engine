"""Opportunistic Argon2id rehash on legacy scrypt login (plan §13)."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    hash_password_scrypt,
    verify_password,
)

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

PASSWORD = "legacy password that is long enough"


def _legacy_identity(admin_conn: PgConnection) -> tuple[UUID, str]:
    authority_id = uuid4()
    identity_id = uuid4()
    login_handle = f"legacy-{uuid4().hex}@example.test"
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"argon2-proof-{uuid4().hex}"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities(id, identity_authority_id, login_handle) "
        "VALUES (%s, %s, %s)",
        (identity_id, authority_id, login_handle),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_credentials "
        "(id, native_identity_id, verifier) VALUES (%s, %s, %s)",
        (uuid4(), identity_id, hash_password_scrypt(PASSWORD)),
    )
    return authority_id, login_handle


def _verifier(admin_conn: PgConnection, *, login_handle: str) -> str:
    row = admin_conn.execute(
        "SELECT credential.verifier FROM request_engine.native_credentials AS credential "
        "JOIN request_engine.native_identities AS identity "
        "ON identity.id = credential.native_identity_id "
        "WHERE identity.login_handle = %s",
        (login_handle,),
    ).fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.asyncio
async def test_successful_legacy_login_upgrades_verifier_in_place(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id, login_handle = _legacy_identity(admin_conn)
    before = _verifier(admin_conn, login_handle=login_handle)
    assert before.startswith("scrypt$")

    issued = await build_native_auth_runtime(command_session_factory).service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )

    after = _verifier(admin_conn, login_handle=login_handle)
    assert after.startswith("$argon2id$")
    assert verify_password(PASSWORD, after) is True
    # The upgrade is transparent: the same session was issued and the credential
    # id / revision are unchanged.
    assert issued.native_identity_id is not None
    assert admin_conn.execute(
        "SELECT credential.revision, credential.status "
        "FROM request_engine.native_credentials AS credential "
        "JOIN request_engine.native_identities AS identity "
        "ON identity.id = credential.native_identity_id "
        "WHERE identity.login_handle = %s",
        (login_handle,),
    ).fetchone() == (1, "active")


@pytest.mark.asyncio
async def test_failed_legacy_login_does_not_rehash(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id, login_handle = _legacy_identity(admin_conn)
    before = _verifier(admin_conn, login_handle=login_handle)

    with pytest.raises(CredentialInvalid):
        await build_native_auth_runtime(command_session_factory).service.authenticate_password(
            identity_authority_id=authority_id,
            login_handle=login_handle,
            password="not the right password",
        )

    assert _verifier(admin_conn, login_handle=login_handle) == before


@pytest.mark.asyncio
async def test_current_verifier_is_not_rehashed_again(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id, login_handle = _legacy_identity(admin_conn)
    runtime = build_native_auth_runtime(command_session_factory)
    await runtime.service.authenticate_password(
        identity_authority_id=authority_id, login_handle=login_handle, password=PASSWORD
    )
    upgraded = _verifier(admin_conn, login_handle=login_handle)
    assert upgraded.startswith("$argon2id$")

    await runtime.service.authenticate_password(
        identity_authority_id=authority_id, login_handle=login_handle, password=PASSWORD
    )
    assert _verifier(admin_conn, login_handle=login_handle) == upgraded


def test_rehash_function_rejects_non_argon2_verifier(
    admin_conn: PgConnection,
    app_role_conn: Connection[Any],
) -> None:
    _authority_id, login_handle = _legacy_identity(admin_conn)
    row = admin_conn.execute(
        "SELECT credential.id, credential.native_identity_id "
        "FROM request_engine.native_credentials AS credential "
        "JOIN request_engine.native_identities AS identity "
        "ON identity.id = credential.native_identity_id "
        "WHERE identity.login_handle = %s",
        (login_handle,),
    ).fetchone()
    assert row is not None
    credential_id, identity_id = row
    assert app_role_conn.execute(
        "SELECT request_auth.rehash_native_password_verifier(%s, %s, %s)",
        (credential_id, identity_id, "scrypt$not-an-upgrade"),
    ).fetchone() == (False,)


def test_rehash_function_is_least_privilege(admin_conn: PgConnection) -> None:
    row = admin_conn.execute(
        """
        SELECT pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig,
               has_function_privilege('request_engine_app', p.oid, 'EXECUTE'),
               EXISTS (
                   SELECT 1 FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))
                    WHERE grantee = 0 AND privilege_type = 'EXECUTE'
               )
          FROM pg_proc p
         WHERE p.oid = to_regprocedure(
             'request_auth.rehash_native_password_verifier(uuid, uuid, text)'
         )
        """
    ).fetchone()
    assert row is not None
    assert row[0:2] == ("request_engine_schema_owner", True)
    assert row[2] == ["search_path=pg_catalog, request_engine"]
    assert row[3] is True
    assert row[4] is False
