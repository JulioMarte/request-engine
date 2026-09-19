"""E1 governed controller-policy upgrade: falsifiable PostgreSQL proofs.

Each proof names the defect that would turn it red. The oracle is a direct admin
SELECT against ``principal_authority_grants`` / ``initial_controller_policies``,
never a production helper.
"""

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    native_identity,
    principal_revision,
    provision_root,
    reset_actor,
    set_tenant_actor,
)
from psycopg import Connection
from psycopg.rows import dict_row

from request_engine.modules.tenancy.adapters.db.controller_policy_commands import (
    PostgresControllerPolicyCommands,
)
from request_engine.modules.tenancy.application.commands.controller_policy_upgrade import (
    UpgradeControllerPolicyCommand,
)
from request_engine.modules.tenancy.application.errors import (
    ControllerPolicyUpgradeConflict,
    ControllerPolicyUpgradeForbidden,
    ControllerPolicyUpgradeInputInvalid,
    ControllerPolicyUpgradeNotFound,
    ControllerPolicyUpgradeRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_V1 = "tenant-controller-v1"
_V2 = "tenant-controller-v2"
_V3 = "tenant-controller-v3"
_V4 = "tenant-controller-v4"


def _actor(conn: PgConnection, *, organization_id: UUID, principal_id: UUID) -> ActorContext:
    return ActorContext(
        organization_id=organization_id,
        principal_id=principal_id,
        capabilities=frozenset({"controller_policy_upgrade"}),
        principal_kind=PrincipalKind.HUMAN,
        authentication_method="native_password",
        authority_revision=principal_revision(conn, principal_id),
    )


def _policy_grants(conn: PgConnection, policy_key: str) -> list[dict[str, Any]]:
    row = conn.execute(
        "SELECT grants FROM request_engine.initial_controller_policies WHERE policy_key = %s",
        (policy_key,),
    ).fetchone()
    assert row is not None
    return cast(list[dict[str, Any]], row[0])


def _policy_capabilities(conn: PgConnection, policy_key: str) -> set[str]:
    return {grant["capability_key"] for grant in _policy_grants(conn, policy_key)}


def _active_capabilities(
    conn: PgConnection, *, organization_id: UUID, principal_id: UUID
) -> set[str]:
    rows = conn.execute(
        """
        SELECT capability_key
          FROM request_engine.principal_authority_grants
         WHERE organization_id = %s AND principal_id = %s AND status = 'active'
        """,
        (organization_id, principal_id),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _insert_policy_grants(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    policy_key: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        )
        SELECT %s, %s, 'tenant', g.authority_plane, g.capability_key, true, %s,
               'authority_management', %s
          FROM jsonb_to_recordset(
              (SELECT grants FROM request_engine.initial_controller_policies
                WHERE policy_key = %s)
          ) AS g(capability_key text, authority_plane text, delegable boolean)
        ON CONFLICT (principal_id, capability_key) WHERE status = 'active'
        DO NOTHING
        """,
        (
            organization_id,
            principal_id,
            principal_id,
            f"e1-seed:{policy_key}:{uuid4().hex}",
            policy_key,
        ),
    )


def _revoke_capability(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability_key: str,
) -> None:
    rowcount = conn.execute(
        """
        UPDATE request_engine.principal_authority_grants
           SET status = 'revoked',
               revision = revision + 1,
               revoked_at = clock_timestamp(),
               revoked_by_principal_id = %s
         WHERE organization_id = %s
           AND principal_id = %s
           AND capability_key = %s
           AND status = 'active'
        """,
        (principal_id, organization_id, principal_id, capability_key),
    ).rowcount
    assert rowcount == 1


def _invite_and_activate(
    conn: PgConnection,
    *,
    organization_id: UUID,
    root_id: UUID,
    party_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    membership_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    set_tenant_actor(conn, organization_id=organization_id, principal_id=root_id)
    try:
        returned = conn.execute(
            "SELECT request_engine.invite_native_staff(%s, %s, %s, %s, %s, %s, %s)",
            (
                membership_id,
                principal_id,
                binding_id,
                authority_id,
                native_identity_id,
                party_id,
                f"e1-invite:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
        activated = conn.execute(
            "SELECT request_engine.transition_staff_membership(%s, 1, 'active', %s)",
            (membership_id, f"e1-activate:{uuid4().hex}"),
        ).fetchone()
        assert activated == (2,)
    finally:
        reset_actor(conn)
    return membership_id, principal_id


def _audit_rows(
    conn: PgConnection, *, organization_id: UUID, aggregate_id: UUID
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT actor_principal_id, aggregate_kind, aggregate_id, details
              FROM request_engine.audit_records
             WHERE organization_id = %s
               AND command_name = 'controller_policy_upgrade'
               AND aggregate_id = %s
             ORDER BY created_at, id
            """,
            (organization_id, aggregate_id),
        )
        return list(cursor.fetchall())


async def _upgrade(
    commands: PostgresControllerPolicyCommands,
    actor: ActorContext,
    *,
    target_principal_id: UUID,
    target_policy_key: str,
    expected_authority_revision: int,
    key: str,
    source_policy_key: str = _V1,
) -> int:
    return await commands.upgrade_controller_policy(
        actor,
        UpgradeControllerPolicyCommand(
            target_principal_id=target_principal_id,
            source_policy_key=source_policy_key,
            target_policy_key=target_policy_key,
            expected_authority_revision=expected_authority_revision,
            idempotency_key=key,
        ),
    )


@pytest.mark.asyncio
async def test_self_upgrade_is_forbidden_and_adds_no_grant(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    before = _active_capabilities(admin_conn, organization_id=organization_id, principal_id=root_id)
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)

    with pytest.raises(ControllerPolicyUpgradeForbidden):
        await _upgrade(
            commands,
            actor,
            target_principal_id=root_id,
            target_policy_key=_V4,
            expected_authority_revision=principal_revision(admin_conn, root_id),
            key=f"e1-self-{uuid4().hex}",
        )

    after = _active_capabilities(admin_conn, organization_id=organization_id, principal_id=root_id)
    assert after == before
    assert _audit_rows(admin_conn, organization_id=organization_id, aggregate_id=root_id) == []


@pytest.mark.asyncio
async def test_upgrade_beyond_actor_delegable_ceiling_is_forbidden(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    _revoke_capability(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        capability_key="authority.read_self",
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=target_id,
        policy_key=_V1,
    )
    before = _active_capabilities(
        admin_conn, organization_id=organization_id, principal_id=target_id
    )
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)

    with pytest.raises(ControllerPolicyUpgradeForbidden):
        await _upgrade(
            commands,
            actor,
            target_principal_id=target_id,
            target_policy_key=_V3,
            expected_authority_revision=principal_revision(admin_conn, target_id),
            key=f"e1-ceiling-{uuid4().hex}",
        )

    assert (
        _active_capabilities(admin_conn, organization_id=organization_id, principal_id=target_id)
        == before
    )


@pytest.mark.asyncio
async def test_revoked_delta_is_not_resurrected(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=target_id,
        policy_key=_V2,
    )
    _revoke_capability(
        admin_conn,
        organization_id=organization_id,
        principal_id=target_id,
        capability_key="agent.read",
    )
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)

    with pytest.raises(ControllerPolicyUpgradeConflict):
        await _upgrade(
            commands,
            actor,
            target_principal_id=target_id,
            target_policy_key=_V3,
            expected_authority_revision=principal_revision(admin_conn, target_id),
            key=f"e1-revoked-{uuid4().hex}",
        )

    assert admin_conn.execute(
        """
        SELECT status FROM request_engine.principal_authority_grants
         WHERE organization_id = %s AND principal_id = %s AND capability_key = 'agent.read'
        """,
        (organization_id, target_id),
    ).fetchall() == [("revoked",)]
    assert "agent.read" not in _active_capabilities(
        admin_conn, organization_id=organization_id, principal_id=target_id
    )


@pytest.mark.asyncio
async def test_idempotent_replay_commits_one_grant_set_and_one_audit_row(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    before = _active_capabilities(
        admin_conn, organization_id=organization_id, principal_id=target_id
    )
    delta = _policy_capabilities(admin_conn, _V3) - before
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)
    revision = principal_revision(admin_conn, target_id)
    key = f"e1-replay-{uuid4().hex}"

    first = await _upgrade(
        commands,
        actor,
        target_principal_id=target_id,
        target_policy_key=_V3,
        expected_authority_revision=revision,
        key=key,
    )
    second = await _upgrade(
        commands,
        actor,
        target_principal_id=target_id,
        target_policy_key=_V3,
        expected_authority_revision=revision,
        key=key,
    )

    assert first == second
    rows = admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.principal_authority_grants
         WHERE organization_id = %s AND principal_id = %s
           AND provenance_kind = 'controller_policy_upgrade'
        """,
        (organization_id, target_id),
    ).fetchone()
    assert rows == (len(delta),)
    audit = _audit_rows(admin_conn, organization_id=organization_id, aggregate_id=target_id)
    assert len(audit) == 1


@pytest.mark.asyncio
async def test_populated_upgrade_grants_exactly_the_missing_delta(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=target_id,
        policy_key=_V1,
    )
    before = _active_capabilities(
        admin_conn, organization_id=organization_id, principal_id=target_id
    )
    expected_added = _policy_capabilities(admin_conn, _V3) - before
    assert expected_added == {"agent.read", "authority.read_self"}
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)
    revision = principal_revision(admin_conn, target_id)

    returned = await _upgrade(
        commands,
        actor,
        target_principal_id=target_id,
        target_policy_key=_V3,
        expected_authority_revision=revision,
        key=f"e1-populated-{uuid4().hex}",
    )

    assert returned == principal_revision(admin_conn, target_id)
    assert returned == revision + len(expected_added)
    after = _active_capabilities(
        admin_conn, organization_id=organization_id, principal_id=target_id
    )
    assert after == before | expected_added
    with admin_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT capability_key, authority_plane, delegable, provenance_reference
              FROM request_engine.principal_authority_grants
             WHERE organization_id = %s AND principal_id = %s
               AND provenance_kind = 'controller_policy_upgrade'
            """,
            (organization_id, target_id),
        )
        added = {row["capability_key"]: row for row in cursor.fetchall()}
    assert set(added) == expected_added
    for capability_key, row in added.items():
        policy_grant = next(
            grant
            for grant in _policy_grants(admin_conn, _V3)
            if grant["capability_key"] == capability_key
        )
        assert row["authority_plane"] == policy_grant["authority_plane"]
        assert row["delegable"] is False
        assert row["provenance_reference"] == f"policy:{_V3};source:{_V1}"


@pytest.mark.asyncio
async def test_unknown_policy_foreign_and_absent_targets_are_rejected(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    foreign_organization_id, _foreign_party, foreign_root_id, _foreign_authority = provision_root(
        admin_conn
    )
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)

    with pytest.raises(ControllerPolicyUpgradeInputInvalid):
        await _upgrade(
            commands,
            actor,
            target_principal_id=target_id,
            target_policy_key="tenant-controller-unknown",
            expected_authority_revision=principal_revision(admin_conn, target_id),
            key=f"e1-unknown-{uuid4().hex}",
        )

    foreign_before = _active_capabilities(
        admin_conn, organization_id=foreign_organization_id, principal_id=foreign_root_id
    )
    with pytest.raises(ControllerPolicyUpgradeNotFound):
        await _upgrade(
            commands,
            actor,
            target_principal_id=foreign_root_id,
            target_policy_key=_V3,
            expected_authority_revision=principal_revision(admin_conn, foreign_root_id),
            key=f"e1-foreign-{uuid4().hex}",
        )

    with pytest.raises(ControllerPolicyUpgradeNotFound):
        await _upgrade(
            commands,
            actor,
            target_principal_id=uuid4(),
            target_policy_key=_V3,
            expected_authority_revision=1,
            key=f"e1-absent-{uuid4().hex}",
        )

    assert (
        _active_capabilities(
            admin_conn, organization_id=foreign_organization_id, principal_id=foreign_root_id
        )
        == foreign_before
    )


@pytest.mark.asyncio
async def test_upgrade_commits_one_secret_free_audit_row(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)
    revision = principal_revision(admin_conn, target_id)

    returned = await _upgrade(
        commands,
        actor,
        target_principal_id=target_id,
        target_policy_key=_V3,
        expected_authority_revision=revision,
        key=f"e1-audit-{uuid4().hex}",
    )

    rows = _audit_rows(admin_conn, organization_id=organization_id, aggregate_id=target_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["actor_principal_id"] == root_id
    assert row["aggregate_kind"] == "TenantController"
    assert row["details"] == {
        "action": "policy_upgrade",
        "reason_code": "controller_policy_upgraded",
        "subject_kind": "TenantController",
        "revision_before": revision,
        "revision_after": returned,
        "source_policy_key": _V1,
        "target_policy_key": _V3,
    }
    serialized = repr(row["details"])
    assert "token" not in serialized
    assert "password" not in serialized
    assert "verifier" not in serialized


@pytest.mark.asyncio
async def test_non_human_actor_is_forbidden(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    before = _active_capabilities(
        admin_conn, organization_id=organization_id, principal_id=target_id
    )
    actor = ActorContext(
        organization_id=organization_id,
        principal_id=root_id,
        capabilities=frozenset({"controller_policy_upgrade"}),
        principal_kind=PrincipalKind.AGENT,
        authentication_method="workload_credential",
        authority_revision=principal_revision(admin_conn, root_id),
    )
    commands = PostgresControllerPolicyCommands(command_session_factory)

    with pytest.raises(ControllerPolicyUpgradeForbidden):
        await _upgrade(
            commands,
            actor,
            target_principal_id=target_id,
            target_policy_key=_V3,
            expected_authority_revision=principal_revision(admin_conn, target_id),
            key=f"e1-agent-{uuid4().hex}",
        )

    assert (
        _active_capabilities(admin_conn, organization_id=organization_id, principal_id=target_id)
        == before
    )


@pytest.mark.asyncio
async def test_stale_target_revision_is_rejected(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _authority_id = provision_root(admin_conn)
    _insert_policy_grants(
        admin_conn,
        organization_id=organization_id,
        principal_id=root_id,
        policy_key=_V4,
    )
    target_authority_id, target_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, target_id = _invite_and_activate(
        admin_conn,
        organization_id=organization_id,
        root_id=root_id,
        party_id=party_id,
        authority_id=target_authority_id,
        native_identity_id=target_identity_id,
    )
    actor = _actor(admin_conn, organization_id=organization_id, principal_id=root_id)
    commands = PostgresControllerPolicyCommands(command_session_factory)

    with pytest.raises(ControllerPolicyUpgradeRevisionConflict):
        await _upgrade(
            commands,
            actor,
            target_principal_id=target_id,
            target_policy_key=_V3,
            expected_authority_revision=principal_revision(admin_conn, target_id) + 5,
            key=f"e1-stale-{uuid4().hex}",
        )
