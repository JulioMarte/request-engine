"""Authority SHARE lock winners, commitment order and non-serialization proofs."""

import asyncio
import threading
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import (
    NEW_PASSWORD,
    POSITIVE_PATHS,
    auth_fingerprint,
    authority_status,
    insert_authority,
    prepare_path,
    session_token_params,
    set_authority_status,
    wait_for_lock_wait,
)
from platform_provisioning_support import (
    platform_grant,
    platform_principal,
    principal_revision,
)
from psycopg import Connection

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.adapters.db.native_platform_provisioning_commands import (
    PostgresNativePlatformProvisioningCommands,
)
from request_engine.modules.tenancy.application.commands.native_platform_provisioning import (
    NativePlatformProvisioningInvalid,
    ProvisionNativePlatformProvisionerCommand,
)
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import hash_password
from request_engine.platform.security.native_human_auth import NativeHumanAuthService
from request_engine.platform.security.platform_context import PlatformActorContext

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
    pytest.mark.concurrency,
]

_SESSION_SQL: LiteralString = (
    "SELECT request_auth.create_native_session("
    "%(native_identity_id)s, %(credential_id)s, %(session_id)s, "
    "%(token_digest)s, %(token_fingerprint)s, %(expires_at)s)"
)
_SUSPEND_SQL: LiteralString = (
    "UPDATE request_engine.identity_authorities "
    "SET status = 'disabled', revision = revision + 1 WHERE id = %s"
)
_LOCK_COMMITMENT_SQL: LiteralString = (
    "SELECT request_auth.lock_credentialed_native_identity(%s, %s)"
)


def _invoke(
    conn: PgConnection,
    statement: LiteralString,
    params: Any,
    outcome: list[object],
) -> None:
    try:
        row = conn.execute(statement, params).fetchone()
        outcome.append(row[0] if row is not None else None)
    except Exception as exc:  # noqa: BLE001
        outcome.append(exc)


def _suspend(
    conn: PgConnection,
    authority_id: UUID,
    outcome: list[object],
) -> None:
    try:
        cursor = conn.execute(_SUSPEND_SQL, (authority_id,))
        conn.commit()
        outcome.append(cursor.rowcount)
    except Exception as exc:  # noqa: BLE001
        outcome.append(exc)


async def _wait_for_platform_control_lock(
    admin_conn: PgConnection, *, wait_seconds: float = 15.0
) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while loop.time() < deadline:
        row = admin_conn.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE usename LIKE 're_platform_control_%' AND wait_event_type = 'Lock'"
        ).fetchone()
        if row == (1,):
            return True
        await asyncio.sleep(0.05)
    return False


def _command_world(
    admin_conn: PgConnection,
    *,
    authority_id: UUID,
    identity_id: UUID,
) -> tuple[PlatformActorContext, ProvisionNativePlatformProvisionerCommand]:
    creator = platform_principal(admin_conn)
    capabilities = ("platform.tenant_provisioner.provision", "organization.provision")
    for capability in capabilities:
        platform_grant(admin_conn, principal_id=creator, capability=capability, delegable=True)
    actor = PlatformActorContext(
        principal_id=creator,
        authority_revision=principal_revision(admin_conn, creator),
        capabilities=frozenset(capabilities),
    )
    command = ProvisionNativePlatformProvisionerCommand(
        identity_authority_id=authority_id,
        native_identity_id=identity_id,
        provenance_reference=f"deployment:{uuid4().hex}",
        idempotency_key=f"authority-gate-{uuid4().hex}",
    )
    return actor, command


@pytest.mark.asyncio
@pytest.mark.parametrize("path", POSITIVE_PATHS)
async def test_committed_suspension_wins_and_contender_rejects(
    path: str,
    admin_conn: PgConnection,
    pg_conninfo: str,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    world = await prepare_path(path, admin_conn, service)
    before = auth_fingerprint(admin_conn, world.identity_id)

    disabler = PgConnection.connect(pg_conninfo)
    outcome: list[object] = []
    try:
        disabler.execute(_SUSPEND_SQL, (world.authority_id,))
        thread = threading.Thread(
            target=_invoke,
            args=(app_role_conn, world.call_sql, world.call_params, outcome),
        )
        thread.start()
        assert wait_for_lock_wait(
            admin_conn, app_role_conn.info.backend_pid, blocker_pid=disabler.info.backend_pid
        ), f"{path} contender never queued on the authority lock"
        disabler.commit()
        thread.join(15)
        assert not thread.is_alive()
        assert len(outcome) == 1 and not isinstance(outcome[0], Exception)
        # Observe committed rejection, not a rollback manufactured by the test.
        app_role_conn.commit()
    finally:
        disabler.close()
        app_role_conn.rollback()

    assert outcome and not world.expect_success(outcome[0])
    if path == "enrollment":
        # The committed loser must observe authority-unavailable, not a duplicate handle.
        assert outcome[0] is None, "suspended-authority enrollment must not read as duplicate"
    assert auth_fingerprint(admin_conn, world.identity_id) == before
    assert world.rejection_ok(admin_conn)
    assert authority_status(admin_conn, world.authority_id)[0] == "disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", POSITIVE_PATHS)
async def test_inflight_positive_transaction_wins_and_suspension_waits(
    path: str,
    admin_conn: PgConnection,
    pg_conninfo: str,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    world = await prepare_path(path, admin_conn, service)

    result = app_role_conn.execute(world.call_sql, world.call_params).fetchone()
    assert result is not None and world.expect_success(result[0])

    disabler = PgConnection.connect(pg_conninfo)
    outcome: list[object] = []
    try:
        thread = threading.Thread(target=_suspend, args=(disabler, world.authority_id, outcome))
        thread.start()
        assert wait_for_lock_wait(
            admin_conn, disabler.info.backend_pid, blocker_pid=app_role_conn.info.backend_pid
        ), f"suspension never waited on the in-flight {path} transaction"
        app_role_conn.commit()
        thread.join(15)
        assert not thread.is_alive()
    finally:
        app_role_conn.rollback()
        disabler.close()

    assert outcome == [1]
    assert authority_status(admin_conn, world.authority_id)[0] == "disabled"
    assert world.effect_ok(admin_conn)


@pytest.mark.asyncio
async def test_rolled_back_suspension_allows_positive_transaction(
    admin_conn: PgConnection,
    pg_conninfo: str,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    world = await prepare_path("session", admin_conn, service)

    disabler = PgConnection.connect(pg_conninfo)
    outcome: list[object] = []
    try:
        disabler.execute(_SUSPEND_SQL, (world.authority_id,))
        thread = threading.Thread(
            target=_invoke,
            args=(app_role_conn, world.call_sql, world.call_params, outcome),
        )
        thread.start()
        assert wait_for_lock_wait(admin_conn, app_role_conn.info.backend_pid)
        disabler.rollback()
        thread.join(15)
        assert not thread.is_alive()
        app_role_conn.commit()
    finally:
        app_role_conn.rollback()
        disabler.close()

    assert outcome == [True]
    assert authority_status(admin_conn, world.authority_id)[0] == "active"
    assert world.effect_ok(admin_conn)


@pytest.mark.asyncio
async def test_suspended_authority_blocks_credentialed_commitment(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"gate-commitment-{uuid4().hex}@example.test",
        password="native authority gate password",
    )
    actor, command = _command_world(
        admin_conn, authority_id=authority_id, identity_id=enrollment.native_identity_id
    )
    set_authority_status(admin_conn, authority_id, "disabled")

    commands = PostgresNativePlatformProvisioningCommands(platform_control_session_factory)
    with pytest.raises(NativePlatformProvisioningInvalid):
        await commands.provision_native_platform_provisioner(actor, command)

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings"
    ).fetchone() == (0,)
    assert admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants"
    ).fetchone() == (2,)


@pytest.mark.asyncio
async def test_commitment_waits_for_rotation_then_succeeds(
    admin_conn: PgConnection,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"gate-commit-rotation-{uuid4().hex}@example.test",
        password="native authority gate password",
    )
    actor, command = _command_world(
        admin_conn, authority_id=authority_id, identity_id=enrollment.native_identity_id
    )
    rotated = app_role_conn.execute(
        "SELECT request_auth.rotate_native_password(%s, %s, %s, %s, %s)",
        (
            enrollment.native_identity_id,
            enrollment.credential_id,
            uuid4(),
            hash_password(NEW_PASSWORD),
            "gate_probe",
        ),
    ).fetchone()
    assert rotated == (True,)

    commands = PostgresNativePlatformProvisioningCommands(platform_control_session_factory)
    task = asyncio.create_task(commands.provision_native_platform_provisioner(actor, command))
    assert await _wait_for_platform_control_lock(admin_conn), (
        "commitment never waited for the in-flight rotation"
    )
    app_role_conn.commit()
    result = await asyncio.wait_for(task, timeout=15)
    app_role_conn.rollback()

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings WHERE id = %s",
        (result.binding_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s AND status = 'active'",
        (enrollment.native_identity_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_commitment_waits_for_identity_disable_then_fails_closed(
    admin_conn: PgConnection,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"gate-commit-disable-{uuid4().hex}@example.test",
        password="native authority gate password",
    )
    actor, command = _command_world(
        admin_conn, authority_id=authority_id, identity_id=enrollment.native_identity_id
    )
    disabled = app_role_conn.execute(
        "SELECT request_auth.disable_native_identity(%s, %s)",
        (enrollment.native_identity_id, "gate_probe"),
    ).fetchone()
    assert disabled == (True,)

    commands = PostgresNativePlatformProvisioningCommands(platform_control_session_factory)
    task = asyncio.create_task(commands.provision_native_platform_provisioner(actor, command))
    assert await _wait_for_platform_control_lock(admin_conn), (
        "commitment never waited for the in-flight identity disable"
    )
    app_role_conn.commit()
    with pytest.raises(NativePlatformProvisioningInvalid):
        await asyncio.wait_for(task, timeout=15)
    app_role_conn.rollback()

    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings"
    ).fetchone() == (0,)
    assert admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants"
    ).fetchone() == (2,)


@pytest.mark.asyncio
async def test_commitment_holder_blocks_rotation(
    admin_conn: PgConnection,
    pg_conninfo: str,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"gate-holder-{uuid4().hex}@example.test",
        password="native authority gate password",
    )

    holder = PgConnection.connect(pg_conninfo)
    outcome: list[object] = []
    try:
        holder.execute("SET ROLE request_platform_control_definer")
        locked = holder.execute(
            _LOCK_COMMITMENT_SQL, (authority_id, enrollment.native_identity_id)
        ).fetchone()
        assert locked == (True,)

        rotation = threading.Thread(
            target=_invoke,
            args=(
                app_role_conn,
                "SELECT request_auth.rotate_native_password(%s, %s, %s, %s, %s)",
                (
                    enrollment.native_identity_id,
                    enrollment.credential_id,
                    uuid4(),
                    hash_password(NEW_PASSWORD),
                    "gate_probe",
                ),
                outcome,
            ),
        )
        rotation.start()
        assert wait_for_lock_wait(admin_conn, app_role_conn.info.backend_pid)
        holder.commit()
        rotation.join(15)
        assert not rotation.is_alive()
    finally:
        app_role_conn.rollback()
        holder.close()

    assert outcome == [True]
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s AND status = 'active'",
        (enrollment.native_identity_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_authority_then_identity_disable_does_not_deadlock_commitment(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    enrollment = await build_native_auth_runtime(
        command_session_factory
    ).service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"gate-deadlock-{uuid4().hex}@example.test",
        password="native authority gate password",
    )

    blocker = PgConnection.connect(pg_conninfo)
    commitment = PgConnection.connect(pg_conninfo)
    outcome: list[object] = []
    try:
        blocker.execute(_SUSPEND_SQL, (authority_id,))
        commitment.execute("SET ROLE request_platform_control_definer")
        thread = threading.Thread(
            target=_invoke,
            args=(
                commitment,
                _LOCK_COMMITMENT_SQL,
                (authority_id, enrollment.native_identity_id),
                outcome,
            ),
        )
        thread.start()
        assert wait_for_lock_wait(admin_conn, commitment.info.backend_pid)
        # Same admin transaction now disables the identity: with authority-first
        # ordering the commitment holds no identity lock, so this cannot deadlock.
        disabled = blocker.execute(
            "SELECT request_auth.disable_native_identity(%s, %s)",
            (enrollment.native_identity_id, "gate_probe"),
        ).fetchone()
        assert disabled == (True,)
        blocker.commit()
        thread.join(15)
        assert not thread.is_alive()
    finally:
        commitment.close()
        blocker.close()

    assert outcome == [False]
    assert authority_status(admin_conn, authority_id)[0] == "disabled"


@pytest.mark.asyncio
async def test_same_authority_identities_are_not_serialized(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn_factory: Any,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    first = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"gate-shared-a-{uuid4().hex}@example.test",
        password="native authority gate password",
    )
    second = await service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"gate-shared-b-{uuid4().hex}@example.test",
        password="native authority gate password",
    )
    conn_a = app_role_conn_factory()
    conn_b = app_role_conn_factory()
    try:
        first_params = session_token_params(first.native_identity_id, first.credential_id)
        second_params = session_token_params(second.native_identity_id, second.credential_id)
        assert conn_a.execute(_SESSION_SQL, first_params).fetchone() == (True,)
        conn_b.execute("SET statement_timeout = '5s'")
        assert conn_b.execute(_SESSION_SQL, second_params).fetchone() == (True,)
        conn_a.commit()
        conn_b.commit()
    finally:
        conn_a.rollback()
        conn_b.rollback()


@pytest.mark.asyncio
async def test_other_authority_operations_are_unaffected_by_uncommitted_suspension(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command_session_factory: SessionFactory,
    app_role_conn_factory: Any,
) -> None:
    suspended_authority = insert_authority(admin_conn)
    active_authority = insert_authority(admin_conn)
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(command_session_factory))
    enrollment = await service.enroll_password_identity(
        identity_authority_id=active_authority,
        login_handle=f"gate-other-{uuid4().hex}@example.test",
        password="native authority gate password",
    )
    blocker = PgConnection.connect(pg_conninfo)
    contender = app_role_conn_factory()
    try:
        blocker.execute(_SUSPEND_SQL, (suspended_authority,))
        contender.execute("SET statement_timeout = '5s'")
        params = session_token_params(enrollment.native_identity_id, enrollment.credential_id)
        assert contender.execute(_SESSION_SQL, params).fetchone() == (True,)
        blocker.rollback()
        contender.commit()
    finally:
        blocker.rollback()
        contender.rollback()
        blocker.close()
