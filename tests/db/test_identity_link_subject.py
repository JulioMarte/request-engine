"""OIDC second-proof identity linking through the real app-role command.

Protects ``INV-IDENTITY-LINK-SELF-001`` at the database boundary for the
subject-based confirmation path:

- a verified external subject (verified at the HTTP boundary) creates a second
  active binding for the SAME tenant Principal under the intent's OIDC authority;
- the intent is consumed exactly once and an exact idempotency replay is a no-op;
- a native target authority is rejected because it has its own confirmation path;
- a subject already live for another Principal in the tenant conflicts;
- a foreign or random intent is indistinguishable from an absent one.
"""

import json
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    native_identity,
    provision_root,
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
    IdentityLinkNotFound,
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


def _oidc_authority(conn: Connection[Any]) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment, status, configuration_ref
        ) VALUES ('oidc', %s, 'active', %s) RETURNING id
        """,
        (
            f"https://idp-{uuid4().hex}.example.test",
            json.dumps(
                {
                    "jwks_uri": f"https://idp-{uuid4().hex}.example.test/.well-known/jwks.json",
                    "audience": "request-engine",
                }
            ),
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


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


def _seed_live_subject_binding(
    conn: Connection[Any],
    *,
    organization_id: UUID,
    identity_authority_id: UUID,
    subject_id: str,
) -> UUID:
    """Create a valid conflicting prerequisite: the subject is already linked."""

    principal_id = uuid4()
    conn.execute(
        """
        INSERT INTO request_engine.principals (
            id, organization_id, principal_kind, external_subject
        ) VALUES (%s, %s, 'human', %s)
        """,
        (principal_id, organization_id, f"identity-link-subject-other-{uuid4().hex}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.identity_bindings (
            organization_id, principal_id, principal_plane,
            identity_authority_id, subject_id, status
        ) VALUES (%s, %s, 'tenant', %s, %s, 'active')
        """,
        (organization_id, principal_id, identity_authority_id, subject_id),
    )
    return principal_id


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


async def _create_intent(
    commands: PostgresIdentityLinkCommands,
    actor: ActorContext,
    *,
    actor_binding_id: UUID,
    target_authority_id: UUID,
    key: str,
) -> IdentityLinkIntentReceipt:
    return await commands.create_identity_link_intent(
        actor,
        CreateIdentityLinkIntentCommand(
            intent_id=uuid4(),
            actor_binding_id=actor_binding_id,
            target_authority_id=target_authority_id,
            nonce_digest=uuid4().hex + uuid4().hex,
            ttl_seconds=_TTL_SECONDS,
            provenance_reference=f"identity-link:{key}",
            idempotency_key=key,
        ),
    )


async def _confirm_subject(
    commands: PostgresIdentityLinkCommands,
    actor: ActorContext,
    *,
    intent_id: UUID,
    expected_actor_binding_revision: int,
    subject_id: str,
    key: str,
) -> IdentityLinkBindingReceipt:
    return await commands.confirm_identity_link_intent(
        actor,
        ConfirmIdentityLinkIntentCommand(
            intent_id=intent_id,
            expected_actor_binding_revision=expected_actor_binding_revision,
            binding_id=uuid4(),
            provenance_reference=f"identity-link:{key}",
            idempotency_key=key,
            subject_id=subject_id,
        ),
    )


@pytest.mark.asyncio
async def test_oidc_subject_link_creates_binding_and_consumes_intent_once(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    oidc_authority = _oidc_authority(admin_conn)
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
    subject_id = f"oidc-subject-{uuid4().hex}"

    created = await _create_intent(
        commands,
        actor,
        actor_binding_id=actor_binding,
        target_authority_id=oidc_authority,
        key="oidc-link-create-1",
    )
    assert created.target_authority_id == oidc_authority

    confirmed = await _confirm_subject(
        commands,
        actor,
        intent_id=created.intent_id,
        expected_actor_binding_revision=1,
        subject_id=subject_id,
        key="oidc-link-confirm-1",
    )
    assert confirmed.principal_id == controller_id
    assert confirmed.binding_revision == 1

    binding = admin_conn.execute(
        "SELECT principal_id, subject_id, identity_authority_id, status "
        "FROM request_engine.identity_bindings WHERE id = %s",
        (confirmed.binding_id,),
    ).fetchone()
    assert binding == (controller_id, subject_id, oidc_authority, "active")
    assert _intent_state(admin_conn, created.intent_id)[0] == "consumed"
    assert _intent_state(admin_conn, created.intent_id)[2] == confirmed.binding_id
    assert _facts(admin_conn, created.intent_id) == ["intent_created", "linked"]

    # Exact idempotency replay returns the same receipt without a second binding.
    replay = await _confirm_subject(
        commands,
        actor,
        intent_id=created.intent_id,
        expected_actor_binding_revision=1,
        subject_id=subject_id,
        key="oidc-link-confirm-1",
    )
    assert replay == confirmed

    # A second confirmation under a different key cannot consume the intent twice.
    with pytest.raises(IdentityLinkConflict):
        await _confirm_subject(
            commands,
            actor,
            intent_id=created.intent_id,
            expected_actor_binding_revision=1,
            subject_id=subject_id,
            key="oidc-link-confirm-2",
        )
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings "
        "WHERE identity_authority_id = %s AND subject_id = %s AND status <> 'revoked'",
        (oidc_authority, subject_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_subject_link_rejects_a_native_target_authority(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    native_authority, _native_identity_id, _credential = native_identity(admin_conn)
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
        target_authority_id=native_authority,
        key="oidc-link-native-create",
    )
    with pytest.raises(IdentityLinkConflict):
        await _confirm_subject(
            commands,
            actor,
            intent_id=created.intent_id,
            expected_actor_binding_revision=1,
            subject_id=f"native-subject-{uuid4().hex}",
            key="oidc-link-native-confirm",
        )
    assert _intent_state(admin_conn, created.intent_id)[0] == "pending"


@pytest.mark.asyncio
async def test_subject_already_live_in_tenant_conflicts(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    oidc_authority = _oidc_authority(admin_conn)
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
    subject_id = f"oidc-subject-{uuid4().hex}"
    _seed_live_subject_binding(
        admin_conn,
        organization_id=organization_id,
        identity_authority_id=oidc_authority,
        subject_id=subject_id,
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())

    created = await _create_intent(
        commands,
        actor,
        actor_binding_id=actor_binding,
        target_authority_id=oidc_authority,
        key="oidc-link-duplicate-create",
    )
    with pytest.raises(IdentityLinkConflict):
        await _confirm_subject(
            commands,
            actor,
            intent_id=created.intent_id,
            expected_actor_binding_revision=1,
            subject_id=subject_id,
            key="oidc-link-duplicate-confirm",
        )
    assert _intent_state(admin_conn, created.intent_id)[0] == "pending"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings "
        "WHERE identity_authority_id = %s AND subject_id = %s AND status <> 'revoked'",
        (oidc_authority, subject_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_foreign_and_random_intents_are_opaque_to_subject_confirmation(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    foreign_org, _foreign_party, foreign_controller, _foreign_authority = provision_root(admin_conn)
    oidc_authority = _oidc_authority(admin_conn)
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
        target_authority_id=oidc_authority,
        key="oidc-link-foreign-create",
    )

    for intent_id, key in (
        (uuid4(), "oidc-link-random-confirm"),
        (foreign_intent.intent_id, "oidc-link-foreign-confirm"),
    ):
        with pytest.raises(IdentityLinkNotFound):
            await _confirm_subject(
                commands,
                actor,
                intent_id=intent_id,
                expected_actor_binding_revision=1,
                subject_id=f"oidc-subject-{uuid4().hex}",
                key=key,
            )


def test_subject_confirmation_takes_the_topology_gate_first(
    admin_conn: Connection[Any],
) -> None:
    definition = admin_conn.execute(
        "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'request_engine' AND p.proname = 'confirm_identity_link_subject'"
    ).fetchone()
    assert definition is not None
    body = str(definition[0])
    begin = body.index("BEGIN")
    first_statement = body[begin + len("BEGIN") :].lstrip()
    assert first_statement.startswith("PERFORM request_engine.acquire_identity_topology_share();")
    root_index = body.index("lock_tenant_staff_root()")
    actor_index = body.index("assert_staff_manager('identity.link_self')")
    assert root_index < actor_index


def test_subject_confirmation_grant_is_limited_to_the_app_role(
    admin_conn: Connection[Any],
) -> None:
    grants = admin_conn.execute(
        """
        SELECT has_function_privilege(
                   'request_engine_app',
                   'request_engine.confirm_identity_link_subject(uuid, bigint, text, uuid, text)',
                   'EXECUTE'
               ),
               has_function_privilege(
                   'request_engine_worker',
                   'request_engine.confirm_identity_link_subject(uuid, bigint, text, uuid, text)',
                   'EXECUTE'
               )
        """
    ).fetchone()
    assert grants == (True, False)
