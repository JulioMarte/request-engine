"""Independent concurrent Native sessions for one native identity.

Protects ``INV-NATIVE-MULTI-SESSION-001`` with real PostgreSQL:

- one native identity may hold several concurrent active sessions; each
  authenticates independently;
- revoking one session leaves the others authenticating;
- a global invalidation (``revoke_native_sessions`` or password rotation) bumps
  the identity session epoch and invalidates every outstanding session;
- each session carries its own activity and authentication timestamps.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.native_session_toucher import PostgresNativeSessionToucher
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import SessionTokenInvalid
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.integration,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "replacement correct horse battery staple"


def _insert_authority(admin_conn: Any) -> UUID:
    authority_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (
            id, kind, issuer_or_environment
        ) VALUES (%s, 'native', %s)
        """,
        (authority_id, f"multi-session:{authority_id}"),
    )
    return authority_id


def _session_rows(admin_conn: Any, identity_id: UUID) -> list[tuple[Any, ...]]:
    return admin_conn.execute(
        """
        SELECT id, status, last_seen_at, last_authenticated_at
          FROM request_engine.native_sessions
         WHERE native_identity_id = %s
         ORDER BY id
        """,
        (identity_id,),
    ).fetchall()


@pytest.mark.asyncio
async def test_concurrent_native_sessions_authenticate_and_revoke_independently(
    admin_conn: Any,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = _insert_authority(admin_conn)
    login_handle = f"multi-session-{uuid4().hex}@example.test"
    store = PostgresNativeHumanAuthStore(command_session_factory)
    service = NativeHumanAuthService(store=store, clock=lambda: datetime.now(UTC))
    authenticator = NativeSessionAuthenticator(
        session_reader=PostgresNativeSessionReader(command_session_factory),
        session_toucher=PostgresNativeSessionToucher(command_session_factory),
    )

    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    session_a = await service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    session_b = await service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    assert session_a.session_id != session_b.session_id

    subject_a = await authenticator.authenticate(NativeSessionEvidence(session_a.raw_token))
    subject_b = await authenticator.authenticate(NativeSessionEvidence(session_b.raw_token))
    assert subject_a.subject_id == str(enrollment.native_identity_id)
    assert subject_b.subject_id == str(enrollment.native_identity_id)

    rows = _session_rows(admin_conn, enrollment.native_identity_id)
    assert len(rows) == 2
    assert {str(row[1]) for row in rows} == {"active"}
    assert all(row[2] is not None for row in rows)
    assert all(row[3] is not None for row in rows)
    assert {row[0] for row in rows} == {session_a.session_id, session_b.session_id}

    # Revoking one session leaves the other authenticating.
    await service.revoke_session(
        native_identity_id=enrollment.native_identity_id,
        session_id=session_a.session_id,
    )
    with pytest.raises(SessionTokenInvalid):
        await authenticator.authenticate(NativeSessionEvidence(session_a.raw_token))
    assert (
        await authenticator.authenticate(NativeSessionEvidence(session_b.raw_token))
    ).subject_id == str(enrollment.native_identity_id)

    # A global epoch bump invalidates every outstanding session.
    await service.revoke_all_sessions(native_identity_id=enrollment.native_identity_id)
    with pytest.raises(SessionTokenInvalid):
        await authenticator.authenticate(NativeSessionEvidence(session_b.raw_token))
    epoch = admin_conn.execute(
        "SELECT session_epoch FROM request_engine.native_identities WHERE id = %s",
        (enrollment.native_identity_id,),
    ).fetchone()
    assert epoch == (2,)


@pytest.mark.asyncio
async def test_password_rotation_invalidates_every_concurrent_session(
    admin_conn: Any,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = _insert_authority(admin_conn)
    login_handle = f"multi-session-rotate-{uuid4().hex}@example.test"
    store = PostgresNativeHumanAuthStore(command_session_factory)
    service = NativeHumanAuthService(store=store, clock=lambda: datetime.now(UTC))
    authenticator = NativeSessionAuthenticator(
        session_reader=PostgresNativeSessionReader(command_session_factory),
    )

    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    session_a = await service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    session_b = await service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    await authenticator.authenticate(NativeSessionEvidence(session_a.raw_token))
    await authenticator.authenticate(NativeSessionEvidence(session_b.raw_token))

    await service.rotate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        current_password=PASSWORD,
        new_password=NEW_PASSWORD,
    )

    with pytest.raises(SessionTokenInvalid):
        await authenticator.authenticate(NativeSessionEvidence(session_a.raw_token))
    with pytest.raises(SessionTokenInvalid):
        await authenticator.authenticate(NativeSessionEvidence(session_b.raw_token))
    epoch = admin_conn.execute(
        "SELECT session_epoch FROM request_engine.native_identities WHERE id = %s",
        (enrollment.native_identity_id,),
    ).fetchone()
    assert epoch == (2,)
