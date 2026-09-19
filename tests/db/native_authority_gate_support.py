"""Shared world and evidence helpers for Native authority suspension proofs."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, LiteralString
from uuid import UUID, uuid4

from request_engine.platform.security.native_auth import (
    digest_opaque_secret,
    hash_password,
    issue_opaque_token,
    parse_opaque_token,
)
from request_engine.platform.security.native_human_auth import NativeHumanAuthService

PgConnection = Any

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "replacement correct horse battery staple"
POSITIVE_PATHS = ("enrollment", "session", "rotation", "issuance", "consumption")


@dataclass(frozen=True)
class PositivePath:
    key: str
    authority_id: UUID
    identity_id: UUID | None
    call_sql: LiteralString
    call_params: dict[str, object]
    expect_success: Callable[[object], bool]
    effect_ok: Callable[[PgConnection], bool]
    rejection_ok: Callable[[PgConnection], bool]


def insert_authority(conn: PgConnection, *, kind: str = "native", status: str = "active") -> UUID:
    authority_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.identity_authorities "
        "(id, kind, status, issuer_or_environment) VALUES (%s, %s, %s, %s)",
        (authority_id, kind, status, f"authority-gate:{uuid4().hex}"),
    )
    return authority_id


def set_authority_status(conn: PgConnection, authority_id: UUID, status: str) -> None:
    conn.execute(
        "UPDATE request_engine.identity_authorities "
        "SET status = %s, revision = revision + 1 WHERE id = %s",
        (status, authority_id),
    )


def authority_status(conn: PgConnection, authority_id: UUID) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT status, revision FROM request_engine.identity_authorities WHERE id = %s",
        (authority_id,),
    ).fetchone()
    assert row is not None
    return row


def auth_fingerprint(conn: PgConnection, identity_id: UUID | None) -> dict[str, object]:
    """Independent before/after facts; excludes authority status and raw secrets."""

    credentials: object = ()
    identity: object = None
    sessions: object = ()
    intents: object = ()
    if identity_id is not None:
        credential_rows: list[tuple[Any, ...]] = conn.execute(
            "SELECT id, status, revision, rotated_at, revoked_at, last_used_at, verifier "
            "FROM request_engine.native_credentials WHERE native_identity_id = %s ORDER BY id",
            (identity_id,),
        ).fetchall()
        # Detect verifier mutation without exposing password verifiers in pytest diffs.
        credentials = [(*row[:-1], sha256(row[-1].encode()).hexdigest()) for row in credential_rows]
        identity = conn.execute(
            "SELECT status, session_epoch, revision, updated_at, disabled_at "
            "FROM request_engine.native_identities WHERE id = %s",
            (identity_id,),
        ).fetchone()
        sessions = conn.execute(
            "SELECT id, status, revoked_at, revocation_reason "
            "FROM request_engine.native_sessions WHERE native_identity_id = %s ORDER BY id",
            (identity_id,),
        ).fetchall()
        intents = conn.execute(
            "SELECT id, status, consumed_at, revoked_at "
            "FROM request_engine.native_recovery_intents "
            "WHERE native_identity_id = %s ORDER BY id",
            (identity_id,),
        ).fetchall()
    return {
        "credentials": credentials,
        "identity": identity,
        "sessions": sessions,
        "intents": intents,
        "authority_tables": (
            conn.execute("SELECT count(*) FROM request_engine.principals").fetchone(),
            conn.execute("SELECT count(*) FROM request_engine.identity_bindings").fetchone(),
            conn.execute(
                "SELECT count(*) FROM request_engine.principal_authority_grants"
            ).fetchone(),
            conn.execute("SELECT count(*) FROM request_engine.staff_memberships").fetchone(),
            conn.execute("SELECT count(*) FROM request_engine.audit_records").fetchone(),
            conn.execute("SELECT count(*) FROM request_engine.outbox_messages").fetchone(),
        ),
    }


def wait_for_lock_wait(
    admin_conn: PgConnection,
    backend_pid: int,
    *,
    timeout: float = 15.0,
    blocker_pid: int | None = None,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = admin_conn.execute(
            "SELECT pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE pid = %s AND wait_event_type = 'Lock'",
            (backend_pid,),
        ).fetchone()
        if row is not None and (blocker_pid is None or blocker_pid in row[0]):
            return True
        threading.Event().wait(0.05)
    return False


def session_token_params(identity_id: UUID, credential_id: UUID) -> dict[str, object]:
    token = issue_opaque_token()
    return {
        "native_identity_id": identity_id,
        "credential_id": credential_id,
        "session_id": token.token_id,
        "token_digest": token.digest,
        "token_fingerprint": token.fingerprint,
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }


async def prepare_path(
    path: str,
    admin_conn: PgConnection,
    service: NativeHumanAuthService,
) -> PositivePath:
    """Build a plausible active-authority world and the direct call for one positive path."""

    authority_id = insert_authority(admin_conn)
    if path == "enrollment":
        identity_id = uuid4()
        credential_id = uuid4()
        params: dict[str, object] = {
            "identity_authority_id": authority_id,
            "native_identity_id": identity_id,
            "login_handle": f"gate-enroll-{uuid4().hex}@example.test",
            "credential_id": credential_id,
            "verifier": hash_password(PASSWORD),
        }
        return PositivePath(
            key=path,
            authority_id=authority_id,
            identity_id=identity_id,
            call_sql=(
                "SELECT request_auth.create_native_identity("
                "%(identity_authority_id)s, %(native_identity_id)s, %(login_handle)s, "
                "%(credential_id)s, %(verifier)s)"
            ),
            call_params=params,
            expect_success=lambda value: value is True,
            effect_ok=lambda conn: (
                conn.execute(
                    "SELECT count(*) FROM request_engine.native_credentials "
                    "WHERE native_identity_id = %s",
                    (identity_id,),
                ).fetchone()
                == (1,)
            ),
            rejection_ok=lambda conn: (
                conn.execute(
                    "SELECT count(*) FROM request_engine.native_identities WHERE id = %s",
                    (identity_id,),
                ).fetchone()
                == (0,)
            ),
        )

    login_handle = f"gate-{path}-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    identity_id = enrollment.native_identity_id
    credential_id = enrollment.credential_id

    if path == "session":
        params = session_token_params(identity_id, credential_id)
        return PositivePath(
            key=path,
            authority_id=authority_id,
            identity_id=identity_id,
            call_sql=(
                "SELECT request_auth.create_native_session("
                "%(native_identity_id)s, %(credential_id)s, %(session_id)s, "
                "%(token_digest)s, %(token_fingerprint)s, %(expires_at)s)"
            ),
            call_params=params,
            expect_success=lambda value: value is True,
            effect_ok=lambda conn: (
                conn.execute(
                    "SELECT count(*) FROM request_engine.native_sessions "
                    "WHERE native_identity_id = %s AND status = 'active'",
                    (identity_id,),
                ).fetchone()
                == (1,)
            ),
            rejection_ok=lambda conn: (
                conn.execute(
                    "SELECT count(*) FROM request_engine.native_sessions "
                    "WHERE native_identity_id = %s",
                    (identity_id,),
                ).fetchone()
                == (0,)
            ),
        )

    if path == "rotation":
        new_credential_id = uuid4()
        params = {
            "native_identity_id": identity_id,
            "expected_credential_id": credential_id,
            "new_credential_id": new_credential_id,
            "new_verifier": hash_password(NEW_PASSWORD),
            "reason": "authority_gate_probe",
        }
        return PositivePath(
            key=path,
            authority_id=authority_id,
            identity_id=identity_id,
            call_sql=(
                "SELECT request_auth.rotate_native_password("
                "%(native_identity_id)s, %(expected_credential_id)s, %(new_credential_id)s, "
                "%(new_verifier)s, %(reason)s)"
            ),
            call_params=params,
            expect_success=lambda value: value is True,
            effect_ok=lambda conn: (
                conn.execute(
                    "SELECT status FROM request_engine.native_credentials WHERE id = %s",
                    (new_credential_id,),
                ).fetchone()
                == ("active",)
            ),
            rejection_ok=lambda conn: (
                conn.execute(
                    "SELECT count(*) FROM request_engine.native_credentials "
                    "WHERE native_identity_id = %s",
                    (identity_id,),
                ).fetchone()
                == (1,)
            ),
        )

    if path == "issuance":
        # A pre-existing pending proof must survive a rejected re-issuance.
        prior = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=login_handle
        )
        assert prior is not None
        token = issue_opaque_token()
        params = {
            "native_identity_id": identity_id,
            "recovery_id": token.token_id,
            "token_digest": token.digest,
            "token_fingerprint": token.fingerprint,
            "expires_at": datetime.now(UTC) + timedelta(minutes=30),
        }
        return PositivePath(
            key=path,
            authority_id=authority_id,
            identity_id=identity_id,
            call_sql=(
                "SELECT request_auth.create_native_recovery_intent("
                "%(native_identity_id)s, %(recovery_id)s, %(token_digest)s, "
                "%(token_fingerprint)s, %(expires_at)s)"
            ),
            call_params=params,
            expect_success=lambda value: value is True,
            effect_ok=lambda conn: (
                conn.execute(
                    "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
                    (token.token_id,),
                ).fetchone()
                == ("pending",)
            ),
            rejection_ok=lambda conn: (
                conn.execute(
                    "SELECT id, status FROM request_engine.native_recovery_intents "
                    "WHERE native_identity_id = %s ORDER BY id",
                    (identity_id,),
                ).fetchall()
                == [(prior.recovery_id, "pending")]
            ),
        )

    if path == "consumption":
        issued = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=login_handle
        )
        assert issued is not None
        parsed = parse_opaque_token(issued.raw_token)
        new_credential_id = uuid4()
        params = {
            "recovery_id": issued.recovery_id,
            "token_digest": digest_opaque_secret(parsed.secret),
            "new_credential_id": new_credential_id,
            "new_verifier": hash_password(NEW_PASSWORD),
        }
        return PositivePath(
            key=path,
            authority_id=authority_id,
            identity_id=identity_id,
            call_sql=(
                "SELECT request_auth.consume_native_recovery_intent("
                "%(recovery_id)s, %(token_digest)s, %(new_credential_id)s, %(new_verifier)s)"
            ),
            call_params=params,
            expect_success=lambda value: value == identity_id,
            effect_ok=lambda conn: (
                conn.execute(
                    "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
                    (issued.recovery_id,),
                ).fetchone()
                == ("consumed",)
            ),
            rejection_ok=lambda conn: (
                conn.execute(
                    "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
                    (issued.recovery_id,),
                ).fetchone()
                == ("pending",)
            ),
        )

    raise ValueError(f"unknown positive path {path!r}")
