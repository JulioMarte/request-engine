"""Platform owner/admin lifecycle: invitation proof, ceiling, continuity, self-action.

Revision 0068 adds the platform-plane membership aggregate, the digest-only
one-time invitation proof and the invite/accept/transition/replace-authority
commands. These proofs exercise the real PostgreSQL 18 semantics: state machine,
revisioning, idempotent replay, delegable ceiling, last-controller continuity,
self-action refusal and append-only facts.
"""

import hashlib
from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import insert_authority
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

_INVITE: LiteralString = (
    "SELECT * FROM request_platform.invite_platform_owner("
    "CAST(%s AS uuid), CAST(%s AS text), CAST(%s AS timestamptz), "
    "CAST(%s AS text), CAST(%s AS text))"
)
_ACCEPT: LiteralString = (
    "SELECT * FROM request_platform.accept_platform_invitation("
    "CAST(%s AS text), CAST(%s AS uuid), CAST(%s AS bigint), "
    "CAST(%s AS text), CAST(%s AS text))"
)
_TRANSITION: LiteralString = (
    "SELECT * FROM request_platform.transition_platform_membership("
    "CAST(%s AS uuid), CAST(%s AS bigint), CAST(%s AS text), "
    "CAST(%s AS text), CAST(%s AS text))"
)
_REPLACE: LiteralString = (
    "SELECT * FROM request_platform.replace_platform_authority("
    "CAST(%s AS uuid), CAST(%s AS bigint), CAST(%s AS text[]), "
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


def _world(
    admin_conn: PgConnection,
) -> tuple[UUID, UUID, UUID, UUID]:
    """A claimed instance with an owner who may delegate owner administration."""

    authority_id = insert_authority(admin_conn)
    workload_authority_id = insert_authority(admin_conn)
    owner = platform_principal(admin_conn)
    admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(singleton_key, state, built_in_native_authority_id, "
        "built_in_workload_authority_id, claimed_at, initial_owner_principal_id, "
        "claim_provenance) VALUES (1, 'claimed', %s, %s, clock_timestamp(), %s, %s)",
        (authority_id, workload_authority_id, owner, "owner-lifecycle-proof"),
    )
    for capability, delegable in (
        ("platform.tenant_provisioner.provision", True),
        ("platform.owner.read", False),
        ("platform.owner.invite", True),
        ("platform.owner.manage_membership", True),
        ("platform.owner.manage_authority", True),
    ):
        platform_grant(admin_conn, principal_id=owner, capability=capability, delegable=delegable)
    identity_id = uuid4()
    credential_id = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, f"owner-{uuid4().hex}@example.test"),
    )
    admin_conn.execute(
        "INSERT INTO request_engine.native_credentials "
        "(id, native_identity_id, verifier) VALUES (%s, %s, %s)",
        (credential_id, identity_id, hash_password(PASSWORD)),
    )
    return owner, authority_id, identity_id, credential_id


def _invite(
    conn: PgConnection,
    *,
    owner: UUID,
    identity_id: UUID,
    key_digest: str,
    intent_digest: str,
    proof_digest: str,
) -> tuple[Any, ...]:
    _set_actor(conn, owner)
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            _INVITE,
            (identity_id, proof_digest, "2030-01-01T00:00:00+00:00", key_digest, intent_digest),
        ).fetchone()
    finally:
        conn.execute("RESET ROLE")
    assert row is not None
    return tuple(row)


def _accept(
    conn: PgConnection,
    *,
    proof_digest: str,
    identity_id: UUID,
    expected_revision: int,
    key_digest: str,
    intent_digest: str,
) -> tuple[Any, ...]:
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            _ACCEPT,
            (proof_digest, identity_id, expected_revision, key_digest, intent_digest),
        ).fetchone()
    finally:
        conn.execute("RESET ROLE")
    assert row is not None
    return tuple(row)


def _transition(
    conn: PgConnection,
    *,
    actor: UUID,
    membership_id: UUID,
    expected_revision: int,
    target_status: str,
    key_digest: str,
    intent_digest: str,
) -> tuple[Any, ...]:
    _set_actor(conn, actor)
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            _TRANSITION,
            (membership_id, expected_revision, target_status, key_digest, intent_digest),
        ).fetchone()
    finally:
        conn.execute("RESET ROLE")
    assert row is not None
    return tuple(row)


def _replace(
    conn: PgConnection,
    *,
    actor: UUID,
    membership_id: UUID,
    expected_authority_revision: int,
    desired: list[str],
    key_digest: str,
    intent_digest: str,
) -> tuple[Any, ...]:
    _set_actor(conn, actor)
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            _REPLACE,
            (
                membership_id,
                expected_authority_revision,
                desired,
                key_digest,
                intent_digest,
            ),
        ).fetchone()
    finally:
        conn.execute("RESET ROLE")
    assert row is not None
    return tuple(row)


def _membership(conn: PgConnection, membership_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, revision, principal_id, identity_binding_id, "
        "activated_at IS NOT NULL, revoked_at IS NOT NULL "
        "FROM request_engine.platform_memberships WHERE id = %s",
        (membership_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _binding(conn: PgConnection, binding_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, revision FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _facts(conn: PgConnection, membership_id: UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT action, revision_before, revision_after, actor_principal_id, "
        "capability_key, correlation_id IS NOT NULL "
        "FROM request_engine.platform_membership_facts "
        "WHERE membership_id = %s ORDER BY created_at, id",
        (membership_id,),
    ).fetchall()


def _active_capabilities(conn: PgConnection, principal_id: UUID) -> set[str]:
    rows = conn.execute(
        "SELECT capability_key FROM request_engine.principal_authority_grants "
        "WHERE principal_id = %s AND status = 'active'",
        (principal_id,),
    ).fetchall()
    return {row[0] for row in rows}


def test_full_owner_lifecycle_is_revisioned_and_audited(admin_conn: PgConnection) -> None:
    owner, _, identity_id, _ = _world(admin_conn)
    proof = _digest()
    invited = _invite(
        admin_conn,
        owner=owner,
        identity_id=identity_id,
        key_digest=_digest(),
        intent_digest=_digest(),
        proof_digest=proof,
    )
    membership_id, invitee, binding_id = invited[0], invited[1], invited[2]
    assert _membership(admin_conn, membership_id)[:2] == ("invited", 1)
    assert _binding(admin_conn, binding_id) == ("pending", 1)
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s", (invitee,)
    ).fetchone() == (True,)
    assert _active_capabilities(admin_conn, invitee) == set()

    accepted = _accept(
        admin_conn,
        proof_digest=proof,
        identity_id=identity_id,
        expected_revision=1,
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    assert accepted[0] == membership_id
    assert accepted[2] == "active"
    assert accepted[3] == 2
    assert _membership(admin_conn, membership_id)[:2] == ("active", 2)
    assert _binding(admin_conn, binding_id) == ("active", 2)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.platform_invitation_intents WHERE proof_digest = %s",
        (proof,),
    ).fetchone() == ("consumed",)

    authority_revision = principal_revision(admin_conn, invitee)
    desired = [
        "platform.owner.invite",
        "platform.owner.manage_membership",
        "platform.owner.manage_authority",
    ]
    replaced = _replace(
        admin_conn,
        actor=owner,
        membership_id=membership_id,
        expected_authority_revision=authority_revision,
        desired=desired,
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    assert replaced[1] == invitee
    assert _active_capabilities(admin_conn, invitee) == set(desired)

    suspended = _transition(
        admin_conn,
        actor=owner,
        membership_id=membership_id,
        expected_revision=2,
        target_status="suspended",
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    assert suspended[1] == "suspended"
    assert suspended[2] == 3
    assert _binding(admin_conn, binding_id) == ("suspended", 3)
    assert admin_conn.execute(
        "SELECT active FROM request_engine.principals WHERE id = %s", (invitee,)
    ).fetchone() == (False,)

    reactivated = _transition(
        admin_conn,
        actor=owner,
        membership_id=membership_id,
        expected_revision=3,
        target_status="active",
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    assert reactivated[1] == "active"
    assert reactivated[2] == 4

    revoked = _transition(
        admin_conn,
        actor=owner,
        membership_id=membership_id,
        expected_revision=4,
        target_status="revoked",
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    assert revoked[1] == "revoked"
    assert revoked[2] == 5
    assert _binding(admin_conn, binding_id) == ("revoked", 5)
    assert _active_capabilities(admin_conn, invitee) == set()

    facts = _facts(admin_conn, membership_id)
    assert [fact[0] for fact in facts] == [
        "invite",
        "accept",
        "replace_authority",
        "suspend",
        "reactivate",
        "revoke",
    ]
    assert all(fact[5] for fact in facts if fact[0] != "accept")


def test_invite_requires_a_credentialed_native_identity(admin_conn: PgConnection) -> None:
    owner, authority_id, _, _ = _world(admin_conn)
    bare_identity = uuid4()
    admin_conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (bare_identity, authority_id, f"bare-{uuid4().hex}@example.test"),
    )
    with pytest.raises(Error) as denied:
        _invite(
            admin_conn,
            owner=owner,
            identity_id=bare_identity,
            key_digest=_digest(),
            intent_digest=_digest(),
            proof_digest=_digest(),
        )
    assert denied.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_memberships"
    ).fetchone() == (0,)


def test_accept_requires_the_bound_identity_and_a_live_proof(
    admin_conn: PgConnection,
) -> None:
    owner, _, identity_id, _ = _world(admin_conn)
    proof = _digest()
    _invite(
        admin_conn,
        owner=owner,
        identity_id=identity_id,
        key_digest=_digest(),
        intent_digest=_digest(),
        proof_digest=proof,
    )

    with pytest.raises(Error) as mismatch:
        _accept(
            admin_conn,
            proof_digest=proof,
            identity_id=uuid4(),
            expected_revision=1,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert mismatch.value.sqlstate == "28000"

    with pytest.raises(Error) as unknown:
        _accept(
            admin_conn,
            proof_digest=_digest(),
            identity_id=identity_id,
            expected_revision=1,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert unknown.value.sqlstate == "28000"

    _accept(
        admin_conn,
        proof_digest=proof,
        identity_id=identity_id,
        expected_revision=1,
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    with pytest.raises(Error) as reused:
        _accept(
            admin_conn,
            proof_digest=proof,
            identity_id=identity_id,
            expected_revision=2,
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert reused.value.sqlstate == "55000"


def test_invitation_replay_is_idempotent_and_key_reuse_conflicts(
    admin_conn: PgConnection,
) -> None:
    owner, _, identity_id, _ = _world(admin_conn)
    key_digest = _digest()
    intent_digest = _digest()
    proof = _digest()
    first = _invite(
        admin_conn,
        owner=owner,
        identity_id=identity_id,
        key_digest=key_digest,
        intent_digest=intent_digest,
        proof_digest=proof,
    )
    replay = _invite(
        admin_conn,
        owner=owner,
        identity_id=identity_id,
        key_digest=key_digest,
        intent_digest=intent_digest,
        proof_digest=_digest(),
    )
    assert replay[0] == first[0]
    assert replay[1] == first[1]
    assert len(_facts(admin_conn, first[0])) == 1
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.platform_memberships"
    ).fetchone() == (1,)

    with pytest.raises(Error) as conflict:
        _invite(
            admin_conn,
            owner=owner,
            identity_id=identity_id,
            key_digest=key_digest,
            intent_digest=_digest(),
            proof_digest=_digest(),
        )
    assert conflict.value.sqlstate == "23505"


def test_replace_authority_enforces_the_delegable_ceiling(
    admin_conn: PgConnection,
) -> None:
    owner, _, identity_id, _ = _world(admin_conn)
    proof = _digest()
    invited = _invite(
        admin_conn,
        owner=owner,
        identity_id=identity_id,
        key_digest=_digest(),
        intent_digest=_digest(),
        proof_digest=proof,
    )
    membership_id, invitee = invited[0], invited[1]
    _accept(
        admin_conn,
        proof_digest=proof,
        identity_id=identity_id,
        expected_revision=1,
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    authority_revision = principal_revision(admin_conn, invitee)

    with pytest.raises(Error) as denied:
        _replace(
            admin_conn,
            actor=owner,
            membership_id=membership_id,
            expected_authority_revision=authority_revision,
            desired=["platform.owner.read"],
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "42501"
    assert _active_capabilities(admin_conn, invitee) == set()

    with pytest.raises(Error) as unknown:
        _replace(
            admin_conn,
            actor=owner,
            membership_id=membership_id,
            expected_authority_revision=authority_revision,
            desired=["platform.identity.recover"],
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert unknown.value.sqlstate == "42501"


def test_self_authority_replacement_is_forbidden(admin_conn: PgConnection) -> None:
    owner, _, identity_id, _ = _world(admin_conn)
    proof = _digest()
    invited = _invite(
        admin_conn,
        owner=owner,
        identity_id=identity_id,
        key_digest=_digest(),
        intent_digest=_digest(),
        proof_digest=proof,
    )
    membership_id, invitee = invited[0], invited[1]
    _accept(
        admin_conn,
        proof_digest=proof,
        identity_id=identity_id,
        expected_revision=1,
        key_digest=_digest(),
        intent_digest=_digest(),
    )
    _replace(
        admin_conn,
        actor=owner,
        membership_id=membership_id,
        expected_authority_revision=principal_revision(admin_conn, invitee),
        desired=["platform.owner.manage_authority"],
        key_digest=_digest(),
        intent_digest=_digest(),
    )

    with pytest.raises(Error) as denied:
        _replace(
            admin_conn,
            actor=invitee,
            membership_id=membership_id,
            expected_authority_revision=principal_revision(admin_conn, invitee),
            desired=["platform.owner.manage_authority"],
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "42501"


def test_last_platform_controller_cannot_be_removed(admin_conn: PgConnection) -> None:
    owner, _, identity_id, _ = _world(admin_conn)
    operator = platform_principal(admin_conn)
    platform_grant(
        admin_conn,
        principal_id=operator,
        capability="platform.owner.manage_membership",
        delegable=False,
    )

    with pytest.raises(Error) as denied:
        _transition(
            admin_conn,
            actor=operator,
            membership_id=uuid4(),
            expected_revision=1,
            target_status="revoked",
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert denied.value.sqlstate == "P0002"

    # Give the owner a real membership, then let a non-controller operator try to
    # revoke the only controller.
    membership_id = _owner_membership(admin_conn, owner, identity_id)
    with pytest.raises(Error) as continuity:
        _transition(
            admin_conn,
            actor=operator,
            membership_id=membership_id,
            expected_revision=1,
            target_status="revoked",
            key_digest=_digest(),
            intent_digest=_digest(),
        )
    assert continuity.value.sqlstate == "23514"
    assert _membership(admin_conn, membership_id)[0] == "active"


def _owner_membership(conn: PgConnection, owner: UUID, identity_id: UUID) -> UUID:
    binding_id = uuid4()
    membership_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.identity_bindings "
        "(id, principal_id, principal_plane, identity_authority_id, subject_id, status) "
        "VALUES (%s, %s, 'platform', "
        "(SELECT built_in_native_authority_id FROM request_engine.platform_instance "
        " WHERE singleton_key = 1), %s, 'active')",
        (binding_id, owner, str(identity_id)),
    )
    conn.execute(
        "INSERT INTO request_engine.platform_memberships "
        "(id, principal_id, identity_binding_id, status, established_by_principal_id, "
        "provenance_kind, provenance_reference, activated_at) "
        "VALUES (%s, %s, %s, 'active', %s, 'owner_invitation', %s, clock_timestamp())",
        (membership_id, owner, binding_id, owner, f"owner-proof:{membership_id}"),
    )
    return membership_id


def test_normal_app_role_cannot_execute_or_read_lifecycle_state(
    admin_conn: PgConnection,
) -> None:
    admin_conn.execute("SET ROLE request_engine_app")
    try:
        with pytest.raises(Error) as denied:
            admin_conn.execute(
                _INVITE,
                (uuid4(), _digest(), "2030-01-01T00:00:00+00:00", _digest(), _digest()),
            )
        assert denied.value.sqlstate == "42501"
        with pytest.raises(Error) as hidden:
            admin_conn.execute("SELECT count(*) FROM request_engine.platform_memberships")
        assert hidden.value.sqlstate == "42501"
    finally:
        admin_conn.execute("RESET ROLE")


def test_membership_facts_are_append_only(admin_conn: PgConnection) -> None:
    owner, _, identity_id, _ = _world(admin_conn)
    proof = _digest()
    invited = _invite(
        admin_conn,
        owner=owner,
        identity_id=identity_id,
        key_digest=_digest(),
        intent_digest=_digest(),
        proof_digest=proof,
    )

    admin_conn.execute("SET ROLE request_engine_schema_owner")
    try:
        with pytest.raises(Error) as update_denied:
            admin_conn.execute(
                "UPDATE request_engine.platform_membership_facts SET action = 'accept'"
            )
        assert update_denied.value.sqlstate == "55000"
        with pytest.raises(Error) as delete_denied:
            admin_conn.execute("DELETE FROM request_engine.platform_membership_facts")
        assert delete_denied.value.sqlstate == "55000"
    finally:
        admin_conn.execute("RESET ROLE")
    assert len(_facts(admin_conn, invited[0])) == 1


def test_new_claim_seeds_owner_administration_capabilities(
    admin_conn: PgConnection,
) -> None:
    authority_id = insert_authority(admin_conn)
    owner = platform_principal(admin_conn)
    v1_capabilities = (
        "platform.principal.provision",
        "platform.tenant_provisioner.provision",
        "platform.recovery_operator.provision",
        "organization.provision",
        "platform.identity.recover",
        "platform.identity.read",
        "platform.identity.recovery_approve",
        "platform.provisioner.read",
        "platform.provisioner.manage_lifecycle",
    )
    for capability in v1_capabilities:
        platform_grant(admin_conn, principal_id=owner, capability=capability, delegable=False)
    admin_conn.execute(
        "INSERT INTO request_engine.platform_installation_claim_facts "
        "(instance_id, setup_session_id, owner_principal_id, native_identity_id, "
        "policy_key, claim_provenance, idempotency_key_digest, intent_digest) "
        "VALUES (%s, %s, %s, %s, 'platform-owner-v1', %s, %s, %s)",
        (
            uuid4(),
            uuid4(),
            owner,
            uuid4(),
            "claim-proof",
            _digest(),
            _digest(),
        ),
    )
    assert _active_capabilities(admin_conn, owner) == set(v1_capabilities) | {
        "platform.owner.read",
        "platform.owner.invite",
        "platform.owner.manage_membership",
        "platform.owner.manage_authority",
    }
    assert authority_id  # authority built for a plausible world
