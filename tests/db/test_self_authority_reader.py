"""Self-only current relationship snapshots through the real app-role reader."""

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_governance_support import grant_delegable, provision_root
from psycopg import Connection

from request_engine.modules.tenancy.adapters.db.self_authority_reader import (
    PostgresSelfAuthorityReader,
)
from request_engine.modules.tenancy.application.queries.self_authority import (
    AuthorityInspectionDenied,
    SelfAuthorityQuery,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]


def _second_tenant_principal(
    conn: Connection[Any],
    *,
    organization_id: UUID,
    scope_key: str,
    principal_kind: str = "human",
) -> tuple[UUID, UUID]:
    """Create a same-tenant Principal with one current Party relationship."""

    principal_id = uuid4()
    party_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.principals "
        "(id, organization_id, principal_kind, external_subject) "
        "VALUES (%s, %s, %s, %s)",
        (principal_id, organization_id, principal_kind, f"self-authority-{principal_id}"),
    )
    conn.execute(
        "INSERT INTO request_engine.parties "
        "(id, organization_id, party_kind, display_name) VALUES (%s, %s, 'person', %s)",
        (party_id, organization_id, f"Second Principal {party_id.hex[:8]}"),
    )
    conn.execute(
        "INSERT INTO request_engine.representations ("
        "organization_id, principal_id, represented_party_id, authority_kind, scope_key, "
        "valid_from) VALUES (%s, %s, %s, 'delegated', %s, clock_timestamp())",
        (organization_id, principal_id, party_id, scope_key),
    )
    return principal_id, party_id


def _tenant_state_fingerprint(
    conn: Connection[Any], *, organization_id: UUID, principal_id: UUID
) -> tuple[object, ...]:
    """Independent durable oracle for mutation-free reads."""

    return (
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
        conn.execute(
            "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
            (principal_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.representations WHERE organization_id=%s",
            (organization_id,),
        ).fetchone(),
    )


@pytest.mark.asyncio
async def test_self_authority_is_current_bounded_and_tenant_opaque(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, party, controller, _ = provision_root(admin_conn)
    other_org, _, _, _ = provision_root(admin_conn)
    actor = ActorContext(org, controller, frozenset({"authority.read_self"}))
    reader = PostgresSelfAuthorityReader(command_session_factory)
    with pytest.raises(AuthorityInspectionDenied):
        await reader.read_self(actor, SelfAuthorityQuery())
    grant_delegable(
        admin_conn,
        principal_id=controller,
        organization_id=org,
        capability_key="authority.read_self",
        authority_plane="operational",
    )
    expected = admin_conn.execute(
        "SELECT id, revision FROM request_engine.representations "
        "WHERE organization_id=%s AND principal_id=%s ORDER BY id",
        (org, controller),
    ).fetchall()
    assert len(expected) == 4
    first = await reader.read_self(actor, SelfAuthorityQuery(limit=2))
    second = await reader.read_self(actor, SelfAuthorityQuery(after=first.next_after, limit=2))
    assert first.next_after == expected[1][0]
    assert second.next_after is None
    items = (*first.representations, *second.representations)
    assert [(item.representation_id, item.revision) for item in items] == expected
    assert {item.represented_party_id for item in items} == {party}
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
        (controller,),
    ).fetchone() == (first.authority_revision,)
    with pytest.raises(AuthorityInspectionDenied):
        await reader.read_self(replace(actor, organization_id=other_org), SelfAuthorityQuery())
    with pytest.raises(AuthorityInspectionDenied):
        await reader.read_self(replace(actor, capabilities=frozenset()), SelfAuthorityQuery())
    with pytest.raises(ValueError):
        await reader.read_self(actor, SelfAuthorityQuery(limit=101))
    assert (
        admin_conn.execute(
            "SELECT id, revision FROM request_engine.representations "
            "WHERE organization_id=%s AND principal_id=%s ORDER BY id",
            (org, controller),
        ).fetchall()
        == expected
    )
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='authority.read_self' AND status='active'",
        (controller, controller),
    )
    with pytest.raises(AuthorityInspectionDenied):
        await reader.read_self(actor, SelfAuthorityQuery())


@pytest.mark.asyncio
async def test_self_authority_omits_noncurrent_relationships_and_inactive_parties(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, party, controller, _ = provision_root(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller,
        organization_id=org,
        capability_key="authority.read_self",
        authority_plane="operational",
    )
    actor = ActorContext(org, controller, frozenset({"authority.read_self"}))
    reader = PostgresSelfAuthorityReader(command_session_factory)
    ids = [
        row[0]
        for row in admin_conn.execute(
            "SELECT id FROM request_engine.representations WHERE organization_id=%s "
            "AND principal_id=%s ORDER BY id",
            (org, controller),
        ).fetchall()
    ]
    assert len(ids) == 4
    admin_conn.execute(
        "UPDATE request_engine.representations "
        "SET status='revoked', revision=revision+1 WHERE id=%s",
        (ids[0],),
    )
    admin_conn.execute(
        "UPDATE request_engine.representations SET valid_from=clock_timestamp()+interval '1 day', "
        "revision=revision+1 WHERE id=%s",
        (ids[1],),
    )
    admin_conn.execute(
        "UPDATE request_engine.representations SET valid_from=clock_timestamp()-interval '2 days', "
        "valid_until=clock_timestamp()-interval '1 day', revision=revision+1 WHERE id=%s",
        (ids[2],),
    )
    snapshot = await reader.read_self(actor, SelfAuthorityQuery())
    assert [item.representation_id for item in snapshot.representations] == [ids[3]]
    admin_conn.execute("UPDATE request_engine.parties SET active=false WHERE id=%s", (party,))
    assert (await reader.read_self(actor, SelfAuthorityQuery())).representations == ()
    admin_conn.execute(
        "UPDATE request_engine.principals SET active=false WHERE id=%s", (controller,)
    )
    with pytest.raises(AuthorityInspectionDenied):
        await reader.read_self(actor, SelfAuthorityQuery())


@pytest.mark.asyncio
@pytest.mark.parametrize("principal_kind", ["human", "integration", "agent"])
async def test_self_authority_never_exposes_another_same_tenant_principals_relationships(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
    principal_kind: str,
) -> None:
    org, party, controller, _ = provision_root(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller,
        organization_id=org,
        capability_key="authority.read_self",
        authority_plane="operational",
    )
    other_principal, other_party = _second_tenant_principal(
        admin_conn,
        organization_id=org,
        scope_key="operations.manage_supply",
        principal_kind=principal_kind,
    )
    reader = PostgresSelfAuthorityReader(command_session_factory)
    actor = ActorContext(org, controller, frozenset({"authority.read_self"}))

    before = _tenant_state_fingerprint(admin_conn, organization_id=org, principal_id=controller)
    snapshot = await reader.read_self(actor, SelfAuthorityQuery())
    assert snapshot.principal_id == controller
    assert {item.represented_party_id for item in snapshot.representations} == {party}
    assert other_party not in {item.represented_party_id for item in snapshot.representations}
    assert (
        _tenant_state_fingerprint(admin_conn, organization_id=org, principal_id=controller)
        == before
    )

    # The second same-tenant Principal sees only its own relationship after an
    # explicit standing grant; a forged in-memory capability alone is denied.
    other_actor = ActorContext(org, other_principal, frozenset({"authority.read_self"}))
    with pytest.raises(AuthorityInspectionDenied):
        await reader.read_self(other_actor, SelfAuthorityQuery())
    grant_delegable(
        admin_conn,
        principal_id=other_principal,
        organization_id=org,
        capability_key="authority.read_self",
        authority_plane="operational",
    )
    other_snapshot = await reader.read_self(other_actor, SelfAuthorityQuery())
    assert other_snapshot.principal_id == other_principal
    assert [item.represented_party_id for item in other_snapshot.representations] == [other_party]
    assert party not in {item.represented_party_id for item in other_snapshot.representations}


@pytest.mark.asyncio
async def test_self_authority_standing_grant_is_not_satisfied_by_temporary_delegation(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _party, controller, _ = provision_root(admin_conn)
    delegate, delegate_party = _second_tenant_principal(
        admin_conn,
        organization_id=org,
        scope_key="operations.manage_supply",
        principal_kind="agent",
    )
    admin_conn.execute(
        "INSERT INTO request_engine.delegations "
        "(id, organization_id, delegator_principal_id, delegate_principal_id, purpose, "
        "allowed_capabilities, not_before, expires_at, provenance_reference) "
        "VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp() - interval '1 minute', "
        "clock_timestamp() + interval '1 day', %s)",
        (
            uuid4(),
            org,
            controller,
            delegate,
            "temporary self inspection",
            ["authority.read_self"],
            "self-authority-delegation-proof",
        ),
    )
    assert admin_conn.execute(
        "SELECT status FROM request_engine.delegations WHERE delegate_principal_id=%s",
        (delegate,),
    ).fetchone() == ("active",)

    reader = PostgresSelfAuthorityReader(command_session_factory)
    actor = ActorContext(org, delegate, frozenset({"authority.read_self"}))
    with pytest.raises(AuthorityInspectionDenied):
        await reader.read_self(actor, SelfAuthorityQuery())

    grant_delegable(
        admin_conn,
        principal_id=delegate,
        organization_id=org,
        capability_key="authority.read_self",
        authority_plane="operational",
    )
    snapshot = await reader.read_self(actor, SelfAuthorityQuery())
    assert snapshot.principal_id == delegate
    assert [item.represented_party_id for item in snapshot.representations] == [delegate_party]
