"""Governed tenant identity-binding lifecycle through the real app-role command.

These proofs protect the D1b lifecycle guarantee:

- suspend/reactivate/revoke transition the tenant binding and increment its
  revision exactly once, under the real runtime role and idempotency boundary;
- revoke is terminal and never resurrects a binding;
- the command cannot remove the tenant's last authenticatable controller (D4);
- a foreign or random binding is indistinguishable from an absent one;
- the command grants no authority and does not mutate the foreign tenant.

A binding created by staff invitation starts ``pending`` at revision 1 and is
bumped to ``active`` revision 2 by the membership activation, so the lifecycle
starts from revision 2.
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

from request_engine.modules.tenancy.adapters.db.identity_binding_commands import (
    PostgresIdentityBindingCommands,
)
from request_engine.modules.tenancy.application.commands.identity_binding import (
    IdentityBindingTargetStatus,
    TransitionIdentityBindingCommand,
)
from request_engine.modules.tenancy.application.errors import (
    IdentityBindingLifecycleConflict,
    IdentityBindingLifecycleForbidden,
    IdentityBindingLifecycleNotFound,
    IdentityBindingLifecycleRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]


def _binding_row(
    conn: Connection[Any], organization_id: UUID, principal_id: UUID
) -> tuple[UUID, str, int]:
    row = conn.execute(
        """
        SELECT id, status, revision
          FROM request_engine.identity_bindings
         WHERE organization_id = %s
           AND principal_id = %s
           AND principal_plane = 'tenant'
        """,
        (organization_id, principal_id),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0]), str(row[1]), int(row[2])


def _active_grant_count(conn: Connection[Any], organization_id: UUID) -> int:
    row = conn.execute(
        """
        SELECT count(*)
          FROM request_engine.principal_authority_grants
         WHERE organization_id = %s
           AND status = 'active'
        """,
        (organization_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _invite_activate_promote(
    conn: Connection[Any],
    *,
    organization_id: UUID,
    party_id: UUID,
    root_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
    promote: bool,
) -> tuple[UUID, UUID, UUID]:
    membership_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    set_tenant_actor(conn, organization_id=organization_id, principal_id=root_id)
    try:
        returned = conn.execute(
            """
            SELECT request_engine.invite_native_staff(
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                membership_id,
                principal_id,
                binding_id,
                authority_id,
                native_identity_id,
                party_id,
                f"binding-lifecycle-invite:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
        activated = conn.execute(
            """
            SELECT request_engine.transition_staff_membership(%s, 1, 'active', %s)
            """,
            (membership_id, f"binding-lifecycle-activate:{uuid4().hex}"),
        ).fetchone()
        assert activated == (2,)
        if promote:
            revision = principal_revision(conn, principal_id)
            promoted = conn.execute(
                """
                SELECT request_engine.replace_staff_authority(
                    %s, %s,
                    ARRAY[
                        'staff.manage_membership',
                        'staff.manage_authority',
                        'identity.bind'
                    ]::text[],
                    %s
                )
                """,
                (membership_id, revision, f"binding-lifecycle-promote:{uuid4().hex}"),
            ).fetchone()
            assert promoted is not None
    finally:
        reset_actor(conn)
    return membership_id, principal_id, binding_id


async def _transition(
    commands: PostgresIdentityBindingCommands,
    actor: ActorContext,
    binding_id: UUID,
    expected_revision: int,
    target: IdentityBindingTargetStatus,
    key: str,
) -> int:
    return await commands.transition_identity_binding(
        actor,
        TransitionIdentityBindingCommand(
            binding_id=binding_id,
            expected_revision=expected_revision,
            target_status=target,
            provenance_reference=f"binding-lifecycle:{key}",
            idempotency_key=key,
        ),
    )


@pytest.mark.asyncio
async def test_binding_lifecycle_transitions_and_revision(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _root_authority = provision_root(admin_conn)
    authority_id, native_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, staff_id, staff_binding = _invite_activate_promote(
        admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        root_id=root_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
        promote=True,
    )
    assert _binding_row(admin_conn, organization_id, staff_id)[1:] == ("active", 2)
    commands = PostgresIdentityBindingCommands(command_session_factory)
    actor = ActorContext(organization_id, root_id, frozenset())

    suspended = await _transition(
        commands,
        actor,
        staff_binding,
        2,
        IdentityBindingTargetStatus.SUSPENDED,
        "suspend-1",
    )
    assert suspended == 3
    assert _binding_row(admin_conn, organization_id, staff_id)[1:] == ("suspended", 3)

    # Exact replay of the same idempotent request returns the recorded revision
    # without a second transition.
    replay = await _transition(
        commands,
        actor,
        staff_binding,
        2,
        IdentityBindingTargetStatus.SUSPENDED,
        "suspend-1",
    )
    assert replay == 3
    assert _binding_row(admin_conn, organization_id, staff_id)[1:] == ("suspended", 3)

    reactivated = await _transition(
        commands,
        actor,
        staff_binding,
        3,
        IdentityBindingTargetStatus.ACTIVE,
        "reactivate-1",
    )
    assert reactivated == 4
    assert _binding_row(admin_conn, organization_id, staff_id)[1:] == ("active", 4)

    revoked = await _transition(
        commands,
        actor,
        staff_binding,
        4,
        IdentityBindingTargetStatus.REVOKED,
        "revoke-1",
    )
    assert revoked == 5
    row = admin_conn.execute(
        "SELECT status, revision, revoked_at FROM request_engine.identity_bindings WHERE id = %s",
        (staff_binding,),
    ).fetchone()
    assert row is not None
    assert row[0] == "revoked"
    assert int(row[1]) == 5
    assert row[2] is not None

    # Revoke is terminal: the same row cannot be reactivated.
    with pytest.raises(IdentityBindingLifecycleConflict):
        await _transition(
            commands,
            actor,
            staff_binding,
            5,
            IdentityBindingTargetStatus.ACTIVE,
            "reactivate-after-revoke",
        )
    assert _binding_row(admin_conn, organization_id, staff_id)[1:] == ("revoked", 5)

    # A stale revision is rejected without a state change.
    with pytest.raises(IdentityBindingLifecycleRevisionConflict):
        await _transition(
            commands,
            actor,
            staff_binding,
            99,
            IdentityBindingTargetStatus.SUSPENDED,
            "stale-revision",
        )


@pytest.mark.asyncio
async def test_binding_suspend_cannot_remove_last_controller(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _root_authority = provision_root(admin_conn)
    authority_id, native_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, staff_id, staff_binding = _invite_activate_promote(
        admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        root_id=root_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
        promote=True,
    )
    root_binding, root_status, root_revision = _binding_row(admin_conn, organization_id, root_id)
    commands = PostgresIdentityBindingCommands(command_session_factory)
    root_actor = ActorContext(organization_id, root_id, frozenset())

    # Suspending one of two controllers' bindings is allowed.
    assert (
        await _transition(
            commands,
            root_actor,
            staff_binding,
            2,
            IdentityBindingTargetStatus.SUSPENDED,
            "suspend-second-controller",
        )
        == 3
    )

    # The remaining controller may not suspend their own last authenticatable path.
    staff_actor = ActorContext(organization_id, staff_id, frozenset())
    with pytest.raises(IdentityBindingLifecycleConflict):
        await _transition(
            commands,
            staff_actor,
            root_binding,
            root_revision,
            IdentityBindingTargetStatus.SUSPENDED,
            "suspend-last-controller",
        )
    assert _binding_row(admin_conn, organization_id, root_id) == (
        root_binding,
        root_status,
        root_revision,
    )


@pytest.mark.asyncio
async def test_binding_lifecycle_is_tenant_scoped_and_grants_no_authority(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, root_id, _root_authority = provision_root(admin_conn)
    foreign_org, _foreign_party, foreign_root, _foreign_authority = provision_root(admin_conn)
    authority_id, native_identity_id, _credential_id = native_identity(admin_conn)
    _membership_id, staff_id, staff_binding = _invite_activate_promote(
        admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        root_id=root_id,
        authority_id=authority_id,
        native_identity_id=native_identity_id,
        promote=False,
    )
    foreign_binding, foreign_status, foreign_revision = _binding_row(
        admin_conn, foreign_org, foreign_root
    )
    grants_before = _active_grant_count(admin_conn, organization_id)
    commands = PostgresIdentityBindingCommands(command_session_factory)
    actor = ActorContext(organization_id, root_id, frozenset())

    # A human actor without the standing identity.bind authority is denied.
    with pytest.raises(IdentityBindingLifecycleForbidden):
        await _transition(
            commands,
            ActorContext(organization_id, staff_id, frozenset()),
            staff_binding,
            2,
            IdentityBindingTargetStatus.SUSPENDED,
            "unprivileged-actor",
        )

    # The foreign tenant's binding is never addressable.
    with pytest.raises(IdentityBindingLifecycleNotFound):
        await _transition(
            commands,
            actor,
            foreign_binding,
            1,
            IdentityBindingTargetStatus.SUSPENDED,
            "foreign-binding",
        )
    with pytest.raises(IdentityBindingLifecycleNotFound):
        await _transition(
            commands,
            actor,
            uuid4(),
            1,
            IdentityBindingTargetStatus.SUSPENDED,
            "random-binding",
        )
    assert _binding_row(admin_conn, foreign_org, foreign_root) == (
        foreign_binding,
        foreign_status,
        foreign_revision,
    )

    # A non-HUMAN actor is rejected before the database is touched.
    agent_actor = ActorContext(
        organization_id, root_id, frozenset(), principal_kind=PrincipalKind.AGENT
    )
    with pytest.raises(IdentityBindingLifecycleForbidden):
        await _transition(
            commands,
            agent_actor,
            staff_binding,
            2,
            IdentityBindingTargetStatus.SUSPENDED,
            "agent-actor",
        )

    # A successful transition grants no new authority.
    assert (
        await _transition(
            commands,
            actor,
            staff_binding,
            2,
            IdentityBindingTargetStatus.SUSPENDED,
            "scoped-suspend",
        )
        == 3
    )
    assert _active_grant_count(admin_conn, organization_id) == grants_before


def test_binding_lifecycle_function_takes_the_topology_gate_first(
    admin_conn: Connection[Any],
) -> None:
    definition = admin_conn.execute(
        "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'request_engine' AND p.proname = %s",
        ("transition_identity_binding",),
    ).fetchone()
    assert definition is not None
    body = str(definition[0])
    begin = body.index("BEGIN")
    first_statement = body[begin + len("BEGIN") :].lstrip()
    assert first_statement.startswith("PERFORM request_engine.acquire_identity_topology_share();")
    # The ordered staff root precedes the specific binding row lock.
    root_index = body.index("lock_tenant_staff_root()")
    binding_lock_index = body.index("FROM request_engine.identity_bindings")
    assert root_index < binding_lock_index
