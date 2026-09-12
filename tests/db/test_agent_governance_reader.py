"""Current agent inspection authority and tenant opacity over the app-role boundary."""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    provision_agent,
    provision_root,
    workload_authority,
)
from psycopg import Connection

from request_engine.modules.tenancy.adapters.db.agent_governance_reader import (
    PostgresAgentGovernanceReader,
)
from request_engine.modules.tenancy.application.errors import (
    AgentGovernanceForbidden,
    AgentGovernanceNotFound,
)
from request_engine.modules.tenancy.application.queries.agent_governance import ListAgentsQuery
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]


@pytest.mark.asyncio
async def test_agent_reader_is_tenant_scoped_and_rechecks_stale_authority(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    org, _, controller, _ = provision_root(admin_conn)
    other_org, _, other_controller, _ = provision_root(admin_conn)
    workload = workload_authority(admin_conn)
    ids = [
        provision_agent(
            admin_conn,
            organization_id=org,
            controller_id=controller,
            workload_authority_id=workload,
        )[0]
        for _ in range(2)
    ]
    foreign_id = provision_agent(
        admin_conn,
        organization_id=other_org,
        controller_id=other_controller,
        workload_authority_id=workload,
    )[0]
    actor = ActorContext(org, controller, frozenset({"agent.read"}))
    reader = PostgresAgentGovernanceReader(command_session_factory)
    # An in-memory claim is insufficient; there is no standing read grant yet.
    with pytest.raises(AgentGovernanceForbidden):
        await reader.list_agents(actor, ListAgentsQuery())
    grant_delegable(
        admin_conn,
        principal_id=controller,
        organization_id=org,
        capability_key="agent.read",
        authority_plane="tenant_control",
    )
    before = admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants"
    ).fetchone()
    first = await reader.list_agents(actor, ListAgentsQuery(limit=1))
    assert [row.principal_id for row in first] == sorted(ids)[:1]
    second = await reader.list_agents(actor, ListAgentsQuery(after=first[0].principal_id, limit=1))
    assert [row.principal_id for row in second] == sorted(ids)[1:]
    assert await reader.list_agents(actor, ListAgentsQuery(after=second[0].principal_id)) == ()
    for target in (foreign_id, uuid4(), controller):
        with pytest.raises(AgentGovernanceNotFound, match="not visible in this tenant"):
            await reader.read_agent(actor, target)
    actual = await reader.read_agent(actor, ids[0])
    assert actual.sponsor_principal_id == controller
    assert actual.status.value == "pending" and actual.principal_active
    assert actual.standing_capabilities == ()
    assert admin_conn.execute(
        "SELECT a.revision, p.authority_revision FROM request_engine.agent_profiles a "
        "JOIN request_engine.principals p ON p.id=a.principal_id WHERE p.id=%s",
        (ids[0],),
    ).fetchone() == (actual.profile_revision, actual.authority_revision)
    for kind in (PrincipalKind.AGENT, PrincipalKind.INTEGRATION, PrincipalKind.SYSTEM):
        with pytest.raises(AgentGovernanceForbidden):
            await reader.list_agents(replace(actor, principal_kind=kind), ListAgentsQuery())
    with pytest.raises(AgentGovernanceForbidden):
        await reader.list_agents(replace(actor, capabilities=frozenset()), ListAgentsQuery())
    assert (
        admin_conn.execute(
            "SELECT count(*) FROM request_engine.principal_authority_grants"
        ).fetchone()
        == before
    )
    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='agent.read' AND status='active'",
        (controller, controller),
    )
    # Reuse the exact previously authorized context, not a refreshed authentication result.
    with pytest.raises(AgentGovernanceForbidden):
        await reader.list_agents(actor, ListAgentsQuery())
    with pytest.raises(AgentGovernanceForbidden):
        await reader.read_agent(actor, ids[0])
