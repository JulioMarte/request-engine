"""Atomic Instance claim and pending setup material (ADR 0014 P4)."""

import hashlib
import secrets
import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import hash_password

PgConnection = Connection[Any]
AppConnFactory = Callable[[], PgConnection]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]

PASSWORD = "instance claim proof password"


def _instance(admin_conn: PgConnection) -> tuple[UUID, UUID]:
    authority_id = uuid4()
    instance_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"claim-authority-{uuid4().hex}"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id, built_in_native_authority_id, built_in_workload_authority_id) "
        "VALUES (%s, %s, %s)",
        (instance_id, authority_id, uuid4()),
    )
    return instance_id, authority_id


async def _control(session_factory: SessionFactory, statement: str, params: dict[str, Any]) -> Any:
    async with session_factory() as session, session.begin():
        return (await session.execute(text(statement), params)).fetchone()


async def _create_setup_session(session_factory: SessionFactory) -> tuple[UUID, bytes]:
    token = secrets.token_bytes(32)
    session_id = uuid4()
    row = await _control(
        session_factory,
        "SELECT request_platform.create_setup_session("
        ":id, :digest, :fingerprint, 'interactive', 3600)",
        {
            "id": session_id,
            "digest": token,
            "fingerprint": hashlib.sha256(token).hexdigest()[:16],
        },
    )
    assert row is not None and row[0] == session_id
    return session_id, token


async def _pending_identity(
    session_factory: SessionFactory, *, setup_session_id: UUID, login_handle: str
) -> UUID:
    native_identity_id = uuid4()
    row = await _control(
        session_factory,
        "SELECT request_platform.set_setup_pending_identity(:identity, :setup, :handle, :verifier)",
        {
            "identity": native_identity_id,
            "setup": setup_session_id,
            "handle": login_handle,
            "verifier": hash_password(PASSWORD),
        },
    )
    assert row == (True,)
    return native_identity_id


def _pending_webauthn(admin_conn: PgConnection, *, setup_session_id: UUID) -> bytes:
    digest = secrets.token_bytes(32)
    admin_conn.execute(
        "INSERT INTO request_engine.webauthn_challenges "
        "(id, purpose, setup_session_id, challenge_digest, expires_at) "
        "VALUES (%s, 'registration', %s, %s, clock_timestamp() + interval '5 minutes')",
        (uuid4(), setup_session_id, digest),
    )
    return digest


async def _finalize_webauthn(
    session_factory: SessionFactory, *, digest: bytes, setup_session_id: UUID
) -> bool:
    row = await _control(
        session_factory,
        "SELECT request_auth.finalize_setup_webauthn_registration("
        ":digest, :row, :credential_id, :public_key, 0, :aaguid, false, false, true, :setup)",
        {
            "digest": digest,
            "row": uuid4(),
            "credential_id": secrets.token_bytes(32),
            "public_key": secrets.token_bytes(77),
            "aaguid": "00" * 16,
            "setup": setup_session_id,
        },
    )
    return row == (True,)


async def _recovery_codes(session_factory: SessionFactory, *, setup_session_id: UUID) -> None:
    digests = [hashlib.sha256(secrets.token_bytes(16)).digest() for _ in range(4)]
    row = await _control(
        session_factory,
        "SELECT request_auth.create_recovery_code_set(:set, NULL, :setup, :digests)",
        {"set": uuid4(), "setup": setup_session_id, "digests": digests},
    )
    assert row == (True,)


async def _ready_world(
    admin_conn: PgConnection,
    control_factory: SessionFactory,
    app_factory: SessionFactory,
    *,
    login_handle: str = "claim-owner@example.test",
) -> tuple[UUID, UUID]:
    _instance_id, _authority_id = _instance(admin_conn)
    setup_session_id, _token = await _create_setup_session(control_factory)
    identity_id = await _pending_identity(
        control_factory, setup_session_id=setup_session_id, login_handle=login_handle
    )
    digest = _pending_webauthn(admin_conn, setup_session_id=setup_session_id)
    assert await _finalize_webauthn(app_factory, digest=digest, setup_session_id=setup_session_id)
    await _recovery_codes(app_factory, setup_session_id=setup_session_id)
    return setup_session_id, identity_id


@pytest.mark.asyncio
async def test_claim_readiness_reflects_durable_facts(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
    command_session_factory: SessionFactory,
) -> None:
    setup_session_id, _identity_id = await _ready_world(
        admin_conn, platform_control_session_factory, command_session_factory
    )
    row = await _control(
        platform_control_session_factory,
        "SELECT setup_status, setup_usable, instance_state, has_identity, "
        "verified_webauthn_count, has_recovery_codes, policy_key "
        "FROM request_platform.read_claim_readiness(:setup)",
        {"setup": setup_session_id},
    )
    assert row is not None
    assert row[0] == "pending"
    assert row[1] is True
    assert row[2] == "unclaimed"
    assert row[3] is True
    assert row[4] == 1
    assert row[5] is True
    assert row[6] == "platform-owner-v1"


@pytest.mark.asyncio
async def test_finalize_claims_instance_atomically(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
    command_session_factory: SessionFactory,
) -> None:
    setup_session_id, identity_id = await _ready_world(
        admin_conn, platform_control_session_factory, command_session_factory
    )
    key = hashlib.sha256(b"claim-key").hexdigest()
    intent = hashlib.sha256(b"claim-intent").hexdigest()
    row = await _control(
        platform_control_session_factory,
        "SELECT instance_id, owner_principal_id, native_identity_id, "
        "setup_session_id, policy_key "
        "FROM request_platform.finalize_instance_claim("
        ":setup, :key, :intent, 'fresh-install', 'setup_session', NULL)",
        {"setup": setup_session_id, "key": key, "intent": intent},
    )
    assert row is not None
    instance_id, owner_principal_id, claimed_identity_id, claimed_setup_id, policy_key = row
    assert claimed_identity_id == identity_id
    assert claimed_setup_id == setup_session_id
    assert policy_key == "platform-owner-v1"

    # Permanent identity + credential + authenticator exist.
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities WHERE id = %s",
        (identity_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s AND status = 'active'",
        (identity_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.webauthn_credentials "
        "WHERE native_identity_id = %s AND status = 'active'",
        (identity_id,),
    ).fetchone() == (1,)
    # Platform principal + active binding.
    assert admin_conn.execute(
        "SELECT principal_plane, principal_kind, active FROM request_engine.principals "
        "WHERE id = %s",
        (owner_principal_id,),
    ).fetchone() == ("platform", "human", True)
    assert admin_conn.execute(
        "SELECT status, organization_id FROM request_engine.identity_bindings "
        "WHERE principal_id = %s",
        (owner_principal_id,),
    ).fetchone() == ("active", None)
    # Exact platform-owner-v1 grant set.
    grants = {
        row[0]
        for row in admin_conn.execute(
            "SELECT capability_key FROM request_engine.principal_authority_grants "
            "WHERE principal_id = %s AND status = 'active'",
            (owner_principal_id,),
        ).fetchall()
    }
    assert grants == {
        "platform.principal.provision",
        "platform.tenant_provisioner.provision",
        "platform.recovery_operator.provision",
        "organization.provision",
        "platform.identity.recover",
        "platform.identity.read",
        "platform.identity.recovery_approve",
        "platform.identity.provision",
        "platform.owner.read",
        "platform.owner.provision",
        "platform.owner.manage_lifecycle",
        "platform.provisioner.read",
        "platform.provisioner.manage_lifecycle",
    }
    # Recovery codes promoted to the identity; instance claimed; setup consumed.
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.recovery_code_sets "
        "WHERE native_identity_id = %s AND status = 'active'",
        (identity_id,),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        "SELECT state, initial_owner_principal_id FROM request_engine.platform_instance "
        "WHERE id = %s",
        (instance_id,),
    ).fetchone() == ("claimed", owner_principal_id)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.setup_sessions WHERE id = %s",
        (setup_session_id,),
    ).fetchone() == ("consumed",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_installation_claim_facts "
        "WHERE instance_id = %s",
        (instance_id,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_setup_closes_after_claim(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
    command_session_factory: SessionFactory,
) -> None:
    setup_session_id, _identity_id = await _ready_world(
        admin_conn, platform_control_session_factory, command_session_factory
    )
    await _control(
        platform_control_session_factory,
        "SELECT instance_id FROM request_platform.finalize_instance_claim("
        ":setup, :key, :intent, 'fresh-install', 'setup_session', NULL)",
        {
            "setup": setup_session_id,
            "key": hashlib.sha256(b"k2").hexdigest(),
            "intent": hashlib.sha256(b"i2").hexdigest(),
        },
    )
    with pytest.raises(DBAPIError):
        await _control(
            platform_control_session_factory,
            "SELECT request_platform.create_setup_session("
            ":id, :digest, :fingerprint, 'interactive', 3600)",
            {
                "id": uuid4(),
                "digest": secrets.token_bytes(32),
                "fingerprint": uuid4().hex[:16],
            },
        )
    readiness = await _control(
        platform_control_session_factory,
        "SELECT setup_usable, instance_state FROM request_platform.read_claim_readiness(:setup)",
        {"setup": setup_session_id},
    )
    assert readiness is not None
    assert readiness[0] is False
    assert readiness[1] == "claimed"


@pytest.mark.asyncio
async def test_exact_finalize_replay_returns_same_result(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
    command_session_factory: SessionFactory,
) -> None:
    setup_session_id, _identity_id = await _ready_world(
        admin_conn, platform_control_session_factory, command_session_factory
    )
    key = hashlib.sha256(b"replay-key").hexdigest()
    intent = hashlib.sha256(b"replay-intent").hexdigest()
    args = {"setup": setup_session_id, "key": key, "intent": intent}
    statement = (
        "SELECT owner_principal_id, native_identity_id "
        "FROM request_platform.finalize_instance_claim("
        ":setup, :key, :intent, 'fresh-install', 'setup_session', NULL)"
    )
    first = await _control(platform_control_session_factory, statement, args)
    second = await _control(platform_control_session_factory, statement, args)
    assert first == second
    # A different intent under the same key must fail closed.
    with pytest.raises(DBAPIError):
        await _control(
            platform_control_session_factory,
            statement,
            {**args, "intent": hashlib.sha256(b"other-intent").hexdigest()},
        )


@pytest.mark.asyncio
async def test_finalize_requires_verified_webauthn(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
    command_session_factory: SessionFactory,
) -> None:
    _instance(admin_conn)
    setup_session_id, _token = await _create_setup_session(platform_control_session_factory)
    await _pending_identity(
        platform_control_session_factory,
        setup_session_id=setup_session_id,
        login_handle="no-passkey@example.test",
    )
    await _recovery_codes(command_session_factory, setup_session_id=setup_session_id)
    with pytest.raises(DBAPIError):
        await _control(
            platform_control_session_factory,
            "SELECT request_platform.finalize_instance_claim("
            ":setup, :key, :intent, 'fresh-install', 'setup_session', NULL)",
            {
                "setup": setup_session_id,
                "key": hashlib.sha256(b"nw").hexdigest(),
                "intent": hashlib.sha256(b"ni").hexdigest(),
            },
        )
    assert admin_conn.execute("SELECT state FROM request_engine.platform_instance").fetchone() == (
        "unclaimed",
    )


@pytest.mark.asyncio
async def test_webauthn_completion_requires_owning_setup_session(
    admin_conn: PgConnection,
    platform_control_session_factory: SessionFactory,
    command_session_factory: SessionFactory,
) -> None:
    _instance(admin_conn)
    session_a, _token_a = await _create_setup_session(platform_control_session_factory)
    session_b, _token_b = await _create_setup_session(platform_control_session_factory)
    digest = _pending_webauthn(admin_conn, setup_session_id=session_a)

    # A valid bearer for a different concurrent ceremony cannot complete it.
    assert not await _finalize_webauthn(
        command_session_factory, digest=digest, setup_session_id=session_b
    )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.webauthn_challenges WHERE challenge_digest = %s",
        (digest,),
    ).fetchone() == ("pending",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.setup_pending_webauthn_credential "
        "WHERE setup_session_id = %s",
        (session_a,),
    ).fetchone() == (0,)

    # The owning SetupSession completes it and consumes the challenge.
    assert await _finalize_webauthn(
        command_session_factory, digest=digest, setup_session_id=session_a
    )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.webauthn_challenges WHERE challenge_digest = %s",
        (digest,),
    ).fetchone() == ("consumed",)


def test_concurrent_finalize_has_exactly_one_winner(
    admin_conn: PgConnection,
    platform_control_conn_factory: AppConnFactory,
) -> None:
    instance_id, _authority_id = _instance(admin_conn)
    setup_session_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.setup_sessions "
        "(id, instance_id, token_digest, token_fingerprint, mode, expires_at) "
        "VALUES (%s, %s, %s, %s, 'interactive', clock_timestamp() + interval '1 hour')",
        (setup_session_id, instance_id, secrets.token_bytes(32), uuid4().hex[:16]),
    )
    identity_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.setup_pending_identity "
        "(id, setup_session_id, login_handle, verifier) VALUES (%s, %s, %s, %s)",
        (identity_id, setup_session_id, "race@example.test", hash_password(PASSWORD)),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.setup_pending_webauthn_credential "
        "(id, setup_session_id, credential_id, public_key, aaguid) "
        "VALUES (%s, %s, %s, %s, %s)",
        (uuid4(), setup_session_id, secrets.token_bytes(32), secrets.token_bytes(77), "00" * 16),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.recovery_code_sets(id, setup_session_id) VALUES (%s, %s)",
        (uuid4(), setup_session_id),
    )

    args = (
        setup_session_id,
        hashlib.sha256(b"race-key").hexdigest(),
        hashlib.sha256(b"race-intent").hexdigest(),
        "fresh-install",
        "setup_session",
        None,
    )
    statement = (
        "SELECT owner_principal_id FROM request_platform.finalize_instance_claim("
        "%s, %s, %s, %s, %s, %s)"
    )
    winner = platform_control_conn_factory()
    winner.execute(statement, args)
    winner_pid_row = winner.execute("SELECT pg_backend_pid()").fetchone()
    assert winner_pid_row is not None
    winner_pid = int(winner_pid_row[0])

    outcome: dict[str, object] = {}

    def _contend() -> None:
        try:
            outcome["row"] = platform_control_conn_factory().execute(statement, args).fetchone()
        except Exception as exc:  # pragma: no cover - surfaced via assertion
            outcome["error"] = exc

    thread = threading.Thread(target=_contend)
    thread.start()
    blocked = _wait_for_any_lock(admin_conn, winner_pid)
    winner.commit()
    thread.join(timeout=20)
    assert blocked
    assert not thread.is_alive()
    # The loser either replays the same receipt (exact replay) or conflicts.
    assert "error" in outcome or outcome["row"] is not None
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_installation_claim_facts "
        "WHERE instance_id = %s",
        (instance_id,),
    ).fetchone() == (1,)


def _wait_for_any_lock(admin_conn: PgConnection, blocker_pid: int) -> bool:
    import time

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        row = admin_conn.execute(
            "SELECT pid FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
            "AND %s = ANY(pg_blocking_pids(pid))",
            (blocker_pid,),
        ).fetchone()
        if row is not None:
            return True
        time.sleep(0.05)
    return False
