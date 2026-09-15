"""Recovery consumption must serialize on the identity before locking its intent."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.native_human_auth import (
    NativeHumanAuthService,
    RecoveryIntentInvalid,
)

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
    pytest.mark.concurrency,
]

_WAIT_SECONDS = 30.0
_PASSWORD = "correct horse battery staple"
_NEW_PASSWORD = "replacement correct horse battery staple"


async def _wait_for_blocked_recovery_consumers(
    admin_conn: PgConnection,
    *,
    minimum: int = 1,
) -> bool:
    for _ in range(int(_WAIT_SECONDS / 0.05)):
        row = admin_conn.execute(
            """
            SELECT count(*)
              FROM pg_stat_activity
             WHERE state = 'active'
               AND wait_event_type = 'Lock'
               AND query LIKE '%consume_native_recovery_intent%'
            """
        ).fetchone()
        if row is not None and int(row[0]) >= minimum:
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.mark.asyncio
async def test_consume_recovery_waits_on_identity_before_touching_intent(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command_session_factory: SessionFactory,
) -> None:
    """0039 regression world: issuance holds identity, then revokes the proof.

    Old consumption locked the intent first and only then waited on identity.
    Under that order the issuance update below blocks on the consumed intent
    while consumption blocks on identity: PostgreSQL must break a deadlock and
    the partial credential effects race becomes possible. The current function
    reads the candidate without locking, queues on the identity root, revalidates
    the proof and loses cleanly.
    """

    authority_id = uuid4()
    login_handle = f"recovery-lock-{uuid4().hex}@example.test"
    admin_conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment)
        VALUES (%s, 'native', %s)
        """,
        (authority_id, f"recovery-lock:{authority_id}"),
    )
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=_PASSWORD,
    )
    identity_id = enrollment.native_identity_id
    issued = await service.issue_recovery(
        identity_authority_id=authority_id, login_handle=login_handle
    )
    assert issued is not None
    epoch_before = admin_conn.execute(
        "SELECT session_epoch FROM request_engine.native_identities WHERE id = %s",
        (identity_id,),
    ).fetchone()
    assert epoch_before is not None

    blocker = PgConnection.connect(pg_conninfo)
    consume: asyncio.Task[UUID] | None = None
    try:
        blocker.execute("SET lock_timeout = '10s'")
        blocker.execute(
            "SELECT status FROM request_engine.native_identities WHERE id = %s FOR UPDATE",
            (identity_id,),
        )
        consume = asyncio.create_task(
            service.consume_recovery(raw_token=issued.raw_token, new_password=_NEW_PASSWORD)
        )
        assert await _wait_for_blocked_recovery_consumers(admin_conn), (
            "recovery consumption never waited on the identity serialization root"
        )

        replacement = issue_opaque_token()
        issued_new = blocker.execute(
            """
            SELECT request_auth.create_native_recovery_intent(
                %s, %s, %s, %s, clock_timestamp() + interval '30 minutes'
            )
            """,
            (
                identity_id,
                replacement.token_id,
                replacement.digest,
                replacement.fingerprint,
            ),
        ).fetchone()
        assert issued_new == (True,)
        blocker.commit()

        with pytest.raises(RecoveryIntentInvalid):
            await consume
    finally:
        if not blocker.closed:
            if consume is not None and not consume.done():
                blocker.rollback()
            blocker.close()
        if consume is not None:
            await asyncio.gather(consume, return_exceptions=True)

    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
        (issued.recovery_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
        (replacement.token_id,),
    ).fetchone() == ("pending",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials WHERE native_identity_id = %s",
        (identity_id,),
    ).fetchone() == (1,)
    assert (
        admin_conn.execute(
            "SELECT session_epoch FROM request_engine.native_identities WHERE id = %s",
            (identity_id,),
        ).fetchone()
        == epoch_before
    )
