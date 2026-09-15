"""Governed global native-identity disable: terminal, continuity, replay, authority."""

import hashlib
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from agent_governance_support import provision_root
from native_authority_gate_support import insert_authority
from platform_provisioning_support import platform_grant, platform_principal, principal_revision
from psycopg import Connection, Error

from request_engine.platform.security.native_auth import hash_password

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]

PASSWORD = "correct horse battery staple"
_DISABLE: LiteralString = (
    "SELECT * FROM request_platform.disable_native_identity("
    "CAST(%s AS uuid), CAST(%s AS bigint), CAST(%s AS text), CAST(%s AS text), "
    "CAST(%s AS text), CAST(%s AS text))"
)


def _digest() -> str:
    return hashlib.sha256(uuid4().hex.encode("utf-8")).hexdigest()


def _set_actor(conn: PgConnection, actor: UUID, *, revision: int | None = None) -> None:
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(actor),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(principal_revision(conn, actor) if revision is None else revision),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authentication_method', 'native_session', false)"
    )
    conn.execute(
        "SELECT set_config('request_engine.correlation_id', %s, false)",
        (str(uuid4()),),
    )


def _native_identity(conn: PgConnection) -> tuple[UUID, UUID, UUID]:
    authority_id = insert_authority(conn)
    identity_id = uuid4()
    credential_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"disable-{uuid4().hex}@example.test"),
    )
    conn.execute(
        "INSERT INTO request_engine.native_credentials "
        "(id, native_identity_id, verifier) VALUES (%s, %s, %s)",
        (credential_id, identity_id, hash_password(PASSWORD)),
    )
    return authority_id, identity_id, credential_id


def _operator(conn: PgConnection, *, authorized: bool = True) -> UUID:
    actor = platform_principal(conn)
    if authorized:
        platform_grant(
            conn,
            principal_id=actor,
            capability="platform.identity.disable",
            delegable=False,
        )
    return actor


def _disable(
    conn: PgConnection,
    *,
    actor: UUID,
    identity: UUID,
    expected_revision: int,
    key_digest: str,
    intent_digest: str,
    reason: str = "operator_revocation",
    case: str | None = None,
    actor_revision: int | None = None,
) -> tuple[Any, ...]:
    _set_actor(conn, actor, revision=actor_revision)
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            _DISABLE,
            (identity, expected_revision, reason, case, key_digest, intent_digest),
        ).fetchone()
    finally:
        conn.execute("RESET ROLE")
    assert row is not None
    return tuple(row)


def test_disable_unbound_native_identity_is_terminal_and_replayable(
    admin_conn: PgConnection,
) -> None:
    _authority_id, identity_id, credential_id = _native_identity(admin_conn)
    actor = _operator(admin_conn)
    key_digest = _digest()
    intent_digest = _digest()

    fact_id, returned_identity, revision_after, tenants, platform = _disable(
        admin_conn,
        actor=actor,
        identity=identity_id,
        expected_revision=1,
        key_digest=key_digest,
        intent_digest=intent_digest,
        case="CASE-1",
    )
    assert returned_identity == identity_id
    assert revision_after == 2
    assert tenants == 0
    assert platform is False

    state = admin_conn.execute(
        "SELECT status, disabled_at, session_epoch, revision FROM request_engine.native_identities "
        "WHERE id = %s",
        (identity_id,),
    ).fetchone()
    assert state is not None
    assert state[0] == "disabled"
    assert state[1] is not None
    assert int(state[2]) == 2
    assert int(state[3]) == 2
    credential = admin_conn.execute(
        "SELECT status FROM request_engine.native_credentials WHERE id = %s",
        (credential_id,),
    ).fetchone()
    assert credential == ("revoked",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_identity_disable_facts "
        "WHERE id = %s AND affected_tenant_count = 0 AND affected_platform = false",
        (fact_id,),
    ).fetchone() == (1,)

    # Exact replay returns the recorded fact without a second mutation.
    replayed = _disable(
        admin_conn,
        actor=actor,
        identity=identity_id,
        expected_revision=1,
        key_digest=key_digest,
        intent_digest=intent_digest,
        case="CASE-1",
    )
    assert replayed[0] == fact_id
    assert replayed[2] == 2
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_identity_disable_facts",
    ).fetchone() == (1,)

    # A second disable of the terminal identity is rejected.
    with pytest.raises(Error) as terminal:
        _disable(
            admin_conn,
            actor=actor,
            identity=identity_id,
            expected_revision=2,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert terminal.value.sqlstate == "55000"


def test_disable_cannot_remove_the_last_tenant_controller(
    admin_conn: PgConnection,
) -> None:
    organization_id, _party, controller, _authority = provision_root(admin_conn)
    identity_row = admin_conn.execute(
        """
        SELECT binding.subject_id::uuid
          FROM request_engine.identity_bindings AS binding
         WHERE binding.organization_id = %s
           AND binding.principal_id = %s
           AND binding.principal_plane = 'tenant'
           AND binding.status = 'active'
        """,
        (organization_id, controller),
    ).fetchone()
    assert identity_row is not None
    identity_id = UUID(str(identity_row[0]))
    actor = _operator(admin_conn)

    with pytest.raises(Error) as denied:
        _disable(
            admin_conn,
            actor=actor,
            identity=identity_id,
            expected_revision=1,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "23514"
    # The whole transaction rolled back: the identity remains active.
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_identities WHERE id = %s",
        (identity_id,),
    ).fetchone() == ("active",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_identity_disable_facts",
    ).fetchone() == (0,)


def test_disable_requires_current_platform_authority(admin_conn: PgConnection) -> None:
    _authority_id, identity_id, _credential_id = _native_identity(admin_conn)
    unauthorized = _operator(admin_conn, authorized=False)
    with pytest.raises(Error) as denied:
        _disable(
            admin_conn,
            actor=unauthorized,
            identity=identity_id,
            expected_revision=1,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "42501"

    actor = _operator(admin_conn)
    with pytest.raises(Error) as stale:
        _disable(
            admin_conn,
            actor=actor,
            identity=identity_id,
            expected_revision=99,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert stale.value.sqlstate == "40001"
