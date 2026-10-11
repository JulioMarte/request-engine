"""Owner transaction: preserve identity, revoke old bearer, never replay secrets."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import pytest
from agent_governance_support import (
    grant_delegable,
    provision_agent,
    provision_root,
    transition_agent,
    workload_authority,
)
from psycopg import Connection

from request_engine.modules.tenancy.adapters.db.agent_governance_commands import (
    PostgresAgentGovernanceCommands,
)
from request_engine.modules.tenancy.adapters.db.agent_governance_reader import (
    PostgresAgentGovernanceReader,
)
from request_engine.modules.tenancy.application.commands.agent_governance import (
    ReplaceAgentAuthorityCommand,
    RotateAgentCredentialCommand,
)
from request_engine.modules.tenancy.application.errors import (
    AgentGovernanceConflict,
    AgentGovernanceForbidden,
    AgentGovernanceNotFound,
    AgentGovernanceRevisionConflict,
)
from request_engine.platform.db.workload_credential_reader import PostgresWorkloadCredentialReader
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.workload_auth import (
    WorkloadCredentialAuthenticator,
    WorkloadCredentialEvidence,
    WorkloadCredentialInvalid,
)

pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]


@pytest.mark.asyncio
async def test_agent_rotation_preserves_identity_reconciles_and_rechecks_replay(
    admin_conn: Connection[Any],
    command_session_factory: Any,
) -> None:
    org, _, controller, _ = provision_root(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller,
        organization_id=org,
        capability_key="agent.read",
        authority_plane="tenant_control",
    )
    agent, binding, identity, old_credential, old_token = provision_agent(
        admin_conn,
        organization_id=org,
        controller_id=controller,
        workload_authority_id=workload_authority(admin_conn),
    )
    actor = ActorContext(
        organization_id=org,
        principal_id=controller,
        principal_kind=PrincipalKind.HUMAN,
        capabilities=frozenset({"agent.manage_authority", "agent.read"}),
    )
    commands = PostgresAgentGovernanceCommands(command_session_factory)
    authenticator = WorkloadCredentialAuthenticator(
        reader=PostgresWorkloadCredentialReader(command_session_factory)
    )
    before = admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (agent,)
    ).fetchone()
    assert before is not None
    command = RotateAgentCredentialCommand(
        agent,
        before[0],
        datetime.now(UTC) + timedelta(hours=1),
        "incident:rotation-proof",
        "rotation-proof",
    )
    first = await commands.rotate_agent_credential(actor, command)
    assert first.workload_token is not None
    assert first.credential_id != old_credential
    assert first.authority_revision == before[0] + 1
    assert first.workload_token not in repr(first)
    repeated = await commands.rotate_agent_credential(actor, command)
    assert repeated.credential_id == first.credential_id
    assert repeated.authority_revision == first.authority_revision
    assert repeated.workload_token is None
    with pytest.raises(WorkloadCredentialInvalid):
        await authenticator.authenticate(WorkloadCredentialEvidence(old_token))
    subject = await authenticator.authenticate(WorkloadCredentialEvidence(first.workload_token))
    assert subject.subject_id == str(identity)
    current = await PostgresAgentGovernanceReader(command_session_factory).read_agent(actor, agent)
    assert current.authority_revision == first.authority_revision
    assert tuple(c.credential_id for c in current.credentials) == (first.credential_id,)
    assert current.profile_revision == 1 and current.status.value == "pending"
    assert current.standing_capabilities == ()
    assert admin_conn.execute(
        "SELECT principal_id,subject_id,status FROM request_engine.identity_bindings WHERE id=%s",
        (binding,),
    ).fetchone() == (agent, str(identity), "pending")
    assert admin_conn.execute(
        "SELECT status,revision FROM request_engine.workload_credentials WHERE id=%s",
        (old_credential,),
    ).fetchone() == ("revoked", 2)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.workload_credentials WHERE workload_identity_id=%s",
        (identity,),
    ).fetchone() == (2,)

    with pytest.raises(AgentGovernanceRevisionConflict):
        await commands.rotate_agent_credential(
            actor,
            RotateAgentCredentialCommand(
                agent, before[0], command.credential_expires_at, "stale-attempt", "stale-attempt"
            ),
        )
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.workload_credentials WHERE workload_identity_id=%s",
        (identity,),
    ).fetchone() == (2,)
    admin_conn.execute(
        """
        UPDATE request_engine.principal_authority_grants SET status='revoked',
            revoked_at=clock_timestamp(), revoked_by_principal_id=%s, revision=revision+1
         WHERE organization_id=%s AND principal_id=%s AND capability_key='agent.manage_authority'
           AND status='active'
    """,
        (controller, org, controller),
    )
    with pytest.raises(AgentGovernanceForbidden):
        await commands.rotate_agent_credential(actor, command)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.workload_credentials WHERE workload_identity_id=%s",
        (identity,),
    ).fetchone() == (2,)


@pytest.mark.asyncio
@pytest.mark.adversarial
@pytest.mark.parametrize("denial", ["foreign", "revoked", "ceiling", "nonhuman"])
async def test_rotation_denial_has_no_credential_receipt_or_audit_effect(
    admin_conn: Connection[Any], command_session_factory: Any, denial: str
) -> None:
    org, _, controller, _ = provision_root(admin_conn)
    agent, _, identity, _, _ = provision_agent(
        admin_conn,
        organization_id=org,
        controller_id=controller,
        workload_authority_id=workload_authority(admin_conn),
    )
    actor = ActorContext(
        organization_id=org,
        principal_id=controller,
        principal_kind=PrincipalKind.HUMAN,
        capabilities=frozenset({"agent.manage_authority"}),
    )
    commands = PostgresAgentGovernanceCommands(command_session_factory)
    expected_error: type[Exception] = AgentGovernanceForbidden
    if denial == "foreign":
        other_org, _, other_controller, _ = provision_root(admin_conn)
        actor = replace(actor, organization_id=other_org, principal_id=other_controller)
        expected_error = AgentGovernanceNotFound
    elif denial == "revoked":
        transition_agent(
            admin_conn,
            organization_id=org,
            controller_id=controller,
            agent_principal_id=agent,
            expected_revision=1,
            target_status="revoked",
        )
        expected_error = AgentGovernanceConflict
    elif denial == "ceiling":
        grant_delegable(
            admin_conn,
            organization_id=org,
            principal_id=controller,
            capability_key="parties.lookup",
            authority_plane="operational",
        )
        row = admin_conn.execute(
            "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (agent,)
        ).fetchone()
        assert row is not None
        await commands.replace_agent_authority(
            actor,
            ReplaceAgentAuthorityCommand(
                agent, row[0], ("parties.lookup",), "proof:grant", "proof:grant"
            ),
        )
        admin_conn.execute(
            "UPDATE request_engine.principal_authority_grants SET status='revoked', "
            "revoked_at=clock_timestamp(),revoked_by_principal_id=%s,revision=revision+1 "
            "WHERE principal_id=%s AND capability_key='parties.lookup' "
            "AND status='active'",
            (controller, controller),
        )
        admin_conn.execute(
            "INSERT INTO request_engine.principal_authority_grants "
            "(organization_id,principal_id,principal_plane,authority_plane,capability_key, "
            "delegable,granted_by_principal_id,provenance_kind,provenance_reference) "
            "VALUES (%s,%s,'tenant','operational','parties.lookup',false,%s, "
            "'authority_management','proof:nondelegable')",
            (org, controller, controller),
        )
    else:
        # Spoofing HUMAN management capabilities in an AGENT context cannot authorize it.
        actor = replace(actor, principal_id=agent, principal_kind=PrincipalKind.AGENT)
    before = _rotation_state(admin_conn)
    row = admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (agent,)
    ).fetchone()
    assert row is not None
    with pytest.raises(expected_error):
        await commands.rotate_agent_credential(
            actor,
            RotateAgentCredentialCommand(
                agent,
                row[0],
                datetime.now(UTC) + timedelta(hours=1),
                "proof:denied",
                "proof:denied",
            ),
        )
    assert _rotation_state(admin_conn) == before
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.workload_credentials WHERE workload_identity_id=%s",
        (identity,),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.concurrency
@pytest.mark.parametrize("same_key", [True, False])
async def test_concurrent_rotation_has_one_durable_effect(
    admin_conn: Connection[Any],
    command_session_factory: Any,
    app_role_conn_factory: Callable[[], Connection[Any]],
    same_key: bool,
) -> None:
    org, _, controller, _ = provision_root(admin_conn)
    agent, _, identity, old_credential, _ = provision_agent(
        admin_conn,
        organization_id=org,
        controller_id=controller,
        workload_authority_id=workload_authority(admin_conn),
    )
    actor = ActorContext(
        organization_id=org,
        principal_id=controller,
        principal_kind=PrincipalKind.HUMAN,
        capabilities=frozenset({"agent.manage_authority"}),
    )
    row = admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (agent,)
    ).fetchone()
    assert row is not None
    command = RotateAgentCredentialCommand(
        agent, row[0], datetime.now(UTC) + timedelta(hours=1), "proof:race", "proof:race"
    )
    contender = command if same_key else replace(command, idempotency_key="proof:race-other")
    commands = PostgresAgentGovernanceCommands(command_session_factory)
    before = _rotation_state(admin_conn)
    with app_role_conn_factory() as holder:
        holder.execute(
            "SELECT set_config('request_engine.organization_id',%s,true), "
            "set_config('request_engine.authenticated_principal_id',%s,true)",
            (str(org), str(controller)),
        )
        holder.execute("SET LOCAL statement_timeout='12s'")
        holder.execute("SELECT request_cmd.lock_agent_credential_manager(%s)", (agent,))
        tasks = [
            asyncio.create_task(commands.rotate_agent_credential(actor, candidate))
            for candidate in (command, contender)
        ]
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blocked = admin_conn.execute(
                    "WITH RECURSIVE blocked(pid) AS ( "
                    "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                    "AND wait_event_type='Lock' AND %s=ANY(pg_blocking_pids(pid)) "
                    "UNION SELECT a.pid FROM pg_stat_activity a JOIN blocked b "
                    "ON b.pid=ANY(pg_blocking_pids(a.pid)) "
                    "WHERE a.datname=current_database() AND a.wait_event_type='Lock') "
                    "SELECT count(*) FROM blocked",
                    (holder.info.backend_pid,),
                ).fetchone()
                if blocked == (2,):
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("two independent rotation transactions did not contend")
        finally:
            holder.commit()
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=20
            )
    errors = [result for result in outcomes if isinstance(result, BaseException)]
    successes = [result for result in outcomes if not isinstance(result, BaseException)]
    assert len(successes) == (2 if same_key else 1)
    assert len(errors) == (0 if same_key else 1)
    if errors:
        assert isinstance(errors[0], AgentGovernanceRevisionConflict)
    assert len({result.credential_id for result in successes}) == 1
    assert sum(result.workload_token is not None for result in successes) == 1
    assert all(result.authority_revision == row[0] + 1 for result in successes)
    after = _rotation_state(admin_conn)
    assert before is not None and after is not None
    assert after[0:3] == tuple(value + 1 for value in before[0:3])
    assert after[3] == before[3] + 1
    assert admin_conn.execute(
        "SELECT status FROM request_engine.workload_credentials WHERE id=%s", (old_credential,)
    ).fetchone() == ("revoked",)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.workload_credentials "
        "WHERE workload_identity_id=%s AND status='active'",
        (identity,),
    ).fetchone() == (1,)


def _rotation_state(conn: Connection[Any]) -> tuple[Any, ...] | None:
    return conn.execute(
        "SELECT (SELECT count(*) FROM request_engine.workload_credentials), "
        "(SELECT count(*) FROM request_engine.idempotency_records), "
        "(SELECT count(*) FROM request_engine.audit_records), "
        "(SELECT sum(authority_revision) FROM request_engine.principals)"
    ).fetchone()
