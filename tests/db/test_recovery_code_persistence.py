"""Recovery code set persistence, single-use and race proofs (plan §5.7)."""

import hashlib
import secrets
import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from native_authority_gate_support import wait_for_lock_wait
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.recovery_code_store import PostgresRecoveryCodeStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import CredentialInvalid
from request_engine.platform.security.recovery_codes import (
    NativeRecoveryCodeService,
    RecoveryCodeInvalid,
    recovery_code_digest,
)

PgConnection = Connection[Any]
AppConnFactory = Callable[[], PgConnection]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

PASSWORD = "recovery code proof password"


async def _identity(admin_conn: PgConnection, command_session_factory: SessionFactory) -> UUID:
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"recovery-proof-{uuid4().hex}"),
    )
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"recovery-{uuid4().hex}@example.test",
        password=PASSWORD,
    )
    return enrollment.native_identity_id


def _service(session_factory: SessionFactory) -> NativeRecoveryCodeService:
    return NativeRecoveryCodeService(store=PostgresRecoveryCodeStore(session_factory), code_count=4)


@pytest.mark.asyncio
async def test_issue_persists_digests_only_and_is_single_use(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _identity(admin_conn, command_session_factory)
    service = _service(command_session_factory)

    codes = await service.issue_for_identity(native_identity_id=identity_id)
    assert len(codes) == 4

    rows = admin_conn.execute(
        "SELECT code.code_digest FROM request_engine.recovery_codes AS code "
        "JOIN request_engine.recovery_code_sets AS code_set ON code_set.id = code.set_id "
        "WHERE code_set.native_identity_id = %s",
        (identity_id,),
    ).fetchall()
    assert len(rows) == 4
    stored = {bytes(row[0]) for row in rows}
    assert all(len(digest) == 32 for digest in stored)
    assert stored == {recovery_code_digest(code) for code in codes}
    assert all(code.encode("ascii") not in stored for code in codes)

    consumed = await service.consume(code=codes[0])
    assert consumed is not None
    assert consumed.native_identity_id == identity_id
    # Single use: the same code can never be consumed twice.
    assert await service.consume(code=codes[0]) is None

    summary = await service.summary(native_identity_id=identity_id)
    assert len(summary) == 1
    assert summary[0].total_codes == 4
    assert summary[0].remaining_codes == 3


@pytest.mark.asyncio
async def test_offline_code_atomically_resets_password_and_revokes_sessions(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    login_handle = f"offline-recovery-{uuid4().hex}@example.test"
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"offline-recovery-{uuid4().hex}"),
    )
    runtime = build_native_auth_runtime(command_session_factory)
    enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    old_session = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=PASSWORD,
    )
    service = _service(command_session_factory)
    codes = await service.issue_for_identity(native_identity_id=enrollment.native_identity_id)

    new_password = "new offline recovery password"
    recovered_identity = await service.recover_password(
        code=codes[0],
        new_password=new_password,
    )
    assert recovered_identity == enrollment.native_identity_id

    with pytest.raises(CredentialInvalid):
        await runtime.service.authenticate_password(
            identity_authority_id=authority_id,
            login_handle=login_handle,
            password=PASSWORD,
        )
    new_session = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=login_handle,
        password=new_password,
    )
    assert new_session.native_identity_id == enrollment.native_identity_id

    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_sessions WHERE id = %s",
        (old_session.session_id,),
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s AND kind = 'password' AND status = 'active'",
        (enrollment.native_identity_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.recovery_codes "
        "WHERE code_digest = %s AND used_at IS NOT NULL",
        (recovery_code_digest(codes[0]),),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT capability_key FROM request_engine.platform_recovery_code_facts "
        "WHERE native_identity_id = %s AND event_kind = 'code_consumed' "
        "ORDER BY created_at DESC LIMIT 1",
        (enrollment.native_identity_id,),
    ).fetchone() == ("platform.recovery_codes.password_reset",)
    recovery_state = admin_conn.execute(
        "SELECT state, recovery_epoch, last_recovery_method, completed_at "
        "FROM request_engine.native_identity_recovery_state "
        "WHERE native_identity_id = %s",
        (enrollment.native_identity_id,),
    ).fetchone()
    assert recovery_state is not None
    assert recovery_state[:3] == (
        "recovery_restricted",
        1,
        "offline_recovery_code",
    )
    readiness = await service.readiness(native_identity_id=enrollment.native_identity_id)
    assert readiness.recovery_restricted is True
    assert readiness.recovery_epoch == 1
    assert readiness.remaining_codes == 3

    with pytest.raises(RecoveryCodeInvalid):
        await service.recover_password(code=codes[0], new_password="another valid password")


@pytest.mark.asyncio
async def test_rotation_invalidates_prior_codes(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _identity(admin_conn, command_session_factory)
    service = _service(command_session_factory)

    first = await service.issue_for_identity(native_identity_id=identity_id)
    second = await service.issue_for_identity(native_identity_id=identity_id)

    assert await service.consume(code=first[1]) is None
    consumed = await service.consume(code=second[0])
    assert consumed is not None

    summary = await service.summary(native_identity_id=identity_id)
    assert [item.status for item in summary] == ["active", "revoked"]
    assert summary[0].remaining_codes == 3


@pytest.mark.asyncio
async def test_setup_scoped_set_promotes_to_identity(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _identity(admin_conn, command_session_factory)
    instance_id = uuid4()
    setup_session_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id, built_in_native_authority_id, built_in_workload_authority_id) "
        "VALUES (%s, %s, %s)",
        (instance_id, uuid4(), uuid4()),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.setup_sessions "
        "(id, instance_id, token_digest, token_fingerprint, mode, expires_at) "
        "VALUES (%s, %s, %s, %s, 'interactive', clock_timestamp() + interval '1 hour')",
        (setup_session_id, instance_id, secrets.token_bytes(32), uuid4().hex[:16]),
    )
    service = _service(command_session_factory)

    codes = await service.issue_for_setup_session(setup_session_id=setup_session_id)
    # A setup-scoped set is not yet consumable as a runtime credential.
    assert await service.consume(code=codes[0]) is None

    set_row = admin_conn.execute(
        "SELECT id FROM request_engine.recovery_code_sets WHERE setup_session_id = %s",
        (setup_session_id,),
    ).fetchone()
    assert set_row is not None
    set_id = UUID(str(set_row[0]))
    assert await service.promote(set_id=set_id, native_identity_id=identity_id)
    consumed = await service.consume(code=codes[1])
    assert consumed is not None
    assert consumed.native_identity_id == identity_id


@pytest.mark.asyncio
async def test_recovery_facts_are_emitted_and_append_only(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _identity(admin_conn, command_session_factory)
    service = _service(command_session_factory)
    codes = await service.issue_for_identity(native_identity_id=identity_id)
    await service.consume(code=codes[0])

    kinds = admin_conn.execute(
        "SELECT event_kind FROM request_engine.platform_recovery_code_facts "
        "WHERE native_identity_id = %s ORDER BY created_at",
        (identity_id,),
    ).fetchall()
    assert [row[0] for row in kinds] == ["set_created", "code_consumed"]
    # The fact table is append-only even for a privileged admin connection.
    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            "DELETE FROM request_engine.platform_recovery_code_facts WHERE native_identity_id = %s",
            (identity_id,),
        )


def test_recovery_tables_are_not_directly_readable(admin_conn: PgConnection) -> None:
    for table in (
        "request_engine.recovery_code_sets",
        "request_engine.recovery_codes",
        "request_engine.platform_recovery_code_facts",
        "request_engine.native_identity_recovery_state",
        "request_engine.native_identity_recovery_facts",
    ):
        assert admin_conn.execute(
            "SELECT has_table_privilege('request_engine_app', %s, 'SELECT')", (table,)
        ).fetchone() == (False,)


_RECOVERY_FUNCTIONS = (
    "create_recovery_code_set(uuid, uuid, uuid, bytea[])",
    "consume_recovery_code(bytea)",
    "consume_recovery_code_and_rotate_password(bytea, uuid, text)",
    "promote_recovery_code_set(uuid, uuid)",
    "revoke_recovery_code_set(uuid, text)",
    "read_recovery_code_set_summary(uuid)",
    "read_native_recovery_readiness(uuid)",
    "complete_native_recovery(uuid)",
)


def test_recovery_functions_are_least_privilege(admin_conn: PgConnection) -> None:
    for signature in _RECOVERY_FUNCTIONS:
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


def test_concurrent_consume_has_exactly_one_winner(
    admin_conn: PgConnection,
    app_role_conn_factory: AppConnFactory,
) -> None:
    identity_id = uuid4()
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"recovery-race-{uuid4().hex}"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities(id, identity_authority_id, login_handle) "
        "VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"race-{uuid4().hex}@example.test"),
    )
    set_id = uuid4()
    digest = hashlib.sha256(b"race-recovery-code").digest()
    admin_conn.execute(
        "INSERT INTO request_engine.recovery_code_sets(id, native_identity_id) VALUES (%s, %s)",
        (set_id, identity_id),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.recovery_codes(set_id, code_digest) VALUES (%s, %s)",
        (set_id, digest),
    )

    winner = app_role_conn_factory()
    winner.execute(
        "SELECT native_identity_id FROM request_auth.consume_recovery_code(%s)", (digest,)
    )
    winner_pid = _backend_pid(winner)

    contender = app_role_conn_factory()
    contender_pid = _backend_pid(contender)
    outcome: dict[str, object] = {}

    def _contend() -> None:
        try:
            outcome["row"] = contender.execute(
                "SELECT native_identity_id FROM request_auth.consume_recovery_code(%s)",
                (digest,),
            ).fetchone()
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            outcome["error"] = exc

    thread = threading.Thread(target=_contend)
    thread.start()
    assert wait_for_lock_wait(admin_conn, contender_pid, blocker_pid=winner_pid)
    winner.commit()
    thread.join(timeout=20)
    assert not thread.is_alive()
    assert "error" not in outcome
    assert outcome["row"] is None
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.recovery_codes WHERE used_at IS NOT NULL "
        "AND set_id = %s",
        (set_id,),
    ).fetchone() == (1,)


def _backend_pid(conn: PgConnection) -> int:
    row = conn.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_repeated_offline_recovery_advances_epoch_without_authority_side_effects(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    identity_id = await _identity(admin_conn, command_session_factory)
    service = _service(command_session_factory)

    first_codes = await service.issue_for_identity(native_identity_id=identity_id)
    assert (
        await service.recover_password(
            code=first_codes[0],
            new_password="first repeated recovery password",
        )
        == identity_id
    )
    first = await service.readiness(native_identity_id=identity_id)
    assert first.recovery_state == "recovery_restricted"
    assert first.recovery_epoch == 1

    second_codes = await service.issue_for_identity(native_identity_id=identity_id)
    assert (
        await service.recover_password(
            code=second_codes[0],
            new_password="second repeated recovery password",
        )
        == identity_id
    )
    second = await service.readiness(native_identity_id=identity_id)
    assert second.recovery_state == "recovery_restricted"
    assert second.recovery_epoch == 2

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identity_recovery_facts "
        "WHERE native_identity_id = %s AND event_kind = 'recovery_started'",
        (identity_id,),
    ).fetchone() == (2,)
    assert admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (0,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings"
    ).fetchone() == (0,)


def test_recovery_posture_facts_are_append_only(admin_conn: PgConnection) -> None:
    identity_id = uuid4()
    authority_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"posture-append-only-{uuid4().hex}"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities(id, identity_authority_id, login_handle) "
        "VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"posture-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_identity_recovery_facts "
        "(native_identity_id, event_kind, recovery_epoch, recovery_method) "
        "VALUES (%s, 'recovery_started', 1, 'offline_recovery_code')",
        (identity_id,),
    )
    with pytest.raises(psycopg.Error):
        admin_conn.execute(
            "UPDATE request_engine.native_identity_recovery_facts "
            "SET recovery_method = 'tampered' WHERE native_identity_id = %s",
            (identity_id,),
        )
