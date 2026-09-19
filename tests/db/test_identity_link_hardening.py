"""Identity-link hardening: one live intent per actor+authority and intent reads.

Protects ``INV-IDENTITY-LINK-SELF-001`` at the database boundary:

- two independent connections that race the same ``(actor, authority)`` create
  leave exactly one pending intent; the loser is rejected as a conflict;
- a stale pending intent is expired before a new one is created, so the partial
  unique index never blocks a legitimate re-request;
- the tenant-scoped intent reader is opaque to a foreign organization's intent.
"""

import threading
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_governance_support import (
    grant_delegable,
    native_identity,
    provision_root,
    set_tenant_actor,
)
from native_authority_gate_support import wait_for_lock_wait
from psycopg import Connection

from request_engine.modules.tenancy.adapters.db.identity_link_commands import (
    PostgresIdentityLinkCommands,
)
from request_engine.modules.tenancy.adapters.db.identity_link_intent_reader import (
    PostgresIdentityLinkIntentReader,
)
from request_engine.modules.tenancy.application.commands.identity_link import (
    CreateIdentityLinkIntentCommand,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.concurrency,
]

_LINK_CAPABILITY = "identity.link_self"
_TTL_SECONDS = 300
_CREATE_SQL = """
    SELECT intent_id, expires_at, target_authority_id
      FROM request_engine.create_identity_link_intent(
          %s, %s, %s, %s, %s, %s
      )
"""


def _active_binding_id(conn: PgConnection, *, organization_id: UUID, principal_id: UUID) -> UUID:
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


def _pending_count(conn: PgConnection, *, organization_id: UUID, actor_principal_id: UUID) -> int:
    row = conn.execute(
        """
        SELECT count(*) FROM request_engine.identity_link_intents
         WHERE organization_id = %s AND actor_principal_id = %s AND status = 'pending'
        """,
        (organization_id, actor_principal_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _call_create(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    actor_binding_id: UUID,
    target_authority_id: UUID,
    key: str,
) -> tuple[UUID, object, UUID]:
    set_tenant_actor(conn, organization_id=organization_id, principal_id=principal_id)
    row = conn.execute(
        _CREATE_SQL,
        (
            uuid4(),
            actor_binding_id,
            target_authority_id,
            uuid4().hex + uuid4().hex,
            _TTL_SECONDS,
            f"identity-link-hardening:{key}",
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0]), row[1], cast(UUID, row[2])


def test_concurrent_duplicate_create_leaves_exactly_one_pending_intent(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    target_authority, _identity, _credential = native_identity(admin_conn)
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

    first = psycopg.connect(pg_conninfo, autocommit=False)
    second = psycopg.connect(pg_conninfo, autocommit=False)
    loser: dict[str, object] = {}

    def second_create() -> None:
        try:
            _call_create(
                second,
                organization_id=organization_id,
                principal_id=controller_id,
                actor_binding_id=actor_binding,
                target_authority_id=target_authority,
                key="loser",
            )
            second.commit()
            loser["state"] = "committed"
        except psycopg.Error as exc:
            second.rollback()
            loser["state"] = exc

    try:
        second_pid = second.execute("SELECT pg_backend_pid()").fetchone()
        assert second_pid is not None

        # The first connection inserts a pending intent and holds its row locks.
        _call_create(
            first,
            organization_id=organization_id,
            principal_id=controller_id,
            actor_binding_id=actor_binding,
            target_authority_id=target_authority,
            key="winner",
        )

        worker = threading.Thread(target=second_create)
        worker.start()
        assert wait_for_lock_wait(admin_conn, int(second_pid[0]))
        first.commit()
        worker.join(timeout=30)

        error = loser.get("state")
        assert isinstance(error, psycopg.Error)
        assert error.sqlstate == "23505"
        assert (
            _pending_count(
                admin_conn, organization_id=organization_id, actor_principal_id=controller_id
            )
            == 1
        )

        # The partial unique index is the independent database backstop: even a
        # direct insert of a second live intent for the same key is rejected.
        with pytest.raises(psycopg.errors.UniqueViolation) as duplicate:
            admin_conn.execute(
                """
                INSERT INTO request_engine.identity_link_intents (
                    id, organization_id, actor_principal_id, actor_binding_id,
                    target_authority_id, actor_binding_revision, nonce_digest,
                    status, expires_at, provenance_reference
                ) VALUES (
                    %s, %s, %s, %s, %s, 1, %s, 'pending',
                    clock_timestamp() + interval '5 minutes', %s
                )
                """,
                (
                    uuid4(),
                    organization_id,
                    controller_id,
                    actor_binding,
                    target_authority,
                    uuid4().hex + uuid4().hex,
                    f"identity-link-duplicate:{uuid4().hex}",
                ),
            )
        assert duplicate.value.diag.constraint_name == "identity_link_intents_live_uq"
    finally:
        first.close()
        second.close()


@pytest.mark.asyncio
async def test_stale_pending_intent_is_expired_before_a_new_one_is_created(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    target_authority, _identity, _credential = native_identity(admin_conn)
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
    stale_intent_id = uuid4()
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
            stale_intent_id,
            organization_id,
            controller_id,
            actor_binding,
            target_authority,
            uuid4().hex + uuid4().hex,
            f"identity-link-stale:{uuid4().hex}",
        ),
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())

    receipt = await commands.create_identity_link_intent(
        actor,
        CreateIdentityLinkIntentCommand(
            intent_id=uuid4(),
            actor_binding_id=actor_binding,
            target_authority_id=target_authority,
            nonce_digest=uuid4().hex + uuid4().hex,
            ttl_seconds=_TTL_SECONDS,
            provenance_reference=f"identity-link-fresh:{uuid4().hex}",
            idempotency_key="link-hardening-fresh",
        ),
    )

    stale_status = admin_conn.execute(
        "SELECT status FROM request_engine.identity_link_intents WHERE id = %s",
        (stale_intent_id,),
    ).fetchone()
    assert stale_status == ("expired",)
    assert (
        _pending_count(
            admin_conn, organization_id=organization_id, actor_principal_id=controller_id
        )
        == 1
    )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.identity_link_intents WHERE id = %s",
        (receipt.intent_id,),
    ).fetchone() == ("pending",)


@pytest.mark.asyncio
async def test_intent_reader_is_opaque_to_a_foreign_organization(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _root_authority = provision_root(admin_conn)
    foreign_org, _foreign_party, foreign_controller, _foreign_authority = provision_root(admin_conn)
    target_authority, _identity, _credential = native_identity(admin_conn)
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
    actor_binding = _active_binding_id(
        admin_conn, organization_id=organization_id, principal_id=controller_id
    )
    foreign_binding = _active_binding_id(
        admin_conn, organization_id=foreign_org, principal_id=foreign_controller
    )
    commands = PostgresIdentityLinkCommands(command_session_factory)
    actor = ActorContext(organization_id, controller_id, frozenset())
    foreign_actor = ActorContext(foreign_org, foreign_controller, frozenset())
    reader = PostgresIdentityLinkIntentReader(command_session_factory)

    own = await commands.create_identity_link_intent(
        actor,
        CreateIdentityLinkIntentCommand(
            intent_id=uuid4(),
            actor_binding_id=actor_binding,
            target_authority_id=target_authority,
            nonce_digest=uuid4().hex + uuid4().hex,
            ttl_seconds=_TTL_SECONDS,
            provenance_reference=f"identity-link-own:{uuid4().hex}",
            idempotency_key="link-hardening-own",
        ),
    )
    foreign = await commands.create_identity_link_intent(
        foreign_actor,
        CreateIdentityLinkIntentCommand(
            intent_id=uuid4(),
            actor_binding_id=foreign_binding,
            target_authority_id=target_authority,
            nonce_digest=uuid4().hex + uuid4().hex,
            ttl_seconds=_TTL_SECONDS,
            provenance_reference=f"identity-link-foreign:{uuid4().hex}",
            idempotency_key="link-hardening-foreign",
        ),
    )

    snapshot = await reader.read_intent(actor, intent_id=own.intent_id)
    assert snapshot is not None
    assert snapshot.actor_principal_id == controller_id
    assert snapshot.target_authority_id == target_authority
    assert snapshot.target_authority_kind == "native"
    assert snapshot.status == "pending"

    assert await reader.read_intent(actor, intent_id=foreign.intent_id) is None
    assert await reader.read_intent(actor, intent_id=uuid4()) is None
