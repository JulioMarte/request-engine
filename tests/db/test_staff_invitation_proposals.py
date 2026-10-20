"""INV-STAFF-INVITATION-PROPOSAL-001: agents propose staff invitations, HUMANs decide.

Real PostgreSQL 18 through a release-shaped application LOGIN (RLS, triggers,
SECURITY DEFINER gates). Only the external secret store is doubled; the
Communications delivery recorder, idempotency, audit and locks are real.
"""

import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from agent_governance_support import (
    grant_delegable,
    provision_agent,
    reset_actor,
    set_tenant_actor,
    transition_agent,
    workload_authority,
)
from psycopg import Connection, Error
from test_staff_email_invitations import InvitationSecretStore
from test_staff_membership_lifecycle import provision_staff_root

from request_engine.modules.communications.adapters.db.staff_invitation_delivery import (
    PostgresStaffInvitationDeliveryRecorder,
)
from request_engine.modules.tenancy.adapters.db.staff_invitation_commands import (
    PostgresStaffInvitationCommands,
)
from request_engine.modules.tenancy.adapters.db.staff_invitation_proposal_commands import (
    PostgresStaffInvitationProposalCommands,
)
from request_engine.modules.tenancy.application.commands.staff_invitation_proposals import (
    ApproveStaffInvitationProposalCommand,
    ProposeStaffInvitationCommand,
    RejectStaffInvitationProposalCommand,
    StaffInvitationProposalStatus,
)
from request_engine.modules.tenancy.application.errors import (
    StaffInvitationProposalDuplicate,
    StaffInvitationProposalNotPending,
    StaffMembershipForbidden,
    StaffMembershipNotFound,
    StaffMembershipRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.adversarial,
    pytest.mark.invariant,
]
PgConnection = Connection[Any]
_HUMAN_CAPABILITIES = frozenset({"staff.invite", "staff.read"})


class _Tenant:
    def __init__(self, conn: PgConnection, *, agent_name: str = "Chief of Staff") -> None:
        org, _party, controller, _binding, _provisioner = provision_staff_root(conn)
        # Valid prerequisite: the controller may delegate the operational proposal
        # capability (policy v8 grants exactly this to new organizations).
        grant_delegable(
            conn,
            principal_id=controller,
            organization_id=org,
            capability_key="staff.propose_invitation",
            authority_plane="operational",
        )
        agent = _active_agent(conn, org, controller, display_name=agent_name)
        self.organization_id = org
        self.controller_id = controller
        self.agent_id = agent
        self.controller = ActorContext(org, controller, _HUMAN_CAPABILITIES)
        self.agent = ActorContext(
            org,
            agent,
            frozenset({"staff.propose_invitation"}),
            principal_kind=PrincipalKind.AGENT,
        )


def _active_agent(conn: PgConnection, org: UUID, controller: UUID, *, display_name: str) -> UUID:
    agent, *_ = provision_agent(
        conn,
        organization_id=org,
        controller_id=controller,
        workload_authority_id=workload_authority(conn),
        display_name=display_name,
    )
    transition_agent(
        conn,
        organization_id=org,
        controller_id=controller,
        agent_principal_id=agent,
        expected_revision=1,
        target_status="active",
    )
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (agent,)
    ).fetchone()
    assert row is not None
    set_tenant_actor(conn, organization_id=org, principal_id=controller)
    try:
        conn.execute(
            "SELECT request_engine.replace_agent_authority(%s,%s,%s,%s)",
            (agent, row[0], ["staff.propose_invitation"], "chief-of-staff-authority"),
        )
    finally:
        reset_actor(conn)
    return agent


def _commands(
    sessions: SessionFactory, store: InvitationSecretStore
) -> PostgresStaffInvitationProposalCommands:
    invitations = PostgresStaffInvitationCommands(
        sessions,
        secret_delivery=store,
        delivery_recorder=PostgresStaffInvitationDeliveryRecorder(),
    )
    return PostgresStaffInvitationProposalCommands(sessions, invitations=invitations)


def _propose(email: str, key: str, **extra: str) -> ProposeStaffInvitationCommand:
    return ProposeStaffInvitationCommand(
        email=email, provenance_reference="owner asked by voice", idempotency_key=key, **extra
    )


def _counts(conn: PgConnection, org: UUID) -> tuple[int, int, int]:
    row = conn.execute(
        """SELECT
            (SELECT count(*) FROM request_engine.staff_invitation_proposals
                WHERE organization_id=%s),
            (SELECT count(*) FROM request_engine.staff_invitations WHERE organization_id=%s),
            (SELECT count(*) FROM request_engine.staff_invitation_deliveries
                WHERE organization_id=%s)""",
        (org, org, org),
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


@pytest.mark.asyncio
async def test_agent_proposal_is_inert_replayable_and_unique_while_pending(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    tenant = _Tenant(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    grants_before = admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchone()

    proposal = await commands.propose(
        tenant.agent,
        _propose(" New.Hire@Example.Test ", "voice-1", display_name="Ana", note="front desk"),
    )

    assert proposal.status == StaffInvitationProposalStatus.PENDING
    assert proposal.revision == 1 and proposal.email == "new.hire@example.test"
    assert proposal.proposed_by_principal_id == tenant.agent_id
    assert proposal.proposed_by_principal_kind == "agent"
    assert proposal.proposed_by_display_name == "Chief of Staff"
    assert (proposal.decided_at, proposal.invitation_id) == (None, None)
    # Inert: no invitation, no delivery intent, no staged secret, no grant change.
    assert _counts(admin_conn, tenant.organization_id) == (1, 0, 0)
    assert store.stage_count == 0
    assert (
        admin_conn.execute(
            "SELECT count(*) FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s",
            (tenant.organization_id,),
        ).fetchone()
        == grants_before
    )
    assert admin_conn.execute(
        "SELECT actor_principal_id,aggregate_id FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name='staff.invitation_proposal.create'",
        (tenant.organization_id,),
    ).fetchall() == [(tenant.agent_id, proposal.proposal_id)]

    replay = await commands.propose(
        tenant.agent,
        _propose("new.hire@example.test", "voice-1", display_name="Ana", note="front desk"),
    )
    assert replay == proposal
    with pytest.raises(IdempotencyConflict):
        await commands.propose(tenant.agent, _propose("other@example.test", "voice-1"))
    with pytest.raises(StaffInvitationProposalDuplicate):
        await commands.propose(tenant.agent, _propose("NEW.HIRE@example.test", "voice-2"))
    assert _counts(admin_conn, tenant.organization_id) == (1, 0, 0)

    # The proposer reads its own proposal; another proposer cannot address it.
    assert await commands.get(tenant.agent, proposal.proposal_id) == proposal
    other_agent = _active_agent(
        admin_conn, tenant.organization_id, tenant.controller_id, display_name="Other agent"
    )
    other = ActorContext(
        tenant.organization_id,
        other_agent,
        frozenset({"staff.propose_invitation"}),
        principal_kind=PrincipalKind.AGENT,
    )
    with pytest.raises(StaffMembershipNotFound):
        await commands.get(other, proposal.proposal_id)
    # Agents never get the administrative inbox, even with a forged read claim.
    with pytest.raises(StaffMembershipForbidden):
        await commands.list(
            ActorContext(
                tenant.organization_id,
                tenant.agent_id,
                frozenset({"staff.read", "staff.propose_invitation"}),
                principal_kind=PrincipalKind.AGENT,
            ),
            status=None,
            after=None,
            limit=10,
        )

    inbox = await commands.list(
        tenant.controller, status=StaffInvitationProposalStatus.PENDING, after=None, limit=10
    )
    assert [item.proposal_id for item in inbox] == [proposal.proposal_id]
    assert inbox[0].proposed_by_display_name == "Chief of Staff"
    assert (
        await commands.list(
            tenant.controller,
            status=StaffInvitationProposalStatus.APPROVED,
            after=None,
            limit=10,
        )
        == ()
    )


@pytest.mark.asyncio
async def test_proposals_are_tenant_isolated(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    tenant_a = _Tenant(admin_conn)
    tenant_b = _Tenant(admin_conn)
    commands = _commands(command_session_factory, InvitationSecretStore())
    proposal = await commands.propose(tenant_a.agent, _propose("a-only@example.test", "a-1"))

    assert await commands.list(tenant_b.controller, status=None, after=None, limit=10) == ()
    with pytest.raises(StaffMembershipNotFound):
        await commands.get(tenant_b.controller, proposal.proposal_id)
    with pytest.raises(StaffMembershipNotFound):
        await commands.reject(
            tenant_b.controller,
            RejectStaffInvitationProposalCommand(
                proposal.proposal_id, 1, "foreign tenant", "b-reject"
            ),
        )
    with app_role_conn.transaction():
        app_role_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,true),"
            "set_config('request_engine.authenticated_principal_id',%s,true)",
            (str(tenant_b.organization_id), str(tenant_b.controller_id)),
        )
        assert app_role_conn.execute(
            "SELECT count(*) FROM request_engine.staff_invitation_proposals"
        ).fetchone() == (0,)
        updated = app_role_conn.execute(
            "UPDATE request_engine.staff_invitation_proposals SET note='x' WHERE id=%s",
            (proposal.proposal_id,),
        ).rowcount
        assert updated == 0
    with pytest.raises(Error) as foreign_insert, app_role_conn.transaction():
        app_role_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,true),"
            "set_config('request_engine.authenticated_principal_id',%s,true)",
            (str(tenant_b.organization_id), str(tenant_b.agent_id)),
        )
        app_role_conn.execute(
            "INSERT INTO request_engine.staff_invitation_proposals"
            "(id,organization_id,email,proposed_by_principal_id,provenance_reference) "
            "VALUES(%s,%s,'x@example.test',%s,'cross tenant')",
            (uuid4(), tenant_a.organization_id, tenant_a.agent_id),
        )
    assert foreign_insert.value.sqlstate == "42501"
    assert admin_conn.execute(
        "SELECT status,revision,note FROM request_engine.staff_invitation_proposals WHERE id=%s",
        (proposal.proposal_id,),
    ).fetchone() == ("pending", 1, None)


@pytest.mark.asyncio
async def test_approval_creates_exactly_one_invitation_through_existing_path(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    tenant = _Tenant(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    proposal = await commands.propose(tenant.agent, _propose("hire@example.test", "p-1"))
    approve = ApproveStaffInvitationProposalCommand(
        proposal.proposal_id, 1, "owner approved in console", "approve-1", expires_in_hours=48
    )

    approved = await commands.approve(tenant.controller, approve)

    assert approved.status == StaffInvitationProposalStatus.APPROVED
    assert approved.revision == 2 and approved.decided_by_principal_id == tenant.controller_id
    assert approved.invitation_id is not None and approved.decided_at is not None
    invitation = admin_conn.execute(
        "SELECT email,status,generation,invited_by_principal_id,token_digest,"
        "expires_at > created_at + interval '47 hours' "
        "FROM request_engine.staff_invitations WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchall()
    assert len(invitation) == 1
    email, status, generation, inviter, digest, honours_expiry = invitation[0]
    assert (email, status, generation, inviter, honours_expiry) == (
        "hire@example.test",
        "pending",
        1,
        tenant.controller_id,
        True,
    )
    # Same delivery semantics as staff_invitation_create: one staged proof whose
    # digest is persisted, and one closed-purpose delivery intent for generation 1.
    assert store.stage_count == 1
    assert list(store.secrets) == [(approved.invitation_id, 1)]
    assert admin_conn.execute(
        "SELECT invitation_id,generation,destination_address,secret_digest,status "
        "FROM request_engine.staff_invitation_deliveries WHERE organization_id=%s",
        (tenant.organization_id,),
    ).fetchall() == [(approved.invitation_id, 1, "hire@example.test", digest, "pending")]
    assert admin_conn.execute(
        "SELECT command_name,actor_principal_id FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name IN "
        "('staff.invitation.create','staff.invitation_proposal.approve') ORDER BY command_name",
        (tenant.organization_id,),
    ).fetchall() == [
        ("staff.invitation.create", tenant.controller_id),
        ("staff.invitation_proposal.approve", tenant.controller_id),
    ]

    # Replay neither re-stages nor duplicates; a new decision on the same proposal fails.
    assert await commands.approve(tenant.controller, approve) == approved
    assert store.stage_count == 1
    with pytest.raises(StaffInvitationProposalNotPending):
        await commands.approve(
            tenant.controller,
            ApproveStaffInvitationProposalCommand(proposal.proposal_id, 2, "again", "approve-2"),
        )
    with pytest.raises(StaffInvitationProposalNotPending):
        await commands.reject(
            tenant.controller,
            RejectStaffInvitationProposalCommand(proposal.proposal_id, 2, "late", "reject-late"),
        )
    assert _counts(admin_conn, tenant.organization_id) == (1, 1, 1)
    # The pending invitation now blocks a new proposal for the same email.
    with pytest.raises(StaffInvitationProposalDuplicate):
        await commands.propose(tenant.agent, _propose("hire@example.test", "p-2"))


@pytest.mark.asyncio
async def test_stale_revision_and_rejection_create_no_invitation(
    admin_conn: PgConnection, command_session_factory: SessionFactory
) -> None:
    tenant = _Tenant(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    proposal = await commands.propose(tenant.agent, _propose("maybe@example.test", "p-1"))

    with pytest.raises(StaffMembershipRevisionConflict):
        await commands.approve(
            tenant.controller,
            ApproveStaffInvitationProposalCommand(proposal.proposal_id, 2, "stale", "stale-1"),
        )
    assert store.stage_count == 0
    assert _counts(admin_conn, tenant.organization_id) == (1, 0, 0)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.idempotency_records WHERE organization_id=%s "
        "AND capability='staff.invitation_proposal.approve'",
        (tenant.organization_id,),
    ).fetchone() == (0,)

    rejected = await commands.reject(
        tenant.controller,
        RejectStaffInvitationProposalCommand(
            proposal.proposal_id, 1, "owner declined", "reject-1", reason="  Not hiring now "
        ),
    )
    assert rejected.status == StaffInvitationProposalStatus.REJECTED
    assert (rejected.revision, rejected.rejection_reason) == (2, "Not hiring now")
    assert rejected.decided_by_principal_id == tenant.controller_id
    assert rejected.invitation_id is None
    with pytest.raises(StaffInvitationProposalNotPending):
        await commands.approve(
            tenant.controller,
            ApproveStaffInvitationProposalCommand(proposal.proposal_id, 2, "after", "after-1"),
        )
    assert store.stage_count == 0
    assert _counts(admin_conn, tenant.organization_id) == (1, 0, 0)
    # A decided proposal no longer blocks a fresh proposal for the same email.
    again = await commands.propose(tenant.agent, _propose("maybe@example.test", "p-2"))
    assert again.status == StaffInvitationProposalStatus.PENDING


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_approve_and_reject_have_exactly_one_winner(
    admin_conn: PgConnection, command_session_factory: SessionFactory, pg_conninfo: str
) -> None:
    tenant = _Tenant(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    proposal = await commands.propose(tenant.agent, _propose("race@example.test", "p-1"))

    blocker: PgConnection = psycopg.connect(pg_conninfo)
    try:
        blocker.execute(
            "SELECT id FROM request_engine.staff_invitation_proposals WHERE id=%s FOR UPDATE",
            (proposal.proposal_id,),
        )
        tasks = [
            asyncio.create_task(
                commands.approve(
                    tenant.controller,
                    ApproveStaffInvitationProposalCommand(
                        proposal.proposal_id, 1, "approve race", "race-approve"
                    ),
                )
            ),
            asyncio.create_task(
                commands.reject(
                    tenant.controller,
                    RejectStaffInvitationProposalCommand(
                        proposal.proposal_id, 1, "reject race", "race-reject"
                    ),
                )
            ),
        ]
        deadline = asyncio.get_running_loop().time() + 15
        while True:
            waiting = admin_conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND usename LIKE 'request_engine_app_f3_%%' AND wait_event_type='Lock'"
            ).fetchone()
            if waiting == (2,):
                break
            assert not any(task.done() for task in tasks), [
                task.exception() for task in tasks if task.done()
            ]
            assert asyncio.get_running_loop().time() < deadline, "both deciders must contend"
            await asyncio.sleep(0.01)
    finally:
        blocker.rollback()
        blocker.close()
    results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=15)

    winners = [result for result in results if not isinstance(result, BaseException)]
    losers = [result for result in results if isinstance(result, BaseException)]
    assert len(winners) == 1 and len(losers) == 1, results
    assert isinstance(
        losers[0], StaffMembershipRevisionConflict | StaffInvitationProposalNotPending
    )
    final = admin_conn.execute(
        "SELECT status,revision,invitation_id FROM request_engine.staff_invitation_proposals "
        "WHERE id=%s",
        (proposal.proposal_id,),
    ).fetchone()
    assert final is not None and final[0] == winners[0].status and final[1] == 2
    invitations = _counts(admin_conn, tenant.organization_id)[1]
    assert invitations == (1 if final[0] == "approved" else 0)
    assert (final[2] is not None) == (final[0] == "approved")
    assert admin_conn.execute(
        "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid "
        "WHERE a.usename LIKE 'request_engine_app_f3_%%' AND NOT l.granted"
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_agent_cannot_approve_in_python_or_postgresql(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
    app_role_conn: PgConnection,
) -> None:
    tenant = _Tenant(admin_conn)
    store = InvitationSecretStore()
    commands = _commands(command_session_factory, store)
    proposal = await commands.propose(tenant.agent, _propose("self-approve@example.test", "p-1"))
    # Even a forged ActorContext claiming staff.invite is rejected for an AGENT.
    forged = ActorContext(
        tenant.organization_id,
        tenant.agent_id,
        frozenset({"staff.invite", "staff.read", "staff.propose_invitation"}),
        principal_kind=PrincipalKind.AGENT,
    )

    # Python denies before opening any database session (independent of the SQL
    # backstop below, which would otherwise also turn this into a 403).
    def no_database() -> Any:
        raise AssertionError("HUMAN-only decision guard must deny before PostgreSQL")

    python_only = _commands(cast(SessionFactory, no_database), store)
    for decided in (python_only, commands):
        with pytest.raises(StaffMembershipForbidden):
            await decided.approve(
                forged,
                ApproveStaffInvitationProposalCommand(proposal.proposal_id, 1, "self", "self-1"),
            )
        with pytest.raises(StaffMembershipForbidden):
            await decided.reject(
                forged,
                RejectStaffInvitationProposalCommand(proposal.proposal_id, 1, "self", "self-2"),
            )

    # PostgreSQL backstop under the real application LOGIN with the agent's
    # trusted context: the manager gate and the decision guard both refuse.
    def as_agent() -> None:
        app_role_conn.execute(
            "SELECT set_config('request_engine.organization_id',%s,true),"
            "set_config('request_engine.authenticated_principal_id',%s,true)",
            (str(tenant.organization_id), str(tenant.agent_id)),
        )

    with pytest.raises(Error) as gate, app_role_conn.transaction():
        as_agent()
        app_role_conn.execute("SELECT request_cmd.lock_staff_invitation_admin(NULL)")
    assert gate.value.sqlstate == "42501"
    with pytest.raises(Error) as decision, app_role_conn.transaction():
        as_agent()
        app_role_conn.execute(
            "UPDATE request_engine.staff_invitation_proposals SET status='rejected',"
            "revision=2,decided_at=clock_timestamp(),decided_by_principal_id=%s,"
            "decision_provenance_reference='self decision' WHERE id=%s",
            (tenant.agent_id, proposal.proposal_id),
        )
    assert decision.value.sqlstate == "42501"
    with pytest.raises(Error) as invite, app_role_conn.transaction():
        as_agent()
        app_role_conn.execute(
            "INSERT INTO request_engine.staff_invitations"
            "(id,organization_id,email,invited_by_principal_id,provenance_reference,"
            "token_digest,expires_at) VALUES(%s,%s,'self-approve@example.test',%s,'self',"
            "repeat('a',64),clock_timestamp()+interval '1 day')",
            (uuid4(), tenant.organization_id, tenant.agent_id),
        )
    assert invite.value.sqlstate == "42501"
    # A proposer cannot attribute a proposal to someone else either.
    with pytest.raises(Error) as spoof, app_role_conn.transaction():
        as_agent()
        app_role_conn.execute(
            "INSERT INTO request_engine.staff_invitation_proposals"
            "(id,organization_id,email,proposed_by_principal_id,provenance_reference) "
            "VALUES(%s,%s,'spoof@example.test',%s,'spoof')",
            (uuid4(), tenant.organization_id, tenant.controller_id),
        )
    assert spoof.value.sqlstate == "42501"
    # Withdrawing the agent's proposal grant closes the SQL insert path as well.
    set_tenant_actor(
        admin_conn, organization_id=tenant.organization_id, principal_id=tenant.controller_id
    )
    try:
        revision = admin_conn.execute(
            "SELECT authority_revision FROM request_engine.principals WHERE id=%s",
            (tenant.agent_id,),
        ).fetchone()
        assert revision is not None
        admin_conn.execute(
            "SELECT request_engine.replace_agent_authority(%s,%s,%s,%s)",
            (tenant.agent_id, revision[0], [], "withdraw proposal authority"),
        )
    finally:
        reset_actor(admin_conn)
    with pytest.raises(Error) as withdrawn, app_role_conn.transaction():
        as_agent()
        app_role_conn.execute(
            "INSERT INTO request_engine.staff_invitation_proposals"
            "(id,organization_id,email,proposed_by_principal_id,provenance_reference) "
            "VALUES(%s,%s,'late@example.test',%s,'after withdrawal')",
            (uuid4(), tenant.organization_id, tenant.agent_id),
        )
    assert withdrawn.value.sqlstate == "42501"
    assert store.stage_count == 0
    assert _counts(admin_conn, tenant.organization_id) == (1, 0, 0)
    assert admin_conn.execute(
        "SELECT status,revision FROM request_engine.staff_invitation_proposals WHERE id=%s",
        (proposal.proposal_id,),
    ).fetchone() == ("pending", 1)
