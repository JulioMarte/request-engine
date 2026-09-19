"""WebAuthn credential/challenge persistence and ceremony proofs (ADR 0014 P2)."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.db.webauthn_store import PostgresWebAuthnStore
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
    SessionRevoked,
)
from request_engine.platform.security.native_webauthn_auth import (
    NativeWebAuthnAuthService,
    WebAuthnCeremonyError,
)
from request_engine.platform.security.webauthn import WebAuthnPolicy

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
]

RP_ID = "localhost"
ORIGIN = "http://localhost:8000"
PASSWORD = "webauthn proof password"


def _policy() -> WebAuthnPolicy:
    return WebAuthnPolicy(
        rp_id=RP_ID,
        rp_name="Request Engine",
        allowed_origins=frozenset({ORIGIN}),
        user_verification_required=True,
    )


def _service(store: PostgresWebAuthnStore) -> NativeWebAuthnAuthService:
    return NativeWebAuthnAuthService(policy=_policy(), store=store)


async def _enroll_identity(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    *,
    login_handle: str,
) -> UUID:
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
        password=PASSWORD,
    )
    return enrollment.native_identity_id


def _insert_credential(admin_conn: PgConnection, identity_id: UUID) -> tuple[UUID, bytes]:
    row_id = uuid4()
    credential_id = secrets.token_bytes(32)
    admin_conn.execute(
        "INSERT INTO request_engine.webauthn_credentials "
        "(id, native_identity_id, credential_id, public_key, sign_count, aaguid, "
        " backup_eligible, backup_state, user_verified) "
        "VALUES (%s, %s, %s, %s, 0, %s, false, false, true)",
        (row_id, identity_id, credential_id, secrets.token_bytes(77), "00" * 16),
    )
    return row_id, credential_id


async def _register_passkey(
    store: PostgresWebAuthnStore,
    service: NativeWebAuthnAuthService,
    identity_id: UUID,
    authenticator: SoftwareAuthenticator,
) -> UUID:
    options = await service.begin_registration(native_identity_id=identity_id)
    credential = authenticator.registration_credential(challenge=options.challenge)
    return await service.complete_registration(credential=credential)


async def _issue_passkey_session(
    store: PostgresWebAuthnStore,
    service: NativeWebAuthnAuthService,
    identity_id: UUID,
    authenticator: SoftwareAuthenticator,
) -> str:
    options = await service.begin_authentication(native_identity_id=identity_id)
    assertion = authenticator.authentication_credential(challenge=options.challenge)
    issued = await service.complete_authentication(
        native_identity_id=identity_id, credential=assertion
    )
    return issued.raw_token


def _session_authenticator(session_factory: SessionFactory) -> NativeSessionAuthenticator:
    return NativeSessionAuthenticator(session_reader=PostgresNativeSessionReader(session_factory))


@pytest.mark.asyncio
async def test_challenge_is_single_use_and_finalization_is_atomic(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-atomic@example.test"
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
    credential_id = secrets.token_bytes(32)
    row_id = uuid4()
    public_key = secrets.token_bytes(77)

    async def _finalize() -> bool:
        return await store.finalize_registration(
            challenge_digest=digest,
            credential_row_id=row_id,
            credential_id=credential_id,
            public_key=public_key,
            sign_count=0,
            aaguid="00" * 16,
            backup_eligible=False,
            backup_state=False,
            user_verified=True,
        )

    assert await _finalize()
    # The challenge is consumed exactly once; the loser writes nothing.
    assert not await _finalize()
    records = await store.read_credentials(native_identity_id=identity_id)
    assert [record.id for record in records] == [row_id]
    assert await store.read_challenge(challenge_digest=digest, purpose="registration") is None


@pytest.mark.asyncio
async def test_expired_challenge_cannot_be_finalized(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
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
    assert await store.read_challenge(challenge_digest=digest, purpose="registration") is None
    assert not await store.finalize_registration(
        challenge_digest=digest,
        credential_row_id=uuid4(),
        credential_id=secrets.token_bytes(32),
        public_key=secrets.token_bytes(77),
        sign_count=0,
        aaguid="00" * 16,
        backup_eligible=False,
        backup_state=False,
        user_verified=True,
    )


@pytest.mark.asyncio
async def test_scope_requires_exactly_one_owner(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
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
    assert not await store.create_challenge(
        challenge_id=uuid4(),
        purpose="registration",
        challenge_digest=secrets.token_bytes(32),
        expires_at=expires,
        native_identity_id=identity_id,
        setup_session_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_credential_id_binds_to_at_most_one_identity(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    first = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-first@example.test"
    )
    second = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-second@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    credential_id = secrets.token_bytes(32)

    async def _finalize(identity_id: UUID) -> bool:
        digest = secrets.token_bytes(32)
        assert await store.create_challenge(
            challenge_id=uuid4(),
            purpose="registration",
            challenge_digest=digest,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            native_identity_id=identity_id,
        )
        return await store.finalize_registration(
            challenge_digest=digest,
            credential_row_id=uuid4(),
            credential_id=credential_id,
            public_key=secrets.token_bytes(77),
            sign_count=0,
            aaguid="00" * 16,
            backup_eligible=False,
            backup_state=False,
            user_verified=True,
        )

    assert await _finalize(first)
    assert not await _finalize(second)
    assert await store.read_credentials(native_identity_id=second) == ()


@pytest.mark.asyncio
async def test_sign_count_is_a_race_safe_high_water_mark(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-sign@example.test"
    )
    row_id, _credential_id = _insert_credential(admin_conn, identity_id)
    store = PostgresWebAuthnStore(command_session_factory)

    async def _authenticate(sign_count: int) -> bool:
        digest = secrets.token_bytes(32)
        assert await store.create_challenge(
            challenge_id=uuid4(),
            purpose="authentication",
            challenge_digest=digest,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            native_identity_id=identity_id,
        )
        token = issue_opaque_token()
        return await store.finalize_authentication(
            challenge_digest=digest,
            credential_row_id=row_id,
            native_identity_id=identity_id,
            sign_count=sign_count,
            backup_eligible=False,
            backup_state=False,
            user_verified=True,
            session_id=token.token_id,
            token_digest=token.digest,
            token_fingerprint=token.fingerprint,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    assert await _authenticate(4)
    # An out-of-order older assertion must never lower the stored high-water mark.
    assert await _authenticate(2)
    assert (await store.read_credentials(native_identity_id=identity_id))[0].sign_count == 4
    assert await _authenticate(6)
    assert (await store.read_credentials(native_identity_id=identity_id))[0].sign_count == 6


@pytest.mark.asyncio
async def test_revoked_credential_cannot_authenticate(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-revoked@example.test"
    )
    row_id, _credential_id = _insert_credential(admin_conn, identity_id)
    store = PostgresWebAuthnStore(command_session_factory)
    assert await store.revoke_credential(
        credential_row_id=row_id, native_identity_id=identity_id, reason="user_removed"
    )
    digest = secrets.token_bytes(32)
    assert await store.create_challenge(
        challenge_id=uuid4(),
        purpose="authentication",
        challenge_digest=digest,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        native_identity_id=identity_id,
    )
    token = issue_opaque_token()
    assert not await store.finalize_authentication(
        challenge_digest=digest,
        credential_row_id=row_id,
        native_identity_id=identity_id,
        sign_count=1,
        backup_eligible=False,
        backup_state=False,
        user_verified=True,
        session_id=token.token_id,
        token_digest=token.digest,
        token_fingerprint=token.fingerprint,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_passkey_ceremony_issues_phishing_resistant_session(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-login@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    service = _service(store)
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    await _register_passkey(store, service, identity_id, authenticator)

    raw_token = await _issue_passkey_session(store, service, identity_id, authenticator)
    subject = await _session_authenticator(command_session_factory).authenticate(
        NativeSessionEvidence(raw_token)
    )

    assert subject.metadata["authentication_assurance"] == (
        AuthenticationAssurance.PHISHING_RESISTANT.value
    )
    assert subject.metadata["authentication_methods"] == "webauthn"
    assert subject.metadata["user_verified"] == "true"
    assert subject.metadata["recovery_derived"] == "false"


@pytest.mark.asyncio
async def test_password_session_is_only_single_factor(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"webauthn-proof-{uuid4().hex}"),
    )
    runtime = build_native_auth_runtime(command_session_factory)
    enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle="password-session@example.test",
        password=PASSWORD,
    )
    issued = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=enrollment.login_handle,
        password=PASSWORD,
    )
    subject = await _session_authenticator(command_session_factory).authenticate(
        NativeSessionEvidence(issued.raw_token)
    )
    assert subject.metadata["authentication_assurance"] == (
        AuthenticationAssurance.SINGLE_FACTOR.value
    )
    assert subject.metadata["user_verified"] == "false"


@pytest.mark.asyncio
async def test_step_up_upgrades_password_session_to_phishing_resistant(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"webauthn-proof-{uuid4().hex}"),
    )
    runtime = build_native_auth_runtime(command_session_factory)
    enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle="step-up@example.test",
        password=PASSWORD,
    )
    identity_id = enrollment.native_identity_id
    store = PostgresWebAuthnStore(command_session_factory)
    service = _service(store)
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    await _register_passkey(store, service, identity_id, authenticator)

    issued = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=enrollment.login_handle,
        password=PASSWORD,
    )
    options = await service.begin_step_up(session_id=issued.session_id)
    assertion = authenticator.authentication_credential(challenge=options.challenge)
    await service.complete_step_up(
        session_id=issued.session_id,
        native_identity_id=identity_id,
        credential=assertion,
    )

    subject = await _session_authenticator(command_session_factory).authenticate(
        NativeSessionEvidence(issued.raw_token)
    )
    assert subject.metadata["authentication_assurance"] == (
        AuthenticationAssurance.PHISHING_RESISTANT.value
    )
    assert set(subject.metadata["authentication_methods"].split(",")) == {
        "password",
        "webauthn",
    }


@pytest.mark.asyncio
async def test_recovery_derived_session_cannot_escape_recovery_by_step_up(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    """A recovery-derived session stays RECOVERY even after a valid WebAuthn step-up."""

    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"webauthn-proof-{uuid4().hex}"),
    )
    runtime = build_native_auth_runtime(command_session_factory)
    enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle="recovery-step-up@example.test",
        password=PASSWORD,
    )
    identity_id = enrollment.native_identity_id
    store = PostgresWebAuthnStore(command_session_factory)
    service = _service(store)
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    await _register_passkey(store, service, identity_id, authenticator)

    # Valid precondition: a recovery-code-derived session (recovery reset the
    # password). Direct SQL creates only the state under test, not the outcome.
    session_id = uuid4()
    token = issue_opaque_token(token_id=session_id)
    admin_conn.execute(
        "INSERT INTO request_engine.native_sessions "
        "(id, native_identity_id, password_credential_id, token_digest, token_fingerprint, "
        " session_epoch, authentication_methods, authentication_assurance, user_verified, "
        " recovery_derived, expires_at) "
        "SELECT %s, i.id, %s, %s, %s, i.session_epoch, ARRAY['recovery_code'], 'recovery', "
        "false, true, clock_timestamp() + interval '1 hour' "
        "FROM request_engine.native_identities i WHERE i.id = %s",
        (session_id, enrollment.credential_id, token.digest, token.fingerprint, identity_id),
    )

    options = await service.begin_step_up(session_id=session_id)
    assertion = authenticator.authentication_credential(challenge=options.challenge)
    await service.complete_step_up(
        session_id=session_id,
        native_identity_id=identity_id,
        credential=assertion,
    )

    subject = await _session_authenticator(command_session_factory).authenticate(
        NativeSessionEvidence(token.raw_token)
    )
    assert subject.metadata["authentication_assurance"] == AuthenticationAssurance.RECOVERY.value
    assert subject.metadata["recovery_derived"] == "true"
    assert "webauthn" in subject.metadata["authentication_methods"]


@pytest.mark.asyncio
async def test_step_up_then_revoke_invalidates_stepped_up_session(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    """Revoking the proving credential must remove step-up-derived assurance."""

    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"webauthn-proof-{uuid4().hex}"),
    )
    runtime = build_native_auth_runtime(command_session_factory)
    enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle="step-up-revoke@example.test",
        password=PASSWORD,
    )
    identity_id = enrollment.native_identity_id
    store = PostgresWebAuthnStore(command_session_factory)
    service = _service(store)
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    credential_row_id = await _register_passkey(store, service, identity_id, authenticator)

    issued = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=enrollment.login_handle,
        password=PASSWORD,
    )
    options = await service.begin_step_up(session_id=issued.session_id)
    assertion = authenticator.authentication_credential(challenge=options.challenge)
    await service.complete_step_up(
        session_id=issued.session_id,
        native_identity_id=identity_id,
        credential=assertion,
    )

    assert await store.revoke_credential(
        credential_row_id=credential_row_id,
        native_identity_id=identity_id,
        reason="compromise",
    )
    with pytest.raises(SessionRevoked):
        await _session_authenticator(command_session_factory).authenticate(
            NativeSessionEvidence(issued.raw_token)
        )


@pytest.mark.asyncio
async def test_suspended_authority_cannot_register_credential(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
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
        login_handle="suspended-register@example.test",
        password=PASSWORD,
    )
    identity_id = enrollment.native_identity_id
    store = PostgresWebAuthnStore(command_session_factory)
    service = _service(store)
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    options = await service.begin_registration(native_identity_id=identity_id)
    credential = authenticator.registration_credential(challenge=options.challenge)

    admin_conn.execute(
        "UPDATE request_engine.identity_authorities "
        "SET status = 'disabled', revision = revision + 1 WHERE id = %s",
        (authority_id,),
    )
    with pytest.raises(WebAuthnCeremonyError):
        await service.complete_registration(credential=credential)
    assert await store.read_credentials(native_identity_id=identity_id) == ()


_LEAST_PRIVILEGE_FUNCTIONS = (
    "create_webauthn_challenge(uuid, text, uuid, uuid, uuid, bytea, timestamptz)",
    "read_webauthn_challenge(bytea, text)",
    "read_webauthn_credential(bytea)",
    "read_webauthn_credentials(uuid)",
    "read_active_webauthn_identity(uuid, text)",
    (
        "finalize_webauthn_registration(bytea, uuid, bytea, bytea, bigint, text, "
        "boolean, boolean, boolean)"
    ),
    (
        "finalize_webauthn_authentication(bytea, uuid, uuid, bigint, boolean, boolean, "
        "boolean, uuid, bytea, text, timestamptz)"
    ),
    "finalize_webauthn_step_up(bytea, uuid, uuid, uuid, bigint, boolean, boolean)",
    "revoke_webauthn_credential(uuid, uuid, text)",
)


def test_webauthn_functions_are_least_privilege(admin_conn: PgConnection) -> None:
    for signature in _LEAST_PRIVILEGE_FUNCTIONS:
        row = admin_conn.execute(
            """
            SELECT pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig,
                   has_function_privilege('request_engine_app', p.oid, 'EXECUTE'),
                   EXISTS (
                       SELECT 1 FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner)))
                        WHERE grantee = 0 AND privilege_type = 'EXECUTE'
                   )
              FROM pg_proc p WHERE p.oid = to_regprocedure(%s)
            """,
            (f"request_auth.{signature}",),
        ).fetchone()
        assert row is not None, signature
        assert row[0:2] == ("request_engine_schema_owner", True), signature
        assert row[2] == ["search_path=pg_catalog, request_engine"], signature
        assert row[3] is True, signature
        assert row[4] is False, signature


@pytest.mark.asyncio
async def test_revoke_credential_revokes_its_sessions(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-cascade@example.test"
    )
    store = PostgresWebAuthnStore(command_session_factory)
    service = _service(store)
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    credential_row_id = await _register_passkey(store, service, identity_id, authenticator)
    raw_token = await _issue_passkey_session(store, service, identity_id, authenticator)

    assert await store.revoke_credential(
        credential_row_id=credential_row_id,
        native_identity_id=identity_id,
        reason="compromise",
    )
    with pytest.raises(SessionRevoked):
        await _session_authenticator(command_session_factory).authenticate(
            NativeSessionEvidence(raw_token)
        )


@pytest.mark.asyncio
async def test_disabling_identity_revokes_webauthn_credentials(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _enroll_identity(
        admin_conn, command_session_factory, login_handle="webauthn-disable@example.test"
    )
    row_id, _credential_id = _insert_credential(admin_conn, identity_id)
    admin_conn.execute(
        "SELECT request_auth.disable_native_identity(%s, %s)",
        (identity_id, "global_disable_proof"),
    )
    store = PostgresWebAuthnStore(command_session_factory)
    record = (await store.read_credentials(native_identity_id=identity_id))[0]
    assert record.id == row_id
    assert record.status == "revoked"


def test_webauthn_tables_are_not_directly_readable(admin_conn: PgConnection) -> None:
    for table in (
        "request_engine.webauthn_credentials",
        "request_engine.webauthn_challenges",
    ):
        assert admin_conn.execute(
            "SELECT has_table_privilege('request_engine_app', %s, 'SELECT')", (table,)
        ).fetchone() == (False,)


@pytest.mark.asyncio
async def test_complete_registration_rejects_unknown_challenge(
    command_session_factory: SessionFactory,
) -> None:
    store = PostgresWebAuthnStore(command_session_factory)
    service = _service(store)
    authenticator = SoftwareAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    credential = authenticator.registration_credential(challenge=secrets.token_bytes(32))
    with pytest.raises(WebAuthnCeremonyError):
        await service.complete_registration(credential=credential)
