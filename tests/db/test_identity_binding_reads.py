"""Tenant identity-binding read projection through the real app-role reader.

These proofs protect the current read guarantee for identity bindings:

- inspection requires an explicit current ``identity.binding.read`` grant and a
  HUMAN actor; a forged in-memory capability alone is denied;
- the projection is tenant-opaque: a foreign binding is indistinguishable from an
  absent one and a random UUID is never addressable;
- the projection never exposes the binding subject, verifier or authority secret;
- reads are mutation-free.
"""

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    provision_agent,
    provision_root,
    workload_authority,
)
from psycopg import Connection

from request_engine.modules.tenancy.adapters.db.identity_binding_admin_reader import (
    PostgresIdentityBindingAdminReader,
)
from request_engine.modules.tenancy.application.queries.identity_binding import (
    GetIdentityBindingQuery,
    IdentityBindingNotFound,
    IdentityBindingReadForbidden,
    ListIdentityBindingsQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]

_READ_CAPABILITY = "identity.binding.read"


def _oracle_bindings(conn: Connection[Any], organization_id: UUID) -> list[tuple[object, ...]]:
    """Independent authoritative projection for the same tenant scope."""

    return conn.execute(
        """
        SELECT binding.id, binding.principal_id, binding.identity_authority_id,
               authority.kind, binding.status, binding.revision
          FROM request_engine.identity_bindings binding
          JOIN request_engine.identity_authorities authority
            ON authority.id = binding.identity_authority_id
         WHERE binding.organization_id = %s
           AND binding.principal_plane = 'tenant'
         ORDER BY binding.id
        """,
        (organization_id,),
    ).fetchall()


def _mutation_fingerprint(conn: Connection[Any], organization_id: UUID) -> tuple[object, ...]:
    return (
        conn.execute(
            "SELECT count(*) FROM request_engine.identity_bindings WHERE organization_id=%s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.audit_records WHERE organization_id=%s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.outbox_messages WHERE organization_id=%s",
            (organization_id,),
        ).fetchone(),
    )


@pytest.mark.asyncio
async def test_binding_read_requires_authority_and_is_tenant_opaque(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _authority = provision_root(admin_conn)
    foreign_org, _, _, _ = provision_root(admin_conn)
    agent_principal, agent_binding, _, _, _ = provision_agent(
        admin_conn,
        organization_id=org,
        controller_id=controller,
        workload_authority_id=workload_authority(admin_conn),
    )
    actor = ActorContext(org, controller, frozenset({_READ_CAPABILITY}))
    reader = PostgresIdentityBindingAdminReader(command_session_factory)

    # A forged in-memory capability alone never satisfies the standing grant.
    with pytest.raises(IdentityBindingReadForbidden):
        await reader.list_bindings(actor, ListIdentityBindingsQuery())

    grant_delegable(
        admin_conn,
        principal_id=controller,
        organization_id=org,
        capability_key=_READ_CAPABILITY,
        authority_plane="tenant_control",
    )

    expected = _oracle_bindings(admin_conn, org)
    assert len(expected) >= 2
    assert {UUID(str(row[0])) for row in expected} >= {agent_binding}

    before = _mutation_fingerprint(admin_conn, org)
    rows = await reader.list_bindings(actor, ListIdentityBindingsQuery())
    assert [
        (row.binding_id, row.principal_id, row.identity_authority_id, row.status, row.revision)
        for row in rows
    ] == [(row[0], row[1], row[2], row[4], row[5]) for row in expected]
    assert agent_principal in {row.principal_id for row in rows}
    assert all(not hasattr(row, "subject_id") for row in rows)
    assert _mutation_fingerprint(admin_conn, org) == before

    # The foreign tenant's binding is not addressable and not listed.
    foreign_binding = _oracle_bindings(admin_conn, foreign_org)[0][0]
    with pytest.raises(IdentityBindingNotFound):
        await reader.read_binding(actor, GetIdentityBindingQuery(UUID(str(foreign_binding))))
    with pytest.raises(IdentityBindingNotFound):
        await reader.read_binding(actor, GetIdentityBindingQuery(uuid4()))
    assert all(row.binding_id != UUID(str(foreign_binding)) for row in rows)

    # A non-HUMAN actor is rejected before any row is read.
    workload_actor = replace(actor, principal_kind=PrincipalKind.AGENT)
    with pytest.raises(IdentityBindingReadForbidden):
        await reader.list_bindings(workload_actor, ListIdentityBindingsQuery())

    # Revoking the standing grant closes the surface again.
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key=%s AND status='active'",
        (controller, controller, _READ_CAPABILITY),
    )
    with pytest.raises(IdentityBindingReadForbidden):
        await reader.list_bindings(actor, ListIdentityBindingsQuery())


@pytest.mark.asyncio
async def test_binding_read_filters_and_cursor_are_bounded(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _authority = provision_root(admin_conn)
    agent_principal, agent_binding, _, _, _ = provision_agent(
        admin_conn,
        organization_id=org,
        controller_id=controller,
        workload_authority_id=workload_authority(admin_conn),
    )
    grant_delegable(
        admin_conn,
        principal_id=controller,
        organization_id=org,
        capability_key=_READ_CAPABILITY,
        authority_plane="tenant_control",
    )
    actor = ActorContext(org, controller, frozenset({_READ_CAPABILITY}))
    reader = PostgresIdentityBindingAdminReader(command_session_factory)

    by_principal = await reader.list_bindings(
        actor, ListIdentityBindingsQuery(principal_id=agent_principal)
    )
    assert [row.binding_id for row in by_principal] == [agent_binding]

    active = await reader.list_bindings(actor, ListIdentityBindingsQuery(status="active"))
    assert {row.binding_id for row in active} == {
        UUID(str(row[0])) for row in _oracle_bindings(admin_conn, org) if row[4] == "active"
    }

    suspended = await reader.list_bindings(actor, ListIdentityBindingsQuery(status="suspended"))
    assert suspended == ()

    ordered = sorted(UUID(str(row[0])) for row in _oracle_bindings(admin_conn, org))
    first = await reader.list_bindings(actor, ListIdentityBindingsQuery(limit=1))
    assert [row.binding_id for row in first] == [ordered[0]]
    second = await reader.list_bindings(
        actor, ListIdentityBindingsQuery(after=first[-1].binding_id, limit=1)
    )
    assert [row.binding_id for row in second] == [ordered[1]]

    with pytest.raises(ValueError):
        ListIdentityBindingsQuery(limit=101)
    with pytest.raises(ValueError):
        ListIdentityBindingsQuery(status="not-a-status")
