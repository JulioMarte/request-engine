"""WebAuthn credential and challenge persistence proofs (ADR 0014 P2)."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.db.webauthn_store import PostgresWebAuthnStore

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
]


async def _enroll_identity(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    *,
    login_handle: str,
) -> tuple[UUID, UUID]:
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"webauthn-proof-{uuid4().hex}"),
    )
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password="webauthn proof password",
    )
    return authority_id, enrollment.native_identity_id


@pytest.mark.asyncio
async def test_challenge_is_single_use(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    _, identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-one@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    digest = secrets.token_bytes(32)
    assert await store.create_challenge(
        challenge_id=uuid4(),
        purpose="registration",
        challenge_digest=digest,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        native_identity_id=identity_id,
    )

    scope = await store.consume_challenge(challenge_digest=digest, purpose="registration")
    assert scope is not None
    assert scope.native_identity_id == identity_id
    assert scope.session_id is None

    assert await store.consume_challenge(challenge_digest=digest, purpose="registration") is None


@pytest.mark.asyncio
async def test_expired_challenge_is_not_consumable(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    _, identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-expired@example.test"
    )
    digest = secrets.token_bytes(32)
    now = datetime.now(UTC)
    admin_conn.execute(
        "INSERT INTO request_engine.webauthn_challenges "
        "(id, purpose, native_identity_id, challenge_digest, created_at, expires_at) "
        "VALUES (%s, 'registration', %s, %s, %s, %s)",
        (uuid4(), identity_id, digest, now - timedelta(minutes=2), now - timedelta(minutes=1)),
    )
    store = PostgresWebAuthnStore(command_session_factory)
    assert await store.consume_challenge(challenge_digest=digest, purpose="registration") is None


@pytest.mark.asyncio
async def test_scope_requires_exactly_one_owner(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    _, identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-scope@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    expires = datetime.now(UTC) + timedelta(minutes=5)
    assert not await store.create_challenge(
        challenge_id=uuid4(),
        purpose="registration",
        challenge_digest=secrets.token_bytes(32),
        expires_at=expires,
    )
    assert not await store.create_challenge(
        challenge_id=uuid4(),
        purpose="registration",
        challenge_digest=secrets.token_bytes(32),
        expires_at=expires,
        native_identity_id=identity_id,
        session_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_register_and_read_credential(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    _, identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-register@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    credential_id = secrets.token_bytes(32)
    public_key = secrets.token_bytes(77)
    row_id = uuid4()
    assert await store.register_credential(
        credential_row_id=row_id,
        native_identity_id=identity_id,
        credential_id=credential_id,
        public_key=public_key,
        sign_count=0,
        aaguid="00" * 16,
        backup_eligible=True,
        backup_state=False,
        user_verified=True,
    )
    records = await store.read_credentials(native_identity_id=identity_id)
    assert len(records) == 1
    record = records[0]
    assert record.id == row_id
    assert record.credential_id == credential_id
    assert record.public_key == public_key
    assert record.aaguid == "00" * 16
    assert record.backup_eligible is True
    assert record.user_verified is True
    assert record.status == "active"


@pytest.mark.asyncio
async def test_credential_id_binds_to_at_most_one_identity(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    _, first = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-first@example.test"
    )
    _, second = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-second@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    credential_id = secrets.token_bytes(32)

    assert await store.register_credential(
        credential_row_id=uuid4(),
        native_identity_id=first,
        credential_id=credential_id,
        public_key=secrets.token_bytes(77),
        sign_count=0,
        aaguid="00" * 16,
        backup_eligible=False,
        backup_state=False,
        user_verified=True,
    )
    assert not await store.register_credential(
        credential_row_id=uuid4(),
        native_identity_id=second,
        credential_id=credential_id,
        public_key=secrets.token_bytes(77),
        sign_count=0,
        aaguid="00" * 16,
        backup_eligible=False,
        backup_state=False,
        user_verified=True,
    )
    assert await store.read_credentials(native_identity_id=second) == ()


@pytest.mark.asyncio
async def test_sign_count_update_and_revocation(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    _, identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-sign@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    row_id = uuid4()
    assert await store.register_credential(
        credential_row_id=row_id,
        native_identity_id=identity_id,
        credential_id=secrets.token_bytes(32),
        public_key=secrets.token_bytes(77),
        sign_count=0,
        aaguid="00" * 16,
        backup_eligible=False,
        backup_state=False,
        user_verified=True,
    )
    assert await store.update_sign_count(
        credential_row_id=row_id, native_identity_id=identity_id, new_sign_count=4
    )
    record = (await store.read_credentials(native_identity_id=identity_id))[0]
    assert record.sign_count == 4

    assert await store.revoke_credential(
        credential_row_id=row_id, native_identity_id=identity_id, reason="user_removed"
    )
    record = (await store.read_credentials(native_identity_id=identity_id))[0]
    assert record.status == "revoked"
    assert not await store.update_sign_count(
        credential_row_id=row_id, native_identity_id=identity_id, new_sign_count=5
    )


@pytest.mark.asyncio
async def test_disabling_identity_revokes_webauthn_credentials(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    _, identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-disable@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    assert await store.register_credential(
        credential_row_id=uuid4(),
        native_identity_id=identity_id,
        credential_id=secrets.token_bytes(32),
        public_key=secrets.token_bytes(77),
        sign_count=0,
        aaguid="00" * 16,
        backup_eligible=False,
        backup_state=False,
        user_verified=True,
    )
    admin_conn.execute(
        "SELECT request_auth.disable_native_identity(%s, %s)",
        (identity_id, "global_disable_proof"),
    )
    record = (await store.read_credentials(native_identity_id=identity_id))[0]
    assert record.status == "revoked"


def test_webauthn_tables_are_not_directly_readable(admin_conn: PgConnection) -> None:
    for table in (
        "request_engine.webauthn_credentials",
        "request_engine.webauthn_challenges",
    ):
        assert admin_conn.execute(
            "SELECT has_table_privilege('request_engine_app', %s, 'SELECT')", (table,)
        ).fetchone() == (False,)
