"""Native-session reauthentication freshness at the PostgreSQL auth boundary.

Real PostgreSQL 18. The session is created through the accepted
``request_auth.create_native_session`` boundary; reauthentication is exercised
directly through ``request_auth.reauthenticate_native_session`` under the real
app role. The guard regression and the absent-verifier path are independent
negative proofs.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import insert_authority
from psycopg import Connection, Error

from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.native_human_auth import NativeHumanAuthService

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

_PASSWORD = "correct horse battery staple"


async def _enroll(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> tuple[UUID, UUID, UUID, str]:
    authority_id = insert_authority(admin_conn)
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(session_factory))
    login_handle = f"reauth-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=_PASSWORD,
    )
    return authority_id, enrollment.native_identity_id, enrollment.credential_id, login_handle


def _create_session(
    app_role_conn: PgConnection,
    *,
    native_identity_id: UUID,
    credential_id: UUID,
) -> UUID:
    token = issue_opaque_token()
    row = app_role_conn.execute(
        """
        SELECT request_auth.create_native_session(
            %(native_identity_id)s,
            %(credential_id)s,
            %(session_id)s,
            %(token_digest)s,
            %(token_fingerprint)s,
            %(expires_at)s
        )
        """,
        {
            "native_identity_id": native_identity_id,
            "credential_id": credential_id,
            "session_id": token.token_id,
            "token_digest": token.digest,
            "token_fingerprint": token.fingerprint,
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        },
    ).fetchone()
    app_role_conn.commit()
    assert row == (True,)
    return token.token_id


def _reauth(
    app_role_conn: PgConnection,
    *,
    session_id: UUID,
    credential_id: UUID,
) -> object:
    row = app_role_conn.execute(
        "SELECT request_auth.reauthenticate_native_session(%s, %s)",
        (session_id, credential_id),
    ).fetchone()
    app_role_conn.commit()
    assert row is not None
    return row[0]


@pytest.mark.asyncio
async def test_native_session_reauth_advances_freshness_and_is_fail_closed(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    _authority_id, native_identity_id, credential_id, _handle = await _enroll(
        admin_conn, command_session_factory
    )
    session_id = _create_session(
        app_role_conn,
        native_identity_id=native_identity_id,
        credential_id=credential_id,
    )
    reader = PostgresNativeSessionReader(command_session_factory)

    initial = await reader.read_native_session(session_id=session_id)
    assert initial is not None
    assert initial.password_credential_id == credential_id
    assert initial.authenticated_at == initial.created_at
    assert initial.last_seen_at is None

    await asyncio.sleep(0.01)
    advanced = _reauth(
        app_role_conn,
        session_id=session_id,
        credential_id=credential_id,
    )
    assert isinstance(advanced, datetime)
    assert advanced > initial.created_at

    refreshed = await reader.read_native_session(session_id=session_id)
    assert refreshed is not None
    assert refreshed.authenticated_at == advanced
    assert refreshed.last_seen_at is not None

    assert admin_conn.execute(
        "SELECT last_authenticated_at, last_seen_at IS NOT NULL "
        "FROM request_engine.native_sessions WHERE id = %s",
        (session_id,),
    ).fetchone() == (advanced, True)


@pytest.mark.asyncio
async def test_native_session_reauth_rejects_wrong_credential_and_revoked_session(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    _authority_id, native_identity_id, credential_id, _handle = await _enroll(
        admin_conn, command_session_factory
    )
    session_id = _create_session(
        app_role_conn,
        native_identity_id=native_identity_id,
        credential_id=credential_id,
    )
    before = admin_conn.execute(
        "SELECT last_authenticated_at FROM request_engine.native_sessions WHERE id = %s",
        (session_id,),
    ).fetchone()
    assert before is not None

    assert _reauth(app_role_conn, session_id=session_id, credential_id=uuid4()) is None
    assert (
        admin_conn.execute(
            "SELECT last_authenticated_at FROM request_engine.native_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()
        == before
    )

    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    await service.revoke_session(
        native_identity_id=native_identity_id,
        session_id=session_id,
        reason="reauth_probe",
    )
    assert _reauth(app_role_conn, session_id=session_id, credential_id=credential_id) is None
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_sessions WHERE id = %s",
        (session_id,),
    ).fetchone() == ("revoked",)


@pytest.mark.asyncio
async def test_native_session_reauth_cannot_regress_last_authenticated_at(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    _authority_id, native_identity_id, credential_id, _handle = await _enroll(
        admin_conn, command_session_factory
    )
    session_id = _create_session(
        app_role_conn,
        native_identity_id=native_identity_id,
        credential_id=credential_id,
    )
    await asyncio.sleep(0.01)
    advanced = _reauth(app_role_conn, session_id=session_id, credential_id=credential_id)

    with pytest.raises(Error) as regression:
        admin_conn.execute(
            """
            UPDATE request_engine.native_sessions
               SET last_authenticated_at = created_at
             WHERE id = %s
            """,
            (session_id,),
        )
    assert regression.value.sqlstate == "55000"
    assert admin_conn.execute(
        "SELECT last_authenticated_at FROM request_engine.native_sessions WHERE id = %s",
        (session_id,),
    ).fetchone() == (advanced,)


def test_native_credential_verifier_reads_only_active_password_verifiers(
    admin_conn: PgConnection,
    app_role_conn: PgConnection,
) -> None:
    authority_id = insert_authority(admin_conn)
    identity_id = uuid4()
    credential_id = uuid4()
    verifier = "scrypt$" + ("a" * 64)
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"verifier-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_credentials "
        "(id, native_identity_id, verifier) VALUES (%s, %s, %s)",
        (credential_id, identity_id, verifier),
    )

    row = app_role_conn.execute(
        "SELECT request_auth.read_native_credential_verifier(%s)",
        (credential_id,),
    ).fetchone()
    app_role_conn.rollback()
    assert row == (verifier,)

    missing = app_role_conn.execute(
        "SELECT request_auth.read_native_credential_verifier(%s)",
        (uuid4(),),
    ).fetchone()
    app_role_conn.rollback()
    assert missing == (None,)
