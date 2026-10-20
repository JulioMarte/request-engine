"""A password proof cannot outlive an in-place verifier change.

Real PostgreSQL auth-role operations and deterministic service-read barriers.
The second connection changes the verifier after the proof snapshot was read;
finalization must reject it without changing freshness or recovery posture.
"""

import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import insert_authority
from psycopg import Connection

from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.recovery_code_store import PostgresRecoveryCodeStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import (
    CredentialInvalid,
    hash_password,
    hash_password_scrypt,
    issue_opaque_token,
)
from request_engine.platform.security.native_human_auth import (
    NativeEnrollmentOutcome,
    NativeHumanAuthService,
    NativeSessionPasswordCredential,
)
from request_engine.platform.security.recovery_codes import (
    NativeRecoveryCodeService,
    RecoverySessionPasswordCredential,
    recovery_code_digest,
)

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]
PgConnection = Connection[Any]
PASSWORD = "initial current password proof"


class PausingReauthenticationStore(PostgresNativeHumanAuthStore):
    def __init__(self, factory: SessionFactory, read: asyncio.Event, resume: asyncio.Event) -> None:
        super().__init__(factory)
        self.read = read
        self.resume = resume

    async def read_session_password_credential(
        self, *, session_id: UUID
    ) -> NativeSessionPasswordCredential | None:
        credential = await super().read_session_password_credential(session_id=session_id)
        self.read.set()
        await self.resume.wait()
        return credential


class PausingRecoveryStore(PostgresRecoveryCodeStore):
    def __init__(self, factory: SessionFactory, read: asyncio.Event, resume: asyncio.Event) -> None:
        super().__init__(factory)
        self.read = read
        self.resume = resume

    async def read_recovery_session_password_credential(
        self, *, session_id: UUID
    ) -> RecoverySessionPasswordCredential | None:
        credential = await super().read_recovery_session_password_credential(session_id=session_id)
        self.read.set()
        await self.resume.wait()
        return credential


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reauthentication", "recovery_completion"])
async def test_in_place_verifier_change_invalidates_a_pending_password_proof(
    operation: str,
    admin_conn: PgConnection,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    store = PostgresNativeHumanAuthStore(command_session_factory)
    handle = f"password-proof-{uuid4().hex}@example.test"
    # Valid upgraded-installation world: the active credential holds a legacy
    # scrypt verifier. Only such a verifier is changed in place by the accepted
    # rehash primitive below, so the world is built through the same auth-role
    # primitives the services use, without an opportunistic login upgrade.
    native_identity_id = uuid4()
    assert (
        await store.create_identity(
            identity_authority_id=authority_id,
            native_identity_id=native_identity_id,
            login_handle=handle,
            credential_id=uuid4(),
            verifier=hash_password_scrypt(PASSWORD),
        )
        == NativeEnrollmentOutcome.CREATED
    )
    password = PASSWORD
    if operation == "recovery_completion":
        recovery_store = PostgresRecoveryCodeStore(command_session_factory)
        codes = await NativeRecoveryCodeService(
            store=recovery_store, code_count=1
        ).issue_for_identity(native_identity_id=native_identity_id)
        password = "password changed through offline recovery"
        assert (
            await recovery_store.consume_and_rotate_password(
                code_digest=recovery_code_digest(codes[0]),
                new_credential_id=uuid4(),
                new_verifier=hash_password_scrypt(password),
            )
            == native_identity_id
        )
    credential = await store.read_password_credential(
        identity_authority_id=authority_id, login_handle=handle
    )
    assert credential is not None
    assert credential.verifier.startswith("scrypt$")
    token = issue_opaque_token()
    assert await store.create_session(
        native_identity_id=native_identity_id,
        credential_id=credential.credential_id,
        session_id=token.token_id,
        token_digest=token.digest,
        token_fingerprint=token.fingerprint,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session_id = token.token_id
    before = admin_conn.execute(
        "SELECT last_authenticated_at FROM request_engine.native_sessions WHERE id = %s",
        (session_id,),
    ).fetchone()
    posture_before = admin_conn.execute(
        "SELECT state, recovery_epoch FROM request_engine.native_identity_recovery_state "
        "WHERE native_identity_id = %s",
        (native_identity_id,),
    ).fetchone()
    read, resume = asyncio.Event(), asyncio.Event()
    pending: Awaitable[object]
    if operation == "reauthentication":
        pending = asyncio.create_task(
            NativeHumanAuthService(
                store=PausingReauthenticationStore(command_session_factory, read, resume)
            ).reauthenticate_session(session_id=session_id, password=password)
        )
    else:
        pending = asyncio.create_task(
            NativeRecoveryCodeService(
                store=PausingRecoveryStore(command_session_factory, read, resume)
            ).complete_recovery_with_password(session_id=session_id, password=password)
        )
    await asyncio.wait_for(read.wait(), timeout=5)
    try:
        # This accepted auth-role primitive changes a verifier in place. It
        # preserves the credential id and session, exposing a stale-proof bug
        # that tests of full rotation/session revocation alone cannot detect.
        changed = app_role_conn.execute(
            "SELECT request_auth.rehash_native_password_verifier(%s, %s, %s)",
            (
                credential.credential_id,
                native_identity_id,
                hash_password("a different current password after snapshot"),
            ),
        ).fetchone()
        app_role_conn.commit()
        assert changed == (True,)
    finally:
        resume.set()
    with pytest.raises(CredentialInvalid):
        await asyncio.wait_for(cast("Awaitable[object]", pending), timeout=5)
    assert (
        admin_conn.execute(
            "SELECT last_authenticated_at FROM request_engine.native_sessions WHERE id = %s",
            (session_id,),
        ).fetchone()
        == before
    )
    assert (
        admin_conn.execute(
            "SELECT state, recovery_epoch FROM request_engine.native_identity_recovery_state "
            "WHERE native_identity_id = %s",
            (native_identity_id,),
        ).fetchone()
        == posture_before
    )
