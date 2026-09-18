"""Deterministic PostgreSQL races for WebAuthn challenge finalization (ADR 0014 P2).

These proofs use independent connections and lock-wait detection, never timing
sleeps. They exercise the authoritative finalization protocol: one winner, no
partial consequence, fail-closed against revocation/disable.
"""

import secrets
import threading
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
        "(id, native_identity_id, credential_id, public_key, aaguid) "
        "VALUES (%s, %s, %s, %s, %s)",
        (uuid4(), identity_id, credential_id, secrets.token_bytes(77), "00" * 16),
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
    _authority, identity_id, credential_id = _world(admin_conn)
    digest = _pending_challenge(admin_conn, identity_id, "registration")
    args = _registration_args(digest, credential_id)

    winner = app_role_conn_factory()
    winner.execute(_FINALIZE_REGISTRATION, args)
    winner_pid = _backend_pid(winner)

    contender = _Contender(app_role_conn_factory(), _FINALIZE_REGISTRATION, args)
    contender.start()
    assert wait_for_lock_wait(admin_conn, contender.pid, blocker_pid=winner_pid)
    winner.commit()
    outcome = contender.join()

    assert "error" not in outcome
    assert outcome["result"] == (False,)
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
