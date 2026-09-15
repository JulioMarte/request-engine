"""Native authority suspension: positive gate, stale reads and re-enable semantics."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import (
    NEW_PASSWORD,
    PASSWORD,
    POSITIVE_PATHS,
    auth_fingerprint,
    authority_status,
    insert_authority,
    prepare_path,
    set_authority_status,
)
from psycopg import Connection

from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.native_session_reader import PostgresNativeSessionReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    issue_opaque_token,
)
from request_engine.platform.security.native_human_auth import (
    NativeEnrollmentUnavailable,
    NativeHumanAuthService,
    NativePasswordCredentialSnapshot,
    RecoveryIntentInvalid,
)
from request_engine.platform.security.native_session import (
    NativeIdentityAuthorityDisabled,
    NativeSessionAuthenticator,
    NativeSessionEvidence,
    SessionRevoked,
)

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]


def _service(session_factory: SessionFactory) -> NativeHumanAuthService:
    return NativeHumanAuthService(store=PostgresNativeHumanAuthStore(session_factory))


def _authenticator(session_factory: SessionFactory) -> NativeSessionAuthenticator:
    return NativeSessionAuthenticator(session_reader=PostgresNativeSessionReader(session_factory))


def test_native_suspension_keeps_definer_and_callable_boundaries(admin_conn: PgConnection) -> None:
    signatures = (
        "read_native_password_credential(uuid,text)",
        "create_native_identity(uuid,uuid,text,uuid,text)",
        "create_native_session(uuid,uuid,uuid,bytea,text,timestamptz)",
        "rotate_native_password(uuid,uuid,uuid,text,text)",
        "create_native_recovery_intent(uuid,uuid,bytea,text,timestamptz)",
        "consume_native_recovery_intent(uuid,bytea,uuid,text)",
        "lock_credentialed_native_identity(uuid,uuid)",
    )
    for signature in signatures:
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
        assert row[3] is (not signature.startswith("lock_credentialed_")), signature
        assert row[4] is False, signature


@pytest.mark.asyncio
async def test_active_authority_allows_full_positive_lifecycle(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    handle = f"gate-lifecycle-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    issued = await service.authenticate_password(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    subject = await _authenticator(command_session_factory).authenticate(
        NativeSessionEvidence(issued.raw_token)
    )
    assert subject.subject_id == str(enrollment.native_identity_id)

    rotated_credential_id = await service.rotate_password(
        identity_authority_id=authority_id,
        login_handle=handle,
        current_password=PASSWORD,
        new_password=NEW_PASSWORD,
    )
    recovery = await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
    assert recovery is not None
    consumed_identity_id = await service.consume_recovery(
        raw_token=recovery.raw_token, new_password=PASSWORD
    )
    assert consumed_identity_id == enrollment.native_identity_id
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_credentials WHERE id = %s",
        (rotated_credential_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s AND status = 'active'",
        (enrollment.native_identity_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
        (recovery.recovery_id,),
    ).fetchone() == ("consumed",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_sessions "
        "WHERE native_identity_id = %s AND status = 'active'",
        (enrollment.native_identity_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_read_credential_returns_no_verifier_when_authority_suspended(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    handle = f"gate-read-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    active_rows = app_role_conn.execute(
        "SELECT * FROM request_auth.read_native_password_credential(%s, %s)",
        (authority_id, handle),
    ).fetchall()
    assert len(active_rows) == 1
    app_role_conn.rollback()

    set_authority_status(admin_conn, authority_id, "disabled")
    disabled_rows = app_role_conn.execute(
        "SELECT * FROM request_auth.read_native_password_credential(%s, %s)",
        (authority_id, handle),
    ).fetchall()
    app_role_conn.rollback()
    assert disabled_rows == []
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials WHERE native_identity_id = %s",
        (enrollment.native_identity_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", POSITIVE_PATHS)
async def test_suspended_authority_rejects_direct_positive_path_without_effects(
    path: str,
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    service = _service(command_session_factory)
    world = await prepare_path(path, admin_conn, service)
    before = auth_fingerprint(admin_conn, world.identity_id)

    set_authority_status(admin_conn, world.authority_id, "disabled")
    try:
        row = app_role_conn.execute(world.call_sql, world.call_params).fetchone()
        # Commit the rejected call: rollback would conceal an accidental write.
        app_role_conn.commit()
    finally:
        app_role_conn.rollback()

    assert row is not None
    result = row[0]
    assert not world.expect_success(result), f"{path} unexpectedly succeeded under suspension"
    assert auth_fingerprint(admin_conn, world.identity_id) == before
    assert world.rejection_ok(admin_conn)
    assert authority_status(admin_conn, world.authority_id)[0] == "disabled"


@pytest.mark.asyncio
async def test_suspended_authority_rejects_service_operations_without_effects(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    handle = f"gate-service-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    recovery = await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
    assert recovery is not None
    before = auth_fingerprint(admin_conn, enrollment.native_identity_id)
    set_authority_status(admin_conn, authority_id, "disabled")

    with pytest.raises(NativeEnrollmentUnavailable):
        await service.enroll_password_identity(
            identity_authority_id=authority_id,
            login_handle=f"gate-service-new-{uuid4().hex}@example.test",
            password=PASSWORD,
        )
    with pytest.raises(CredentialInvalid):
        await service.authenticate_password(
            identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
        )
    with pytest.raises(CredentialInvalid):
        await service.rotate_password(
            identity_authority_id=authority_id,
            login_handle=handle,
            current_password=PASSWORD,
            new_password=NEW_PASSWORD,
        )
    assert (
        await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
        is None
    )
    with pytest.raises(RecoveryIntentInvalid):
        await service.consume_recovery(raw_token=recovery.raw_token, new_password=NEW_PASSWORD)

    assert auth_fingerprint(admin_conn, enrollment.native_identity_id) == before
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities"
    ).fetchone() == (1,)


class _SuspendingStore(PostgresNativeHumanAuthStore):
    """Disable the authority after a valid snapshot read, before the DB mutation."""

    def __init__(
        self,
        session_factory: SessionFactory,
        admin_conn: PgConnection,
        authority_id: UUID,
    ) -> None:
        super().__init__(session_factory)
        self._admin_conn = admin_conn
        self._authority_id = authority_id
        self.suspended = False

    async def read_password_credential(
        self, *, identity_authority_id: UUID, login_handle: str
    ) -> NativePasswordCredentialSnapshot | None:
        snapshot = await super().read_password_credential(
            identity_authority_id=identity_authority_id, login_handle=login_handle
        )
        if snapshot is not None and not self.suspended:
            set_authority_status(self._admin_conn, self._authority_id, "disabled")
            self.suspended = True
        return snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["session", "rotation", "issuance"])
async def test_stale_valid_snapshot_cannot_bypass_suspended_authority(
    operation: str,
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    base_service = _service(command_session_factory)
    handle = f"gate-stale-{uuid4().hex}@example.test"
    enrollment = await base_service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    prior_recovery = None
    if operation == "issuance":
        prior_recovery = await base_service.issue_recovery(
            identity_authority_id=authority_id, login_handle=handle
        )
        assert prior_recovery is not None

    before = auth_fingerprint(admin_conn, enrollment.native_identity_id)
    service = NativeHumanAuthService(
        store=_SuspendingStore(command_session_factory, admin_conn, authority_id)
    )
    if operation == "session":
        with pytest.raises(CredentialInvalid):
            await service.authenticate_password(
                identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
            )
    elif operation == "rotation":
        with pytest.raises(CredentialInvalid):
            await service.rotate_password(
                identity_authority_id=authority_id,
                login_handle=handle,
                current_password=PASSWORD,
                new_password=NEW_PASSWORD,
            )
    else:
        assert (
            await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
            is None
        )

    assert authority_status(admin_conn, authority_id)[0] == "disabled"
    assert auth_fingerprint(admin_conn, enrollment.native_identity_id) == before
    if prior_recovery is not None:
        assert admin_conn.execute(
            "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
            (prior_recovery.recovery_id,),
        ).fetchone() == ("pending",)


@pytest.mark.asyncio
async def test_unknown_wrong_kind_and_disabled_identity_fail_closed(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    unknown_authority = uuid4()
    unknown = app_role_conn.execute(
        "SELECT request_auth.create_native_identity(%s, %s, %s, %s, %s)",
        (
            unknown_authority,
            uuid4(),
            f"gate-unknown-{uuid4().hex}@example.test",
            uuid4(),
            "scrypt$placeholder",
        ),
    ).fetchone()
    app_role_conn.rollback()
    assert unknown == (None,)

    wrong_kind_authority = insert_authority(admin_conn, kind="workload")
    wrong_kind = app_role_conn.execute(
        "SELECT request_auth.create_native_identity(%s, %s, %s, %s, %s)",
        (
            wrong_kind_authority,
            uuid4(),
            f"gate-wrong-kind-{uuid4().hex}@example.test",
            uuid4(),
            "scrypt$placeholder",
        ),
    ).fetchone()
    app_role_conn.rollback()
    assert wrong_kind == (None,)

    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    handle = f"gate-disabled-identity-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    recovery = await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
    assert recovery is not None
    await service.disable_identity(
        native_identity_id=enrollment.native_identity_id, reason="gate_probe"
    )
    before = auth_fingerprint(admin_conn, enrollment.native_identity_id)

    with pytest.raises(CredentialInvalid):
        await service.authenticate_password(
            identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
        )
    with pytest.raises(CredentialInvalid):
        await service.rotate_password(
            identity_authority_id=authority_id,
            login_handle=handle,
            current_password=PASSWORD,
            new_password=NEW_PASSWORD,
        )
    assert (
        await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
        is None
    )
    with pytest.raises(RecoveryIntentInvalid):
        await service.consume_recovery(raw_token=recovery.raw_token, new_password=NEW_PASSWORD)
    assert auth_fingerprint(admin_conn, enrollment.native_identity_id) == before


@pytest.mark.asyncio
async def test_revocations_remain_available_while_authority_suspended(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    handle = f"gate-revoke-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    first_session = await service.authenticate_password(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    second_session = await service.authenticate_password(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    set_authority_status(admin_conn, authority_id, "disabled")

    await service.revoke_session(
        native_identity_id=enrollment.native_identity_id,
        session_id=first_session.session_id,
        reason="suspended_revoke",
    )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_sessions WHERE id = %s",
        (first_session.session_id,),
    ).fetchone() == ("revoked",)

    await service.revoke_all_sessions(
        native_identity_id=enrollment.native_identity_id, reason="suspended_revoke_all"
    )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_sessions WHERE id = %s",
        (second_session.session_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_identities WHERE id = %s",
        (enrollment.native_identity_id,),
    ).fetchone() == ("active",)

    await service.disable_identity(
        native_identity_id=enrollment.native_identity_id, reason="suspended_disable"
    )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_identities WHERE id = %s",
        (enrollment.native_identity_id,),
    ).fetchone() == ("disabled",)


@pytest.mark.asyncio
async def test_reenable_restores_only_still_valid_session_and_pending_proof(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    authenticator = _authenticator(command_session_factory)
    handle = f"gate-reenable-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    session = await service.authenticate_password(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    recovery = await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
    assert recovery is not None

    set_authority_status(admin_conn, authority_id, "disabled")
    with pytest.raises(NativeIdentityAuthorityDisabled):
        await authenticator.authenticate(NativeSessionEvidence(session.raw_token))
    with pytest.raises(RecoveryIntentInvalid):
        await service.consume_recovery(raw_token=recovery.raw_token, new_password=NEW_PASSWORD)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
        (recovery.recovery_id,),
    ).fetchone() == ("pending",)

    set_authority_status(admin_conn, authority_id, "active")
    subject = await authenticator.authenticate(NativeSessionEvidence(session.raw_token))
    assert subject.subject_id == str(enrollment.native_identity_id)
    consumed = await service.consume_recovery(
        raw_token=recovery.raw_token, new_password=NEW_PASSWORD
    )
    assert consumed == enrollment.native_identity_id
    new_session = await service.authenticate_password(
        identity_authority_id=authority_id, login_handle=handle, password=NEW_PASSWORD
    )
    assert new_session.native_identity_id == enrollment.native_identity_id
    with pytest.raises(RecoveryIntentInvalid):
        await service.consume_recovery(raw_token=recovery.raw_token, new_password=PASSWORD)


@pytest.mark.asyncio
async def test_reenable_does_not_revive_terminal_or_revoked_state(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    authenticator = _authenticator(command_session_factory)
    handle = f"gate-terminal-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    first = await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
    assert first is not None
    second = await service.issue_recovery(identity_authority_id=authority_id, login_handle=handle)
    assert second is not None
    consumed = await service.consume_recovery(raw_token=second.raw_token, new_password=NEW_PASSWORD)
    assert consumed == enrollment.native_identity_id
    expired = issue_opaque_token()
    admin_conn.execute(
        """
        INSERT INTO request_engine.native_recovery_intents (
            id, native_identity_id, token_digest, token_fingerprint, status,
            created_at, expires_at
        ) VALUES (
            %s, %s, %s, %s, 'pending',
            clock_timestamp() - interval '2 hours',
            clock_timestamp() - interval '1 hour'
        )
        """,
        (expired.token_id, enrollment.native_identity_id, expired.digest, expired.fingerprint),
    )
    revoked_session = await service.authenticate_password(
        identity_authority_id=authority_id, login_handle=handle, password=NEW_PASSWORD
    )
    await service.revoke_session(
        native_identity_id=enrollment.native_identity_id,
        session_id=revoked_session.session_id,
        reason="terminal_probe",
    )

    set_authority_status(admin_conn, authority_id, "disabled")
    set_authority_status(admin_conn, authority_id, "active")

    for dead_token in (first.raw_token, expired.raw_token, second.raw_token):
        with pytest.raises(RecoveryIntentInvalid):
            await service.consume_recovery(raw_token=dead_token, new_password=PASSWORD)
    with pytest.raises(SessionRevoked):
        await authenticator.authenticate(NativeSessionEvidence(revoked_session.raw_token))
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s AND status = 'active'",
        (enrollment.native_identity_id,),
    ).fetchone() == (1,)

    disabled_handle = f"gate-disabled-{uuid4().hex}@example.test"
    disabled_enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=disabled_handle,
        password=PASSWORD,
    )
    disabled_proof = await service.issue_recovery(
        identity_authority_id=authority_id, login_handle=disabled_handle
    )
    assert disabled_proof is not None
    await service.disable_identity(
        native_identity_id=disabled_enrollment.native_identity_id, reason="terminal_probe"
    )
    set_authority_status(admin_conn, authority_id, "disabled")
    set_authority_status(admin_conn, authority_id, "active")
    with pytest.raises(CredentialInvalid):
        await service.authenticate_password(
            identity_authority_id=authority_id,
            login_handle=disabled_handle,
            password=PASSWORD,
        )
    with pytest.raises(RecoveryIntentInvalid):
        await service.consume_recovery(
            raw_token=disabled_proof.raw_token, new_password=NEW_PASSWORD
        )
