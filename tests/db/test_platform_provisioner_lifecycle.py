"""Platform provisioner lifecycle: revision, replay, audit, continuity, terminal."""

import hashlib
import threading
from typing import Any, LiteralString
from uuid import UUID, uuid4

import psycopg
import pytest
from native_authority_gate_support import insert_authority, set_authority_status
from platform_provisioning_support import (
    platform_grant,
    platform_principal,
    principal_revision,
)
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
_DEFAULT_REASON = {
    "suspend": "operator_suspension",
    "reactivate": "operator_reactivation",
    "revoke": "operator_revocation",
}
_CALL: LiteralString = (
    "SELECT * FROM request_platform.transition_native_platform_provisioner("
    "CAST(%s AS uuid), CAST(%s AS text), CAST(%s AS bigint), CAST(%s AS text), "
    "CAST(%s AS text), CAST(%s AS text), CAST(%s AS text))"
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


def _world(
    admin_conn: PgConnection,
    *,
    controller: bool = False,
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID]:
    """A credentialed native platform provisioner with one active binding."""

    authority_id = insert_authority(admin_conn)
    identity_id = uuid4()
    credential_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"lifecycle-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_credentials "
        "(id, native_identity_id, verifier) VALUES (%s, %s, %s)",
        (credential_id, identity_id, hash_password(PASSWORD)),
    )
    actor = platform_principal(admin_conn)
    platform_grant(
        admin_conn,
        principal_id=actor,
        capability="platform.provisioner.manage_lifecycle",
        delegable=False,
    )
    provisioner = platform_principal(admin_conn)
    binding_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.identity_bindings "
        "(id, principal_id, principal_plane, identity_authority_id, subject_id, status) "
        "VALUES (%s, %s, 'platform', %s, %s, 'active')",
        (binding_id, provisioner, authority_id, str(identity_id)),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.principal_authority_grants "
        "(principal_id, principal_plane, authority_plane, capability_key, delegable, "
        "granted_by_principal_id, provenance_kind, provenance_reference) "
        "VALUES (%s, 'platform', 'platform', 'organization.provision', false, %s, "
        "'provisioning', %s)",
        (provisioner, actor, f"lifecycle:{uuid4().hex}"),
    )
    if controller:
        platform_grant(
            admin_conn,
            principal_id=provisioner,
            capability="platform.tenant_provisioner.provision",
            delegable=False,
        )
    return actor, provisioner, binding_id, authority_id, identity_id, credential_id


def _transition(
    conn: PgConnection,
    *,
    actor: UUID,
    provisioner: UUID,
    action: str,
    expected_revision: int,
    key_digest: str,
    intent_digest: str,
    reason: str | None = None,
    case: str | None = None,
    actor_revision: int | None = None,
) -> tuple[Any, ...]:
    _set_actor(conn, actor, revision=actor_revision)
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            _CALL,
            (
                provisioner,
                action,
                expected_revision,
                reason or _DEFAULT_REASON[action],
                case,
                key_digest,
                intent_digest,
            ),
        ).fetchone()
    finally:
        conn.execute("RESET ROLE")
    assert row is not None
    return tuple(row)


def _binding(conn: PgConnection, binding_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, revision, revoked_at IS NOT NULL "
        "FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _facts(conn: PgConnection, provisioner: UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT action, reason_code, revision_before, revision_after, "
        "actor_principal_id, capability_key, correlation_id IS NOT NULL "
        "FROM request_engine.platform_authority_lifecycle_facts "
        "WHERE principal_id = %s ORDER BY created_at, id",
        (provisioner,),
    ).fetchall()


def test_lifecycle_transitions_are_revisioned_audited_and_terminal(
    admin_conn: PgConnection,
) -> None:
    actor, provisioner, binding_id, _, _, _ = _world(admin_conn)
    start_revision = principal_revision(admin_conn, provisioner)

    suspended = _transition(
        admin_conn,
        actor=actor,
        provisioner=provisioner,
        action="suspend",
        expected_revision=start_revision,
        key_digest=_digest(),
        intent_digest=_digest(),
        case="case-2026-001",
    )
    assert suspended[1] == provisioner
    assert suspended[2] == "suspend"
    assert suspended[3] == start_revision + 1
    assert suspended[4] == binding_id
    assert suspended[5] == "suspended"
    assert _binding(admin_conn, binding_id) == ("suspended", 2, False)

    reactivated = _transition(
        admin_conn,
        actor=actor,
        provisioner=provisioner,
        action="reactivate",
        expected_revision=start_revision + 1,
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    assert reactivated[3] == start_revision + 2
    assert reactivated[5] == "active"
    assert _binding(admin_conn, binding_id) == ("active", 3, False)

    revoked = _transition(
        admin_conn,
        actor=actor,
        provisioner=provisioner,
        action="revoke",
        expected_revision=start_revision + 2,
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    assert revoked[3] == start_revision + 4
    assert revoked[5] == "revoked"
    assert _binding(admin_conn, binding_id) == ("revoked", 4, True)

    grants = admin_conn.execute(
        "SELECT capability_key, status, revoked_by_principal_id, revoked_at IS NOT NULL "
        "FROM request_engine.principal_authority_grants WHERE principal_id = %s",
        (provisioner,),
    ).fetchall()
    assert grants == [("organization.provision", "revoked", actor, True)]

    facts = _facts(admin_conn, provisioner)
    assert [fact[0] for fact in facts] == ["suspend", "reactivate", "revoke"]
    assert [fact[1] for fact in facts] == [
        "operator_suspension",
        "operator_reactivation",
        "operator_revocation",
    ]
    assert [fact[2] for fact in facts] == [
        start_revision,
        start_revision + 1,
        start_revision + 2,
    ]
    assert [fact[3] for fact in facts] == [
        start_revision + 1,
        start_revision + 2,
        start_revision + 4,
    ]
    assert {fact[4] for fact in facts} == {actor}
    assert {fact[5] for fact in facts} == {"platform.provisioner.manage_lifecycle"}
    assert all(fact[6] for fact in facts)


def test_lifecycle_replay_is_idempotent_and_key_reuse_conflicts(
    admin_conn: PgConnection,
) -> None:
    actor, provisioner, binding_id, _, _, _ = _world(admin_conn)
    revision = principal_revision(admin_conn, provisioner)
    key_digest = _digest()
    intent_digest = _digest()

    first = _transition(
        admin_conn,
        actor=actor,
        provisioner=provisioner,
        action="suspend",
        expected_revision=revision,
        key_digest=key_digest,
        intent_digest=intent_digest,
    )
    replay = _transition(
        admin_conn,
        actor=actor,
        provisioner=provisioner,
        action="suspend",
        expected_revision=revision,
        key_digest=key_digest,
        intent_digest=intent_digest,
    )
    assert replay[0] == first[0]
    assert replay[3] == first[3]
    assert _binding(admin_conn, binding_id) == ("suspended", 2, False)
    assert len(_facts(admin_conn, provisioner)) == 1

    with pytest.raises(Error) as reused:
        _transition(
            admin_conn,
            actor=actor,
            provisioner=provisioner,
            action="revoke",
            expected_revision=revision + 1,
            key_digest=key_digest,
            intent_digest=_digest(),
        )
    assert reused.value.sqlstate == "23505"
    assert _binding(admin_conn, binding_id) == ("suspended", 2, False)


def test_lifecycle_requires_current_target_and_actor_revisions(
    admin_conn: PgConnection,
) -> None:
    actor, provisioner, binding_id, _, _, _ = _world(admin_conn)
    revision = principal_revision(admin_conn, provisioner)

    with pytest.raises(Error) as stale_target:
        _transition(
            admin_conn,
            actor=actor,
            provisioner=provisioner,
            action="suspend",
            expected_revision=revision - 1,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert stale_target.value.sqlstate == "40001"

    with pytest.raises(Error) as stale_actor:
        _transition(
            admin_conn,
            actor=actor,
            provisioner=provisioner,
            action="suspend",
            expected_revision=revision,
            key_digest=_digest(),
            intent_digest=_digest(),
            actor_revision=revision + 5,
        )
    assert stale_actor.value.sqlstate == "40001"
    assert _binding(admin_conn, binding_id) == ("active", 1, False)
    assert _facts(admin_conn, provisioner) == []


@pytest.mark.parametrize(
    "path_break",
    ["credential_revoked", "identity_disabled", "authority_disabled"],
)
def test_reactivate_requires_an_authenticatable_native_path(
    admin_conn: PgConnection, path_break: str
) -> None:
    actor, provisioner, binding_id, authority_id, identity_id, _ = _world(admin_conn)
    revision = principal_revision(admin_conn, provisioner)
    _transition(
        admin_conn,
        actor=actor,
        provisioner=provisioner,
        action="suspend",
        expected_revision=revision,
        key_digest=_digest(),
        intent_digest=_digest(),
    )

    if path_break == "credential_revoked":
        admin_conn.execute(
            "UPDATE request_engine.native_credentials SET status = 'revoked', "
            "revoked_at = clock_timestamp(), revision = revision + 1 "
            "WHERE native_identity_id = %s AND status = 'active'",
            (identity_id,),
        )
    elif path_break == "identity_disabled":
        admin_conn.execute(
            "UPDATE request_engine.native_identities SET status = 'disabled', "
            "disabled_at = clock_timestamp(), session_epoch = session_epoch + 1, "
            "revision = revision + 1 WHERE id = %s",
            (identity_id,),
        )
    else:
        set_authority_status(admin_conn, authority_id, "disabled")

    with pytest.raises(Error) as denied:
        _transition(
            admin_conn,
            actor=actor,
            provisioner=provisioner,
            action="reactivate",
            expected_revision=revision + 1,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "23514"
    assert _binding(admin_conn, binding_id) == ("suspended", 2, False)
    assert len(_facts(admin_conn, provisioner)) == 1


@pytest.mark.parametrize("action", ["suspend", "revoke"])
def test_last_platform_controller_cannot_be_removed(admin_conn: PgConnection, action: str) -> None:
    actor, provisioner, binding_id, _, _, _ = _world(admin_conn, controller=True)
    revision = principal_revision(admin_conn, provisioner)

    with pytest.raises(Error) as denied:
        _transition(
            admin_conn,
            actor=actor,
            provisioner=provisioner,
            action=action,
            expected_revision=revision,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "23514"
    assert _binding(admin_conn, binding_id) == ("active", 1, False)
    assert _facts(admin_conn, provisioner) == []


def test_lifecycle_target_must_be_a_platform_provisioner(
    admin_conn: PgConnection,
) -> None:
    actor, _, _, _, _, _ = _world(admin_conn)
    outsider = platform_principal(admin_conn)
    platform_grant(
        admin_conn,
        principal_id=outsider,
        capability="organization.provision",
        delegable=False,
    )

    with pytest.raises(Error) as denied:
        _transition(
            admin_conn,
            actor=actor,
            provisioner=outsider,
            action="revoke",
            expected_revision=principal_revision(admin_conn, outsider),
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "22023"
    assert _facts(admin_conn, outsider) == []


def test_lifecycle_requires_lifecycle_authority_and_current_actor_grant(
    admin_conn: PgConnection,
) -> None:
    actor, provisioner, binding_id, _, _, _ = _world(admin_conn)
    revision = principal_revision(admin_conn, provisioner)
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status = 'revoked', "
        "revision = revision + 1, revoked_at = clock_timestamp(), "
        "revoked_by_principal_id = %s WHERE principal_id = %s AND status = 'active'",
        (actor, actor),
    )
    with pytest.raises(Error) as denied:
        _transition(
            admin_conn,
            actor=actor,
            provisioner=provisioner,
            action="suspend",
            expected_revision=revision,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "42501"
    assert _binding(admin_conn, binding_id) == ("active", 1, False)


def test_normal_app_role_cannot_execute_or_read_lifecycle_state(
    admin_conn: PgConnection,
) -> None:
    admin_conn.execute("SET ROLE request_engine_app")
    try:
        with pytest.raises(Error) as denied:
            admin_conn.execute(
                _CALL, (uuid4(), "revoke", 1, "operator_revocation", None, _digest(), _digest())
            )
        assert denied.value.sqlstate == "42501"
        with pytest.raises(Error) as hidden:
            admin_conn.execute(
                "SELECT count(*) FROM request_engine.platform_authority_lifecycle_facts"
            )
        assert hidden.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")


def test_lifecycle_facts_are_append_only(admin_conn: PgConnection) -> None:
    actor, provisioner, _, _, _, _ = _world(admin_conn)
    revision = principal_revision(admin_conn, provisioner)
    _transition(
        admin_conn,
        actor=actor,
        provisioner=provisioner,
        action="suspend",
        expected_revision=revision,
        key_digest=_digest(),
        intent_digest=_digest(),
    )

    admin_conn.execute("SET ROLE request_engine_schema_owner")
    try:
        with pytest.raises(Error) as update_denied:
            admin_conn.execute(
                "UPDATE request_engine.platform_authority_lifecycle_facts "
                "SET reason_code = 'rewritten'"
            )
        assert update_denied.value.sqlstate == "55000"
        with pytest.raises(Error) as delete_denied:
            admin_conn.execute("DELETE FROM request_engine.platform_authority_lifecycle_facts")
        assert delete_denied.value.sqlstate == "55000"
    finally:
        admin_conn.execute("RESET ROLE")
    assert len(_facts(admin_conn, provisioner)) == 1


def test_concurrent_lifecycle_transitions_serialize_on_the_platform_plane(
    admin_conn: PgConnection, pg_conninfo: str
) -> None:
    actor, provisioner, binding_id, _, _, _ = _world(admin_conn)
    revision = principal_revision(admin_conn, provisioner)
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, object]] = []
    outcomes_lock = threading.Lock()

    def worker() -> None:
        conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
        try:
            _set_actor(conn, actor)
            conn.execute("SET ROLE request_platform_control")
            barrier.wait(timeout=15)
            try:
                row = conn.execute(
                    _CALL,
                    (
                        provisioner,
                        "suspend",
                        revision,
                        "operator_suspension",
                        None,
                        _digest(),
                        _digest(),
                    ),
                ).fetchone()
                with outcomes_lock:
                    outcomes.append(("ok", row))
            except Error as exc:
                with outcomes_lock:
                    outcomes.append(("error", exc.sqlstate))
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(str(outcome[0]) for outcome in outcomes) == ["error", "ok"]
    assert [outcome[1] for outcome in outcomes if outcome[0] == "error"] == ["40001"]
    assert _binding(admin_conn, binding_id) == ("suspended", 2, False)
    assert len(_facts(admin_conn, provisioner)) == 1
