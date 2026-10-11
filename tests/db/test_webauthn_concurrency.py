"""Deterministic PostgreSQL races for WebAuthn challenge finalization (ADR 0014 P2).

These proofs use independent connections and lock-wait detection, never timing
sleeps. They exercise the authoritative finalization protocol: one winner, no
partial consequence, fail-closed against revocation/disable.
"""

import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import wait_for_lock_wait
from psycopg import Connection

from request_engine.platform.security.native_auth import issue_opaque_token

PgConnection = Connection[Any]
AppConnFactory = Callable[[], PgConnection]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
    pytest.mark.concurrency,
]

_FINALIZE_REGISTRATION: LiteralString = (
    "SELECT request_auth.finalize_webauthn_registration(%s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_FINALIZE_AUTHENTICATION: LiteralString = (
    "SELECT request_auth.finalize_webauthn_authentication("
    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_FINALIZE_STEP_UP: LiteralString = (
    "SELECT request_auth.finalize_webauthn_step_up(%s, %s, %s, %s, %s, %s, %s)"
)
_FINALIZE_SETUP: LiteralString = (
    "SELECT request_auth.finalize_setup_webauthn_registration("
    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_FINALIZE_DISCOVERABLE: LiteralString = (
    "SELECT native_identity_id FROM request_auth.finalize_discoverable_webauthn_authentication("
    "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def _backend_pid(conn: PgConnection) -> int:
    row = conn.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return int(row[0])


class _Contender:
    """Run one statement on an independent connection without blocking the test."""

    def __init__(
        self, conn: PgConnection, statement: LiteralString, params: tuple[object, ...]
    ) -> None:
        self._conn = conn
        self._statement: LiteralString = statement
        self._params = params
        self._outcome: dict[str, object] = {}
        self._thread = threading.Thread(target=self._run)
        self._pid = _backend_pid(conn)

    def start(self) -> None:
        self._thread.start()

    def join(self) -> dict[str, object]:
        self._thread.join(timeout=20)
        assert not self._thread.is_alive(), "contending finalization did not complete"
        return self._outcome

    @property
    def pid(self) -> int:
        return self._pid

    def _run(self) -> None:
        try:
            self._outcome["result"] = self._conn.execute(self._statement, self._params).fetchone()
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            self._outcome["error"] = exc


def _world(admin_conn: PgConnection) -> tuple[UUID, UUID, bytes]:
    authority_id = uuid4()
    identity_id = uuid4()
    credential_id = secrets.token_bytes(32)
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"webauthn-race-{uuid4().hex}"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities(id, identity_authority_id, login_handle) "
        "VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"race-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.webauthn_credentials "
        "(id, native_identity_id, credential_id, public_key, aaguid, user_handle,user_verified) "
        "VALUES (%s, %s, %s, %s, %s, %s,false)",
        (
            uuid4(),
            identity_id,
            credential_id,
            secrets.token_bytes(77),
            "00" * 16,
            secrets.token_bytes(32),
        ),
    )
    return authority_id, identity_id, credential_id


def _credential_row(admin_conn: PgConnection, credential_id: bytes) -> UUID:
    row = admin_conn.execute(
        "SELECT id FROM request_engine.webauthn_credentials WHERE credential_id = %s",
        (credential_id,),
    ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _pending_challenge(
    admin_conn: PgConnection, identity_id: UUID, purpose: str = "authentication"
) -> bytes:
    digest = secrets.token_bytes(32)
    if purpose == "registration":
        admin_conn.execute(
            "INSERT INTO request_engine.webauthn_challenges "
            "(id, purpose, native_identity_id, challenge_digest, expires_at, user_handle) "
            "VALUES (%s, %s, %s, %s, clock_timestamp() + interval '5 minutes', %s)",
            (uuid4(), purpose, identity_id, digest, secrets.token_bytes(32)),
        )
    else:
        admin_conn.execute(
            "INSERT INTO request_engine.webauthn_challenges "
            "(id, purpose, native_identity_id, challenge_digest, expires_at) "
            "VALUES (%s, %s, %s, %s, clock_timestamp() + interval '5 minutes')",
            (uuid4(), purpose, identity_id, digest),
        )
    return digest


def _registration_args(digest: bytes, credential_id: bytes) -> tuple[object, ...]:
    return (
        digest,
        uuid4(),
        credential_id,
        secrets.token_bytes(77),
        0,
        "00" * 16,
        False,
        False,
        True,
    )


def _authentication_args(
    digest: bytes, row_id: UUID, identity_id: UUID, sign_count: int
) -> tuple[object, ...]:
    token = issue_opaque_token()
    return (
        digest,
        row_id,
        identity_id,
        sign_count,
        False,
        False,
        True,
        token.token_id,
        token.digest,
        token.fingerprint,
        datetime.now(UTC) + timedelta(hours=1),
    )


def test_concurrent_challenge_finalization_has_exactly_one_winner(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    _authority, identity_id, _existing_credential_id = _world(admin_conn)
    credential_id = secrets.token_bytes(32)
    digest = _pending_challenge(admin_conn, identity_id, "registration")
    args = _registration_args(digest, credential_id)

    winner = app_role_conn_factory()
    assert winner.execute(_FINALIZE_REGISTRATION, args).fetchone() == (True,)
    winner_pid = _backend_pid(winner)

    contender = _Contender(app_role_conn_factory(), _FINALIZE_REGISTRATION, args)
    contender.start()
    assert wait_for_lock_wait(admin_conn, contender.pid, blocker_pid=winner_pid)
    winner.commit()
    outcome = contender.join()

    assert "error" not in outcome
    assert outcome["result"] == (False,)
    assert admin_conn.execute(
        "SELECT status,consumed_at IS NOT NULL FROM request_engine.webauthn_challenges "
        "WHERE challenge_digest=%s",
        (digest,),
    ).fetchone() == ("consumed", True)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.webauthn_credentials WHERE credential_id = %s",
        (credential_id,),
    ).fetchone() == (1,)


def test_concurrent_assertions_keep_counter_high_water(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    _authority, identity_id, credential_id = _world(admin_conn)
    row_id = _credential_row(admin_conn, credential_id)
    first = _authentication_args(
        _pending_challenge(admin_conn, identity_id), row_id, identity_id, 7
    )
    second = _authentication_args(
        _pending_challenge(admin_conn, identity_id), row_id, identity_id, 5
    )

    older = app_role_conn_factory()
    older.execute(_FINALIZE_AUTHENTICATION, first)
    older_pid = _backend_pid(older)

    newer = _Contender(app_role_conn_factory(), _FINALIZE_AUTHENTICATION, second)
    newer.start()
    assert wait_for_lock_wait(admin_conn, newer.pid, blocker_pid=older_pid)
    older.commit()
    outcome = newer.join()

    assert "error" not in outcome
    assert outcome["result"] == (True,)
    assert admin_conn.execute(
        "SELECT sign_count FROM request_engine.webauthn_credentials WHERE id = %s",
        (row_id,),
    ).fetchone() == (7,)


def test_assertion_racing_credential_revoke_fails_closed(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    _authority, identity_id, credential_id = _world(admin_conn)
    row_id = _credential_row(admin_conn, credential_id)
    args = _authentication_args(_pending_challenge(admin_conn, identity_id), row_id, identity_id, 1)

    assertion = app_role_conn_factory()
    assertion.execute(_FINALIZE_AUTHENTICATION, args)
    assertion_pid = _backend_pid(assertion)

    revoker_conn = app_role_conn_factory()
    revoker = _Contender(
        revoker_conn,
        "SELECT request_auth.revoke_webauthn_credential(%s, %s, %s)",
        (row_id, identity_id, "race"),
    )
    revoker.start()
    assert wait_for_lock_wait(admin_conn, revoker.pid, blocker_pid=assertion_pid)
    assertion.commit()
    outcome = revoker.join()
    revoker_conn.commit()

    assert "error" not in outcome
    assert outcome["result"] == (True,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.webauthn_credentials WHERE id = %s",
        (row_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_sessions "
        "WHERE webauthn_credential_id = %s AND status = 'active'",
        (row_id,),
    ).fetchone() == (0,)


def test_assertion_racing_identity_disable_leaves_no_active_session(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    _authority, identity_id, credential_id = _world(admin_conn)
    row_id = _credential_row(admin_conn, credential_id)
    args = _authentication_args(_pending_challenge(admin_conn, identity_id), row_id, identity_id, 1)

    assertion = app_role_conn_factory()
    assertion.execute(_FINALIZE_AUTHENTICATION, args)
    assertion_pid = _backend_pid(assertion)

    disabler_conn = app_role_conn_factory()
    disabler = _Contender(
        disabler_conn,
        "SELECT request_auth.disable_native_identity(%s, %s)",
        (identity_id, "race_disable"),
    )
    disabler.start()
    assert wait_for_lock_wait(admin_conn, disabler.pid, blocker_pid=assertion_pid)
    assertion.commit()
    outcome = disabler.join()
    disabler_conn.commit()

    assert "error" not in outcome
    assert outcome["result"] == (True,)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_identities WHERE id = %s",
        (identity_id,),
    ).fetchone() == ("disabled",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_sessions "
        "WHERE native_identity_id = %s AND status = 'active'",
        (identity_id,),
    ).fetchone() == (0,)


def test_step_up_racing_credential_revoke_does_not_deadlock(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    _authority, identity_id, credential_id = _world(admin_conn)
    row_id = _credential_row(admin_conn, credential_id)

    password_credential_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.native_credentials "
        "(id, native_identity_id, verifier) VALUES (%s, %s, %s)",
        (password_credential_id, identity_id, "scrypt$" + "a" * 64),
    )
    token = issue_opaque_token()
    session = app_role_conn_factory()
    session.execute(
        "SELECT request_auth.create_native_session(%s, %s, %s, %s, %s, %s)",
        (
            identity_id,
            password_credential_id,
            token.token_id,
            token.digest,
            token.fingerprint,
            datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    session.commit()

    digest = secrets.token_bytes(32)
    admin_conn.execute(
        "INSERT INTO request_engine.webauthn_challenges "
        "(id, purpose, session_id, challenge_digest, expires_at) "
        "VALUES (%s, 'step_up', %s, %s, clock_timestamp() + interval '5 minutes')",
        (uuid4(), token.token_id, digest),
    )
    step_up_args: tuple[object, ...] = (digest, row_id, token.token_id, identity_id, 1, False, True)

    stepper = app_role_conn_factory()
    stepper.execute(_FINALIZE_STEP_UP, step_up_args)
    stepper_pid = _backend_pid(stepper)

    revoker_conn = app_role_conn_factory()
    revoker = _Contender(
        revoker_conn,
        "SELECT request_auth.revoke_webauthn_credential(%s, %s, %s)",
        (row_id, identity_id, "race"),
    )
    revoker.start()
    assert wait_for_lock_wait(admin_conn, revoker.pid, blocker_pid=stepper_pid)
    stepper.commit()
    outcome = revoker.join()
    revoker_conn.commit()

    assert "error" not in outcome, outcome
    assert outcome["result"] == (True,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_sessions "
        "WHERE native_identity_id = %s AND status = 'active'",
        (identity_id,),
    ).fetchone() == (0,)


def test_discoverable_finalization_rechecks_expiry_after_identity_lock_wait(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    authority_id, identity_id, credential_id = _world(admin_conn)
    row_id = _credential_row(admin_conn, credential_id)
    handle_row = admin_conn.execute(
        "SELECT user_handle FROM request_engine.webauthn_credentials WHERE id=%s", (row_id,)
    ).fetchone()
    assert handle_row is not None and handle_row[0] is not None
    challenge_digest = secrets.token_bytes(32)
    challenge_id = uuid4()
    expiry = admin_conn.execute(
        "INSERT INTO request_engine.webauthn_challenges "
        "(id,purpose,challenge_digest,expires_at) "
        "VALUES(%s,'authentication_discoverable',%s,clock_timestamp()+interval '1 second') "
        "RETURNING expires_at",
        (challenge_id, challenge_digest),
    ).fetchone()
    assert expiry is not None
    token = issue_opaque_token()
    args: tuple[object, ...] = (
        challenge_digest,
        row_id,
        7,
        False,
        False,
        True,
        token.token_id,
        token.digest,
        token.fingerprint,
        datetime.now(UTC) + timedelta(hours=1),
        authority_id,
        bytes(handle_row[0]),
    )

    admin_conn.execute("BEGIN")
    admin_conn.execute(
        "SELECT id FROM request_engine.native_identities WHERE id=%s FOR UPDATE",
        (identity_id,),
    )
    blocker_pid = _backend_pid(admin_conn)
    finalizer = _Contender(app_role_conn_factory(), _FINALIZE_DISCOVERABLE, args)
    finalizer.start()
    assert wait_for_lock_wait(admin_conn, finalizer.pid, blocker_pid=blocker_pid)

    deadline = time.monotonic() + 10
    while True:
        expired = admin_conn.execute(
            "SELECT clock_timestamp() >= expires_at FROM request_engine.webauthn_challenges "
            "WHERE id=%s",
            (challenge_id,),
        ).fetchone()
        assert expired is not None
        if expired[0]:
            break
        assert time.monotonic() < deadline, "database challenge did not expire while blocked"
        time.sleep(0.01)

    admin_conn.execute("COMMIT")
    assert finalizer.join()["result"] is None
    assert admin_conn.execute(
        "SELECT status,consumed_at FROM request_engine.webauthn_challenges WHERE id=%s",
        (challenge_id,),
    ).fetchone() == ("pending", None)
    assert admin_conn.execute(
        "SELECT sign_count,last_used_at FROM request_engine.webauthn_credentials WHERE id=%s",
        (row_id,),
    ).fetchone() == (0, None)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_sessions WHERE id=%s", (token.token_id,)
    ).fetchone() == (0,)


def _wait_until_challenge_expired(admin_conn: PgConnection, digest: bytes) -> None:
    """Observe DB time only after the contender is proven blocked on a real lock."""
    deadline = time.monotonic() + 10
    while True:
        row = admin_conn.execute(
            "SELECT clock_timestamp() >= expires_at FROM request_engine.webauthn_challenges "
            "WHERE challenge_digest=%s",
            (digest,),
        ).fetchone()
        assert row is not None
        if row[0]:
            return
        assert time.monotonic() < deadline, "challenge did not expire while blocked"
        time.sleep(0.01)


def _shorten_challenge(admin_conn: PgConnection, digest: bytes) -> None:
    admin_conn.execute(
        "UPDATE request_engine.webauthn_challenges "
        "SET expires_at=clock_timestamp()+interval '1 second' WHERE challenge_digest=%s",
        (digest,),
    )


def _assert_challenge_pending(admin_conn: PgConnection, digest: bytes) -> None:
    assert admin_conn.execute(
        "SELECT status,consumed_at FROM request_engine.webauthn_challenges "
        "WHERE challenge_digest=%s",
        (digest,),
    ).fetchone() == ("pending", None)


def _password_session(
    admin_conn: PgConnection, app_role_conn_factory: AppConnFactory, identity_id: UUID
) -> UUID:
    password_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.native_credentials(id,native_identity_id,verifier) "
        "VALUES(%s,%s,%s)",
        (password_id, identity_id, "scrypt$" + "a" * 64),
    )
    token = issue_opaque_token()
    with app_role_conn_factory() as conn:
        assert conn.execute(
            "SELECT request_auth.create_native_session(%s,%s,%s,%s,%s,%s)",
            (
                identity_id,
                password_id,
                token.token_id,
                token.digest,
                token.fingerprint,
                datetime.now(UTC) + timedelta(hours=1),
            ),
        ).fetchone() == (True,)
    return token.token_id


@pytest.mark.parametrize("ceremony", ["registration", "authentication", "step_up"])
def test_finalization_rechecks_challenge_expiry_after_owner_lock_wait(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
    ceremony: str,
) -> None:
    """Regression: challenge passes entry check, then expires behind owner lock."""
    _authority, identity_id, credential_id = _world(admin_conn)
    row_id = _credential_row(admin_conn, credential_id)
    session_id = _password_session(admin_conn, app_role_conn_factory, identity_id)
    if ceremony == "step_up":
        digest = secrets.token_bytes(32)
        admin_conn.execute(
            "INSERT INTO request_engine.webauthn_challenges "
            "(id,purpose,session_id,challenge_digest,expires_at) "
            "VALUES(%s,'step_up',%s,%s,clock_timestamp()+interval '5 minutes')",
            (uuid4(), session_id, digest),
        )
        statement = _FINALIZE_STEP_UP
        args = (digest, row_id, session_id, identity_id, 7, False, True)
    elif ceremony == "registration":
        digest = _pending_challenge(admin_conn, identity_id, ceremony)
        statement = _FINALIZE_REGISTRATION
        args = _registration_args(digest, secrets.token_bytes(32))
    else:
        digest = _pending_challenge(admin_conn, identity_id)
        statement = _FINALIZE_AUTHENTICATION
        args = _authentication_args(digest, row_id, identity_id, 7)
    before = admin_conn.execute(
        "SELECT authentication_methods,user_verified,last_authenticated_at,last_seen_at "
        "FROM request_engine.native_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    _shorten_challenge(admin_conn, digest)
    admin_conn.execute("BEGIN")
    admin_conn.execute(
        "SELECT id FROM request_engine.native_identities WHERE id=%s FOR UPDATE",
        (identity_id,),
    )
    finalizer_conn = app_role_conn_factory()
    finalizer = _Contender(finalizer_conn, statement, args)
    finalizer.start()
    assert wait_for_lock_wait(admin_conn, finalizer.pid, blocker_pid=_backend_pid(admin_conn))
    _wait_until_challenge_expired(admin_conn, digest)
    admin_conn.execute("COMMIT")
    outcome = finalizer.join()
    finalizer_conn.commit()
    assert outcome == {"result": (False,)}
    _assert_challenge_pending(admin_conn, digest)
    assert admin_conn.execute(
        "SELECT sign_count,last_used_at FROM request_engine.webauthn_credentials WHERE id=%s",
        (row_id,),
    ).fetchone() == (0, None)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.webauthn_credentials WHERE native_identity_id=%s",
        (identity_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_sessions WHERE native_identity_id=%s",
        (identity_id,),
    ).fetchone() == (1,)
    assert (
        admin_conn.execute(
            "SELECT authentication_methods,user_verified,last_authenticated_at,last_seen_at "
            "FROM request_engine.native_sessions WHERE id=%s",
            (session_id,),
        ).fetchone()
        == before
    )


def _setup_challenge(admin_conn: PgConnection) -> tuple[UUID, bytes]:
    native_id, workload_id, instance_id, setup_id = uuid4(), uuid4(), uuid4(), uuid4()
    for authority_id, kind in ((native_id, "native"), (workload_id, "workload")):
        admin_conn.execute(
            "INSERT INTO request_engine.identity_authorities(id,kind,issuer_or_environment) "
            "VALUES(%s,%s,%s)",
            (authority_id, kind, f"setup-race-{uuid4().hex}"),
        )
    admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id,built_in_native_authority_id,built_in_workload_authority_id) VALUES(%s,%s,%s)",
        (instance_id, native_id, workload_id),
    )
    token = issue_opaque_token(token_id=setup_id)
    admin_conn.execute(
        "INSERT INTO request_engine.setup_sessions "
        "(id,instance_id,token_digest,token_fingerprint,mode,expires_at) "
        "VALUES(%s,%s,%s,%s,'interactive',clock_timestamp()+interval '20 minutes')",
        (setup_id, instance_id, token.digest, token.fingerprint),
    )
    digest = secrets.token_bytes(32)
    admin_conn.execute(
        "INSERT INTO request_engine.webauthn_challenges "
        "(id,purpose,setup_session_id,challenge_digest,user_handle,expires_at) "
        "VALUES(%s,'registration',%s,%s,%s,clock_timestamp()+interval '5 minutes')",
        (uuid4(), setup_id, digest, secrets.token_bytes(32)),
    )
    return setup_id, digest


def test_setup_registration_rechecks_expiry_after_setup_session_lock_wait(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    setup_id, digest = _setup_challenge(admin_conn)
    args = (*_registration_args(digest, secrets.token_bytes(32)), setup_id)
    _shorten_challenge(admin_conn, digest)
    admin_conn.execute("BEGIN")
    admin_conn.execute(
        "SELECT id FROM request_engine.setup_sessions WHERE id=%s FOR UPDATE",
        (setup_id,),
    )
    finalizer_conn = app_role_conn_factory()
    contender = _Contender(finalizer_conn, _FINALIZE_SETUP, args)
    contender.start()
    assert wait_for_lock_wait(admin_conn, contender.pid, blocker_pid=_backend_pid(admin_conn))
    _wait_until_challenge_expired(admin_conn, digest)
    admin_conn.execute("COMMIT")
    outcome = contender.join()
    finalizer_conn.commit()
    assert outcome == {"result": (False,)}
    _assert_challenge_pending(admin_conn, digest)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.setup_pending_webauthn_credential "
        "WHERE setup_session_id=%s",
        (setup_id,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT status,consumed_at FROM request_engine.setup_sessions WHERE id=%s",
        (setup_id,),
    ).fetchone() == ("pending", None)


@pytest.mark.parametrize("setup", [False, True], ids=["normal", "setup"])
def test_registration_rolls_back_when_uniqueness_wait_outlives_challenge(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
    setup: bool,
) -> None:
    """A rolled-back rival releases its credential id only after TTL expired."""
    credential_id = secrets.token_bytes(32)
    other_setup_id: UUID | None = None
    other_identity_id: UUID | None = None
    if setup:
        setup_id, digest = _setup_challenge(admin_conn)
        other_setup_id = uuid4()
        token = issue_opaque_token(token_id=other_setup_id)
        admin_conn.execute(
            "INSERT INTO request_engine.setup_sessions "
            "(id,instance_id,token_digest,token_fingerprint,mode,expires_at) "
            "SELECT %s,instance_id,%s,%s,mode,expires_at "
            "FROM request_engine.setup_sessions WHERE id=%s",
            (other_setup_id, token.digest, token.fingerprint, setup_id),
        )
        statement = _FINALIZE_SETUP
        args = (*_registration_args(digest, credential_id), setup_id)
    else:
        _authority, identity_id, _credential = _world(admin_conn)
        _other_authority, other_identity_id, _other_credential = _world(admin_conn)
        digest = _pending_challenge(admin_conn, identity_id, "registration")
        statement = _FINALIZE_REGISTRATION
        args = _registration_args(digest, credential_id)
    _shorten_challenge(admin_conn, digest)
    admin_conn.execute("BEGIN")
    if setup:
        assert other_setup_id is not None
        admin_conn.execute(
            "INSERT INTO request_engine.setup_pending_webauthn_credential "
            "(id,setup_session_id,credential_id,public_key,aaguid,user_handle) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                other_setup_id,
                credential_id,
                secrets.token_bytes(77),
                "00" * 16,
                secrets.token_bytes(32),
            ),
        )
    else:
        assert other_identity_id is not None
        admin_conn.execute(
            "INSERT INTO request_engine.webauthn_credentials "
            "(id,native_identity_id,credential_id,public_key,aaguid,user_handle) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                uuid4(),
                other_identity_id,
                credential_id,
                secrets.token_bytes(77),
                "00" * 16,
                secrets.token_bytes(32),
            ),
        )
    finalizer_conn = app_role_conn_factory()
    contender = _Contender(finalizer_conn, statement, args)
    contender.start()
    assert wait_for_lock_wait(admin_conn, contender.pid, blocker_pid=_backend_pid(admin_conn))
    _wait_until_challenge_expired(admin_conn, digest)
    admin_conn.execute("ROLLBACK")
    outcome = contender.join()
    finalizer_conn.commit()
    assert outcome == {"result": (False,)}
    _assert_challenge_pending(admin_conn, digest)
    for table in ("webauthn_credentials", "setup_pending_webauthn_credential"):
        # Fixed names only; this is an authoritative absence oracle, not fixture setup.
        query: LiteralString = (
            "SELECT count(*) FROM request_engine.webauthn_credentials WHERE credential_id=%s"
            if table == "webauthn_credentials"
            else "SELECT count(*) FROM request_engine.setup_pending_webauthn_credential "
            "WHERE credential_id=%s"
        )
        assert admin_conn.execute(query, (credential_id,)).fetchone() == (0,)


@pytest.mark.parametrize("discoverable", [False, True], ids=["bound", "discoverable"])
def test_authentication_rolls_back_counter_when_token_uniqueness_wait_outlives_challenge(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
    discoverable: bool,
) -> None:
    authority_id, identity_id, credential_id = _world(admin_conn)
    row_id = _credential_row(admin_conn, credential_id)
    _other_authority, other_identity_id, other_credential_id = _world(admin_conn)
    other_row_id = _credential_row(admin_conn, other_credential_id)
    if discoverable:
        digest = secrets.token_bytes(32)
        admin_conn.execute(
            "INSERT INTO request_engine.webauthn_challenges "
            "(id,purpose,challenge_digest,expires_at) "
            "VALUES(%s,'authentication_discoverable',%s,clock_timestamp()+interval '5 minutes')",
            (uuid4(), digest),
        )
    else:
        digest = _pending_challenge(admin_conn, identity_id)
    token = issue_opaque_token()
    expires = datetime.now(UTC) + timedelta(hours=1)
    if discoverable:
        handle = admin_conn.execute(
            "SELECT user_handle FROM request_engine.webauthn_credentials WHERE id=%s",
            (row_id,),
        ).fetchone()
        assert handle is not None
        statement = _FINALIZE_DISCOVERABLE
        args = (
            digest,
            row_id,
            7,
            False,
            False,
            True,
            token.token_id,
            token.digest,
            token.fingerprint,
            expires,
            authority_id,
            bytes(handle[0]),
        )
    else:
        statement = _FINALIZE_AUTHENTICATION
        args = (
            digest,
            row_id,
            identity_id,
            7,
            False,
            False,
            True,
            token.token_id,
            token.digest,
            token.fingerprint,
            expires,
        )
    _shorten_challenge(admin_conn, digest)
    admin_conn.execute("BEGIN")
    admin_conn.execute(
        "INSERT INTO request_engine.native_sessions "
        "(id,native_identity_id,webauthn_credential_id,token_digest,token_fingerprint,"
        "session_epoch,expires_at,authentication_methods) "
        "SELECT %s,id,%s,%s,%s,session_epoch,%s,ARRAY['webauthn']::text[] "
        "FROM request_engine.native_identities WHERE id=%s",
        (uuid4(), other_row_id, token.digest, token.fingerprint, expires, other_identity_id),
    )
    finalizer_conn = app_role_conn_factory()
    contender = _Contender(finalizer_conn, statement, args)
    contender.start()
    assert wait_for_lock_wait(admin_conn, contender.pid, blocker_pid=_backend_pid(admin_conn))
    _wait_until_challenge_expired(admin_conn, digest)
    admin_conn.execute("ROLLBACK")
    expected = None if discoverable else (False,)
    outcome = contender.join()
    finalizer_conn.commit()
    assert outcome == {"result": expected}
    _assert_challenge_pending(admin_conn, digest)
    assert admin_conn.execute(
        "SELECT sign_count,last_used_at,user_verified,last_regression_at "
        "FROM request_engine.webauthn_credentials WHERE id=%s",
        (row_id,),
    ).fetchone() == (0, None, False, None)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_sessions WHERE token_digest=%s",
        (token.digest,),
    ).fetchone() == (0,)


def test_live_finalizer_completion_is_not_reversed_by_later_commit_after_ttl(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    """The contract is finalizer admission/effect, not delivery or caller COMMIT."""
    _authority, identity_id, _existing_credential = _world(admin_conn)
    digest = _pending_challenge(admin_conn, identity_id, "registration")
    credential_id = secrets.token_bytes(32)
    _shorten_challenge(admin_conn, digest)
    finalizer_conn = app_role_conn_factory()
    assert finalizer_conn.execute(
        _FINALIZE_REGISTRATION,
        _registration_args(digest, credential_id),
    ).fetchone() == (True,)
    _wait_until_challenge_expired(admin_conn, digest)
    finalizer_conn.commit()
    assert admin_conn.execute(
        "SELECT status,consumed_at < expires_at FROM request_engine.webauthn_challenges "
        "WHERE challenge_digest=%s",
        (digest,),
    ).fetchone() == ("consumed", True)
    assert admin_conn.execute(
        "SELECT native_identity_id FROM request_engine.webauthn_credentials WHERE credential_id=%s",
        (credential_id,),
    ).fetchone() == (identity_id,)
