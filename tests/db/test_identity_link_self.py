"""Self-service dual-proof identity linking through the real app-role command.

Protects ``INV-IDENTITY-LINK-SELF-001``:

- a HUMAN actor with a current ``identity.link_self`` grant and an active tenant
  binding creates a short-TTL intent and consumes it exactly once to create a
  second active binding for the SAME tenant Principal;
- the actor binding revision captured by the intent is revalidated, so a stale
  actor binding cannot confirm;
- an expired or already-consumed intent cannot be confirmed;
- a subject already live for another Principal in the tenant conflicts;
- a foreign or random intent is indistinguishable from an absent one;
- an actor without the standing grant is denied;
- linking never creates or mutates grants, memberships or another Principal.

The second identity's password is verified at the HTTP boundary; these DB
proofs exercise the authoritative primitive that re-locks the credentialed
native identity and creates the binding.
"""

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    native_identity,
    principal_revision,
    provision_root,
    reset_actor,
    set_tenant_actor,
)
from psycopg import Connection

from request_engine.modules.tenancy.adapters.db.identity_link_commands import (
    PostgresIdentityLinkCommands,
)
from request_engine.modules.tenancy.application.commands.identity_link import (
    ConfirmIdentityLinkIntentCommand,
    CreateIdentityLinkIntentCommand,
    IdentityLinkBindingReceipt,
    IdentityLinkIntentReceipt,
)
from request_engine.modules.tenancy.application.errors import (
    IdentityLinkConflict,
    IdentityLinkForbidden,
    IdentityLinkNotFound,
    IdentityLinkRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

_LINK_CAPABILITY = "identity.link_self"
_TTL_SECONDS = 300


def _active_binding_id(conn: Connection[Any], *, organization_id: UUID, principal_id: UUID) -> UUID:
    row = conn.execute(
        """
        SELECT id FROM request_engine.identity_bindings
         WHERE organization_id = %s AND principal_id = %s
           AND principal_plane = 'tenant' AND status = 'active'
        """,
        (organization_id, principal_id),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _binding_state(conn: Connection[Any], binding_id: UUID) -> tuple[str, int, str | None]:
    row = conn.execute(
        "SELECT status, revision, subject_id FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1]), cast(str | None, row[2])


def _intent_state(conn: Connection[Any], intent_id: UUID) -> tuple[str, object, object]:
    row = conn.execute(
        "SELECT status, consumed_at, resulting_binding_id "
        "FROM request_engine.identity_link_intents WHERE id = %s",
        (intent_id,),
    ).fetchone()
    assert row is not None
    return str(row[0]), row[1], row[2]


def _facts(conn: Connection[Any], intent_id: UUID) -> list[str]:
    rows = conn.execute(
        "SELECT action FROM request_engine.identity_link_facts "
        "WHERE intent_id = %s ORDER BY created_at, id",
        (intent_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _counts(conn: Connection[Any], organization_id: UUID) -> tuple[int, int, int]:
    grants = conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE organization_id = %s AND status = 'active'",
        (organization_id,),
    ).fetchone()
    memberships = conn.execute(
        "SELECT count(*) FROM request_engine.staff_memberships "
        "WHERE organization_id = %s AND status = 'active'",
        (organization_id,),
    ).fetchone()
    principals = conn.execute(
        "SELECT count(*) FROM request_engine.principals WHERE organization_id = %s",
        (organization_id,),
    ).fetchone()
    assert grants is not None and memberships is not None and principals is not None
    return int(grants[0]), int(memberships[0]), int(principals[0])


def _invite_activate_staff(
    conn: Connection[Any],
    *,
    organization_id: UUID,
    party_id: UUID,
    controller_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    membership_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    set_tenant_actor(conn, organization_id=organization_id, principal_id=controller_id)
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
                f"identity-link-invite:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
        activated = conn.execute(
            "SELECT request_engine.transition_staff_membership(%s, 1, 'active', %s)",
            (membership_id, f"identity-link-activate:{uuid4().hex}"),
        ).fetchone()
        assert activated == (2,)
    finally:
        reset_actor(conn)
    return membership_id, principal_id


def _promote_to_controller(
    conn: Connection[Any],
    *,
    organization_id: UUID,
    controller_id: UUID,
    membership_id: UUID,
    principal_id: UUID,
) -> None:
    revision = principal_revision(conn, principal_id)
    set_tenant_actor(conn, organization_id=organization_id, principal_id=controller_id)
    try:
        promoted = conn.execute(
            "SELECT request_engine.replace_staff_authority(%s, %s, %s::text[], %s)",
            (
                membership_id,
                revision,
                [
                    "staff.manage_membership",
                    "staff.manage_authority",
                    "identity.bind",
                ],
                f"identity-link-promote:{uuid4().hex}",
            ),
        ).fetchone()
        assert promoted is not None
    finally:
        reset_actor(conn)


async def _create_intent(
    commands: PostgresIdentityLinkCommands,
    actor: ActorContext,
    *,
    actor_binding_id: UUID,
    target_authority_id: UUID,
    key: str,
    ttl_seconds: int = _TTL_SECONDS,
) -> IdentityLinkIntentReceipt:
    return await commands.create_identity_link_intent(
        actor,
        CreateIdentityLinkIntentCommand(
            intent_id=uuid4(),
            actor_binding_id=actor_binding_id,
            target_authority_id=target_authority_id,
            nonce_digest=uuid4().hex + uuid4().hex,
            ttl_seconds=ttl_seconds,
            provenance_reference=f"identity-link:{key}",
            idempotency_key=key,
        ),
    )


async def _confirm_intent(
    commands: PostgresIdentityLinkCommands,
    actor: ActorContext,
    *,
    intent_id: UUID,
    expected_actor_binding_revision: int,
    native_identity_id: UUID,
    key: str,
) -> IdentityLinkBindingReceipt:
    return await commands.confirm_identity_link_intent(
        actor,
        ConfirmIdentityLinkIntentCommand(
            intent_id=intent_id,
            expected_actor_binding_revision=expected_actor_binding_revision,
            native_identity_id=native_identity_id,
            binding_id=uuid4(),
            provenance_reference=f"identity-link:{key}",
            idempotency_key=key,
        ),
    )


@pytest.mark.asyncio
async def test_self_link_creates_binding_for_same_principal_and_consumes_intent_once(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    second_authority, second_identity, _credential = native_identity(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_LINK_CAPABILITY,
        authority_plane="tenant_control",
    )
    actor_binding = _active_binding_id(
        admin_conn, organization_id=organization_id, principal_id=controller_id
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())
    before = _counts(admin_conn, organization_id)

    created = await _create_intent(
        commands,
        actor,
        actor_binding_id=actor_binding,
        target_authority_id=second_authority,
        key="link-create-1",
    )
    intent_id = created.intent_id
    assert created.target_authority_id == second_authority
    assert _intent_state(admin_conn, intent_id)[0] == "pending"

    confirmed = await _confirm_intent(
        commands,
        actor,
        intent_id=intent_id,
        expected_actor_binding_revision=1,
        native_identity_id=second_identity,
        key="link-confirm-1",
    )
    assert confirmed.principal_id == controller_id
    assert confirmed.binding_revision == 1
    new_binding_id = confirmed.binding_id

    status, revision, subject_id = _binding_state(admin_conn, new_binding_id)
    assert (status, revision, subject_id) == ("active", 1, str(second_identity))
    assert _intent_state(admin_conn, intent_id)[0] == "consumed"
    assert _intent_state(admin_conn, intent_id)[2] == new_binding_id
    assert _facts(admin_conn, intent_id) == ["intent_created", "linked"]

    # Exact replay under the still-authorized actor returns the same receipt and
    # does not create a second binding.
    replay = await _confirm_intent(
        commands,
        actor,
        intent_id=intent_id,
        expected_actor_binding_revision=1,
        native_identity_id=second_identity,
        key="link-confirm-1",
    )
    assert replay == confirmed
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings "
        "WHERE organization_id = %s AND principal_id = %s AND status <> 'revoked'",
        (organization_id, controller_id),
    ).fetchone() == (2,)

    # A second confirmation under a different key cannot consume the intent twice.
    with pytest.raises(IdentityLinkConflict):
        await _confirm_intent(
            commands,
            actor,
            intent_id=intent_id,
            expected_actor_binding_revision=1,
            native_identity_id=second_identity,
            key="link-confirm-2",
        )

    # Linking grants no authority and creates no membership or extra Principal.
    assert _counts(admin_conn, organization_id) == before


@pytest.mark.asyncio
async def test_self_link_conflicts_when_subject_already_linked_to_second_principal(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, controller_id, _root_authority = provision_root(admin_conn)
    second_authority, second_identity, _credential = native_identity(admin_conn)
    staff_authority, staff_identity, _staff_credential = native_identity(admin_conn)
    _staff_membership, staff_id = _invite_activate_staff(
        admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        controller_id=controller_id,
        authority_id=staff_authority,
        native_identity_id=staff_identity,
    )
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_LINK_CAPABILITY,
        authority_plane="tenant_control",
    )
    grant_delegable(
        admin_conn,
        principal_id=staff_id,
        organization_id=organization_id,
        capability_key=_LINK_CAPABILITY,
        authority_plane="tenant_control",
    )
    controller_binding = _active_binding_id(
        admin_conn, organization_id=organization_id, principal_id=controller_id
    )
    staff_binding = _active_binding_id(
        admin_conn, organization_id=organization_id, principal_id=staff_id
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    controller = ActorContext(organization_id, controller_id, frozenset())
    staff_actor = ActorContext(organization_id, staff_id, frozenset())

    # The controller links the second identity.
    first = await _create_intent(
        commands,
        controller,
        actor_binding_id=controller_binding,
        target_authority_id=second_authority,
        key="link-owner-create",
    )
    await _confirm_intent(
        commands,
        controller,
        intent_id=first.intent_id,
        expected_actor_binding_revision=1,
        native_identity_id=second_identity,
        key="link-owner-confirm",
    )

    # A second Principal cannot take the same subject in the same tenant.
    second = await _create_intent(
        commands,
        staff_actor,
        actor_binding_id=staff_binding,
        target_authority_id=second_authority,
        key="link-takeover-create",
    )
    with pytest.raises(IdentityLinkConflict):
        await _confirm_intent(
            commands,
            staff_actor,
            intent_id=second.intent_id,
            expected_actor_binding_revision=2,
            native_identity_id=second_identity,
            key="link-takeover-confirm",
        )
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings "
        "WHERE identity_authority_id = %s AND subject_id = %s AND status <> 'revoked'",
        (second_authority, str(second_identity)),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_expired_intent_cannot_be_confirmed(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    second_authority, second_identity, _credential = native_identity(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_LINK_CAPABILITY,
        authority_plane="tenant_control",
    )
    actor_binding = _active_binding_id(
        admin_conn, organization_id=organization_id, principal_id=controller_id
    )
    # Backdated pending intent: production cannot create an already-expired intent
    # without waiting, so the precondition is built directly.
    intent_id = uuid4()
    admin_conn.execute(
        """
        INSERT INTO request_engine.identity_link_intents (
            id, organization_id, actor_principal_id, actor_binding_id,
            target_authority_id, actor_binding_revision, nonce_digest,
            status, expires_at, provenance_reference, created_at
        ) VALUES (
            %s, %s, %s, %s, %s, 1, %s, 'pending',
            clock_timestamp() - interval '1 minute',
            %s, clock_timestamp() - interval '10 minutes'
        )
        """,
        (
            intent_id,
            organization_id,
            controller_id,
            actor_binding,
            second_authority,
            uuid4().hex + uuid4().hex,
            f"identity-link-expired:{uuid4().hex}",
        ),
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())

    with pytest.raises(IdentityLinkConflict):
        await _confirm_intent(
            commands,
            actor,
            intent_id=intent_id,
            expected_actor_binding_revision=1,
            native_identity_id=second_identity,
            key="link-expired-confirm",
        )
    assert _intent_state(admin_conn, intent_id)[0] == "pending"


@pytest.mark.asyncio
async def test_stale_actor_binding_revision_is_rejected(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, party_id, controller_id, _root_authority = provision_root(admin_conn)
    second_authority, second_identity, _credential = native_identity(admin_conn)
    staff_authority, staff_identity, _staff_credential = native_identity(admin_conn)
    staff_membership, staff_id = _invite_activate_staff(
        admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        controller_id=controller_id,
        authority_id=staff_authority,
        native_identity_id=staff_identity,
    )
    # A second effective controller preserves continuity while the first
    # controller's binding is suspended and reactivated.
    _promote_to_controller(
        admin_conn,
        organization_id=organization_id,
        controller_id=controller_id,
        membership_id=staff_membership,
        principal_id=staff_id,
    )
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_LINK_CAPABILITY,
        authority_plane="tenant_control",
    )
    actor_binding = _active_binding_id(
        admin_conn, organization_id=organization_id, principal_id=controller_id
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())
    created = await _create_intent(
        commands,
        actor,
        actor_binding_id=actor_binding,
        target_authority_id=second_authority,
        key="link-stale-create",
    )
    intent_id = created.intent_id

    # Suspend then reactivate the actor binding so its revision advances while it
    # remains active; the intent still holds the earlier revision.
    set_tenant_actor(admin_conn, organization_id=organization_id, principal_id=controller_id)
    try:
        admin_conn.execute(
            "SELECT request_engine.transition_identity_binding(%s, 1, 'suspended', %s)",
            (actor_binding, f"identity-link-stale:{uuid4().hex}"),
        )
        admin_conn.execute(
            "SELECT request_engine.transition_identity_binding(%s, 2, 'active', %s)",
            (actor_binding, f"identity-link-stale:{uuid4().hex}"),
        )
    finally:
        reset_actor(admin_conn)
    assert _binding_state(admin_conn, actor_binding)[:2] == ("active", 3)

    with pytest.raises(IdentityLinkRevisionConflict):
        await _confirm_intent(
            commands,
            actor,
            intent_id=intent_id,
            expected_actor_binding_revision=1,
            native_identity_id=second_identity,
            key="link-stale-confirm",
        )
    assert _intent_state(admin_conn, intent_id)[0] == "pending"


@pytest.mark.asyncio
async def test_foreign_and_random_intents_are_opaque(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    foreign_org, _foreign_party, foreign_controller, _foreign_authority = provision_root(admin_conn)
    second_authority, second_identity, _credential = native_identity(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key=_LINK_CAPABILITY,
        authority_plane="tenant_control",
    )
    grant_delegable(
        admin_conn,
        principal_id=foreign_controller,
        organization_id=foreign_org,
        capability_key=_LINK_CAPABILITY,
        authority_plane="tenant_control",
    )
    foreign_binding = _active_binding_id(
        admin_conn, organization_id=foreign_org, principal_id=foreign_controller
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())
    foreign_actor = ActorContext(foreign_org, foreign_controller, frozenset())

    foreign_intent = await _create_intent(
        commands,
        foreign_actor,
        actor_binding_id=foreign_binding,
        target_authority_id=second_authority,
        key="link-foreign-create",
    )

    for intent_id, key in (
        (uuid4(), "link-random-confirm"),
        (foreign_intent.intent_id, "link-foreign-confirm"),
    ):
        with pytest.raises(IdentityLinkNotFound):
            await _confirm_intent(
                commands,
                actor,
                intent_id=intent_id,
                expected_actor_binding_revision=1,
                native_identity_id=second_identity,
                key=key,
            )


@pytest.mark.asyncio
async def test_actor_without_link_grant_is_forbidden(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    second_authority, second_identity, _credential = native_identity(admin_conn)
    actor_binding = _active_binding_id(
        admin_conn, organization_id=organization_id, principal_id=controller_id
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())

    # The root controller has staff control grants but not identity.link_self.
    with pytest.raises(IdentityLinkForbidden):
        await _create_intent(
            commands,
            actor,
            actor_binding_id=actor_binding,
            target_authority_id=second_authority,
            key="link-no-grant-create",
        )
    with pytest.raises(IdentityLinkForbidden):
        await _confirm_intent(
            commands,
            actor,
            intent_id=uuid4(),
            expected_actor_binding_revision=1,
            native_identity_id=second_identity,
            key="link-no-grant-confirm",
        )
    assert principal_revision(admin_conn, controller_id) > 0


def test_link_functions_take_the_topology_gate_first(
    admin_conn: Connection[Any],
) -> None:
    for function_name in (
        "create_identity_link_intent",
        "confirm_identity_link_intent",
    ):
        definition = admin_conn.execute(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'request_engine' AND p.proname = %s",
            (function_name,),
        ).fetchone()
        assert definition is not None
        body = str(definition[0])
        begin = body.index("BEGIN")
        first_statement = body[begin + len("BEGIN") :].lstrip()
        assert first_statement.startswith(
            "PERFORM request_engine.acquire_identity_topology_share();"
        ), function_name
        root_index = body.index("lock_tenant_staff_root()")
        actor_index = body.index("assert_staff_manager('identity.link_self')")
        assert root_index < actor_index, function_name
