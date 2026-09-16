from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agent_governance_support import (
    grant_delegable,
    native_identity,
    principal_revision,
    provision_root,
    workload_authority,
)
from psycopg import Connection, Error
from psycopg.rows import dict_row

from request_engine.modules.tenancy.adapters.db.agent_governance_commands import (
    PostgresAgentGovernanceCommands,
)
from request_engine.modules.tenancy.adapters.db.integration_governance_commands import (
    PostgresIntegrationGovernanceCommands,
)
from request_engine.modules.tenancy.adapters.db.staff_membership_commands import (
    PostgresStaffMembershipCommands,
)
from request_engine.modules.tenancy.application.commands.agent_governance import (
    ProvisionAgentCommand,
    ReplaceAgentAuthorityCommand,
    TransitionAgentProfileCommand,
)
from request_engine.modules.tenancy.application.commands.integration_governance import (
    ProvisionIntegrationCommand,
    ReplaceIntegrationAuthorityCommand,
    RotateIntegrationCredentialCommand,
    TransitionIntegrationStatusCommand,
)
from request_engine.modules.tenancy.application.commands.staff_membership import (
    InviteNativeStaffCommand,
    ReplaceStaffAuthorityCommand,
    StaffMembershipTargetStatus,
    TransitionStaffMembershipCommand,
)
from request_engine.modules.tenancy.domain.agent_governance import (
    AgentOperatingMode,
    AgentProfileStatus,
)
from request_engine.modules.tenancy.domain.integration_governance import IntegrationStatus
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_STAFF_CAPABILITIES = ("staff.invite", "staff.manage_authority", "staff.manage_membership")
_AGENT_CAPABILITIES = ("agent.provision", "agent.manage_authority", "agent.suspend")
_INTEGRATION_CAPABILITIES = (
    "integration.provision",
    "integration.manage_authority",
    "integration.suspend",
)


def _actor(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capabilities: tuple[str, ...],
) -> ActorContext:
    return ActorContext(
        organization_id=organization_id,
        principal_id=principal_id,
        capabilities=frozenset(capabilities),
        principal_kind=PrincipalKind.HUMAN,
        authentication_method="native_password",
        authority_revision=principal_revision(conn, principal_id),
    )


def _audit_rows(
    conn: PgConnection,
    *,
    organization_id: UUID,
    command_name: str,
    aggregate_id: UUID,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT actor_principal_id, aggregate_kind, aggregate_id,
                   idempotency_record_id, details
              FROM request_engine.audit_records
             WHERE organization_id = %s
               AND command_name = %s
               AND aggregate_id = %s
             ORDER BY created_at, id
            """,
            (organization_id, command_name, aggregate_id),
        )
        return list(cursor.fetchall())


def _only_row(
    conn: PgConnection,
    *,
    organization_id: UUID,
    command_name: str,
    aggregate_id: UUID,
) -> dict[str, Any]:
    rows = _audit_rows(
        conn,
        organization_id=organization_id,
        command_name=command_name,
        aggregate_id=aggregate_id,
    )
    assert len(rows) == 1, f"expected exactly one {command_name} audit row, got {len(rows)}"
    return rows[0]


@pytest.mark.asyncio
async def test_staff_identity_commands_commit_exactly_one_audit_row(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    invite_authority_id, invite_identity_id, _credential_id = native_identity(admin_conn)
    actor = _actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
        capabilities=_STAFF_CAPABILITIES,
    )
    commands = PostgresStaffMembershipCommands(command_session_factory)

    invite = InviteNativeStaffCommand(
        identity_authority_id=invite_authority_id,
        native_identity_id=invite_identity_id,
        provenance_reference=f"staff-audit-invite:{uuid4().hex}",
        idempotency_key=f"staff-invite-{uuid4().hex}",
    )
    invited = await commands.invite_native_staff(actor, invite)
    assert await commands.invite_native_staff(actor, invite) == invited

    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="staff.invite",
        aggregate_id=invited.membership_id,
    )
    assert row["actor_principal_id"] == controller_id
    assert row["aggregate_kind"] == "StaffMembership"
    assert row["aggregate_id"] == invited.membership_id
    assert row["idempotency_record_id"] is not None
    assert row["details"] == {
        "action": "invite",
        "reason_code": "staff_invited",
        "subject_kind": "StaffMembership",
        "revision_before": 0,
        "revision_after": 1,
    }
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.staff_memberships WHERE id = %s",
        (invited.membership_id,),
    ).fetchone() == ("invited", 1)

    activated_revision = await commands.transition_staff_membership(
        actor,
        TransitionStaffMembershipCommand(
            membership_id=invited.membership_id,
            expected_revision=1,
            target_status=StaffMembershipTargetStatus.ACTIVE,
            provenance_reference=f"staff-audit-activate:{uuid4().hex}",
            idempotency_key=f"staff-activate-{uuid4().hex}",
        ),
    )
    assert activated_revision == 2
    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="staff.manage_membership",
        aggregate_id=invited.membership_id,
    )
    assert row["details"] == {
        "action": "status_transition",
        "reason_code": "staff_activated",
        "subject_kind": "StaffMembership",
        "revision_before": 1,
        "revision_after": 2,
    }
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.staff_memberships WHERE id = %s",
        (invited.membership_id,),
    ).fetchone() == ("active", 2)

    before = principal_revision(admin_conn, invited.principal_id)
    replaced_revision = await commands.replace_staff_authority(
        actor,
        ReplaceStaffAuthorityCommand(
            membership_id=invited.membership_id,
            expected_authority_revision=before,
            desired_capabilities=("staff.invite",),
            provenance_reference=f"staff-audit-authority:{uuid4().hex}",
            idempotency_key=f"staff-authority-{uuid4().hex}",
        ),
    )
    assert replaced_revision == before + 1
    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="staff.manage_authority",
        aggregate_id=invited.membership_id,
    )
    assert row["details"] == {
        "action": "authority_replace",
        "reason_code": "authority_replaced",
        "subject_kind": "StaffMembership",
        "revision_before": before,
        "revision_after": replaced_revision,
    }
    assert principal_revision(admin_conn, invited.principal_id) == replaced_revision


@pytest.mark.asyncio
async def test_agent_identity_commands_commit_exactly_one_audit_row(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key="appointments.book",
        authority_plane="operational",
    )
    actor = _actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
        capabilities=_AGENT_CAPABILITIES,
    )
    commands = PostgresAgentGovernanceCommands(command_session_factory)

    provision = ProvisionAgentCommand(
        identity_authority_id=workload_authority_id,
        display_name="Audit Evidence Agent",
        purpose="prove append-only identity audit",
        sponsor_principal_id=controller_id,
        operating_mode=AgentOperatingMode.AUTONOMOUS,
        credential_expires_at=datetime.now(UTC) + timedelta(days=30),
        provenance_reference=f"agent-audit-provision:{uuid4().hex}",
        idempotency_key=f"agent-provision-{uuid4().hex}",
    )
    provisioned = await commands.provision_agent(actor, provision)
    assert provisioned.workload_token is not None
    replayed = await commands.provision_agent(actor, provision)
    assert replayed.principal_id == provisioned.principal_id
    assert replayed.workload_token is None

    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="agent.provision",
        aggregate_id=provisioned.principal_id,
    )
    assert row["actor_principal_id"] == controller_id
    assert row["aggregate_kind"] == "AgentPrincipal"
    assert row["details"] == {
        "action": "provision",
        "reason_code": "agent_provisioned",
        "subject_kind": "AgentPrincipal",
        "revision_before": 0,
        "revision_after": provisioned.profile_revision,
    }
    assert provisioned.profile_revision == 1
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.agent_profiles WHERE principal_id = %s",
        (provisioned.principal_id,),
    ).fetchone() == ("pending", 1)

    before = principal_revision(admin_conn, provisioned.principal_id)
    replaced_revision = await commands.replace_agent_authority(
        actor,
        ReplaceAgentAuthorityCommand(
            agent_principal_id=provisioned.principal_id,
            expected_authority_revision=before,
            desired_capabilities=("appointments.book",),
            provenance_reference=f"agent-audit-authority:{uuid4().hex}",
            idempotency_key=f"agent-authority-{uuid4().hex}",
        ),
    )
    assert replaced_revision == before + 1
    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="agent.manage_authority",
        aggregate_id=provisioned.principal_id,
    )
    assert row["details"] == {
        "action": "authority_replace",
        "reason_code": "authority_replaced",
        "subject_kind": "AgentPrincipal",
        "revision_before": before,
        "revision_after": replaced_revision,
    }

    activated_revision = await commands.transition_agent_profile(
        actor,
        TransitionAgentProfileCommand(
            agent_principal_id=provisioned.principal_id,
            expected_revision=1,
            target_status=AgentProfileStatus.ACTIVE,
            provenance_reference=f"agent-audit-activate:{uuid4().hex}",
            idempotency_key=f"agent-activate-{uuid4().hex}",
        ),
    )
    assert activated_revision == 2
    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="agent.suspend",
        aggregate_id=provisioned.principal_id,
    )
    assert row["details"] == {
        "action": "status_transition",
        "reason_code": "agent_activated",
        "subject_kind": "AgentPrincipal",
        "revision_before": 1,
        "revision_after": 2,
    }
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.agent_profiles WHERE principal_id = %s",
        (provisioned.principal_id,),
    ).fetchone() == ("active", 2)


@pytest.mark.asyncio
async def test_integration_identity_commands_commit_exactly_one_audit_row_without_secrets(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    for capability in _INTEGRATION_CAPABILITIES:
        grant_delegable(
            admin_conn,
            principal_id=controller_id,
            organization_id=organization_id,
            capability_key=capability,
            authority_plane="tenant_control",
        )
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key="appointments.book",
        authority_plane="operational",
    )
    workload_authority_id = workload_authority(admin_conn)
    actor = _actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
        capabilities=_INTEGRATION_CAPABILITIES,
    )
    commands = PostgresIntegrationGovernanceCommands(command_session_factory)

    provision = ProvisionIntegrationCommand(
        identity_authority_id=workload_authority_id,
        credential_expires_at=datetime.now(UTC) + timedelta(days=30),
        provenance_reference=f"integration-audit-provision:{uuid4().hex}",
        idempotency_key=f"integration-provision-{uuid4().hex}",
    )
    provisioned = await commands.provision_integration(actor, provision)
    assert provisioned.workload_token is not None
    replayed = await commands.provision_integration(actor, provision)
    assert replayed.principal_id == provisioned.principal_id
    assert replayed.workload_token is None

    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="integration.provision",
        aggregate_id=provisioned.principal_id,
    )
    assert row["aggregate_kind"] == "IntegrationPrincipal"
    assert row["details"] == {
        "action": "provision",
        "reason_code": "integration_provisioned",
        "subject_kind": "IntegrationPrincipal",
        "revision_before": 0,
        "revision_after": provisioned.authority_revision,
    }
    assert provisioned.authority_revision == 1

    before = principal_revision(admin_conn, provisioned.principal_id)
    replaced_revision = await commands.replace_integration_authority(
        actor,
        ReplaceIntegrationAuthorityCommand(
            integration_principal_id=provisioned.principal_id,
            expected_authority_revision=before,
            desired_capabilities=("appointments.book",),
            provenance_reference=f"integration-audit-authority:{uuid4().hex}",
            idempotency_key=f"integration-authority-{uuid4().hex}",
        ),
    )
    assert replaced_revision == before + 1
    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="integration.manage_authority",
        aggregate_id=provisioned.principal_id,
    )
    assert row["details"] == {
        "action": "authority_replace",
        "reason_code": "authority_replaced",
        "subject_kind": "IntegrationPrincipal",
        "revision_before": before,
        "revision_after": replaced_revision,
    }

    activated_revision = await commands.transition_integration_status(
        actor,
        TransitionIntegrationStatusCommand(
            integration_principal_id=provisioned.principal_id,
            expected_revision=replaced_revision,
            target_status=IntegrationStatus.ACTIVE,
            provenance_reference=f"integration-audit-activate:{uuid4().hex}",
            idempotency_key=f"integration-activate-{uuid4().hex}",
        ),
    )
    assert activated_revision > replaced_revision
    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="integration.transition_status",
        aggregate_id=provisioned.principal_id,
    )
    assert row["details"] == {
        "action": "status_transition",
        "reason_code": "integration_activated",
        "subject_kind": "IntegrationPrincipal",
        "revision_before": replaced_revision,
        "revision_after": activated_revision,
    }

    rotated = await commands.rotate_integration_credential(
        actor,
        RotateIntegrationCredentialCommand(
            integration_principal_id=provisioned.principal_id,
            expected_revision=activated_revision,
            credential_expires_at=datetime.now(UTC) + timedelta(days=30),
            provenance_reference=f"integration-audit-rotate:{uuid4().hex}",
            idempotency_key=f"integration-rotate-{uuid4().hex}",
        ),
    )
    assert rotated.workload_token is not None
    assert rotated.authority_revision == activated_revision + 1
    row = _only_row(
        admin_conn,
        organization_id=organization_id,
        command_name="integration_credential_rotate",
        aggregate_id=rotated.credential_id,
    )
    assert row["aggregate_kind"] == "IntegrationCredential"
    assert row["details"] == {
        "action": "credential_rotate",
        "reason_code": "credential_rotated",
        "subject_kind": "IntegrationCredential",
        "revision_before": activated_revision,
        "revision_after": rotated.authority_revision,
    }
    serialized = repr(row["details"])
    assert rotated.workload_token not in serialized
    assert "digest" not in serialized
    assert "token" not in serialized


@pytest.mark.asyncio
async def test_rejected_identity_commands_leave_no_audit_row(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    workload_authority_id = workload_authority(admin_conn)
    grant_delegable(
        admin_conn,
        principal_id=controller_id,
        organization_id=organization_id,
        capability_key="appointments.book",
        authority_plane="operational",
    )
    for capability in _INTEGRATION_CAPABILITIES:
        grant_delegable(
            admin_conn,
            principal_id=controller_id,
            organization_id=organization_id,
            capability_key=capability,
            authority_plane="tenant_control",
        )
    actor = _actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
        capabilities=_STAFF_CAPABILITIES + _AGENT_CAPABILITIES + _INTEGRATION_CAPABILITIES,
    )

    agent_commands = PostgresAgentGovernanceCommands(command_session_factory)
    agent = await agent_commands.provision_agent(
        actor,
        ProvisionAgentCommand(
            identity_authority_id=workload_authority_id,
            display_name="Rejected Agent",
            purpose="stale revision must not audit",
            sponsor_principal_id=controller_id,
            operating_mode=AgentOperatingMode.AUTONOMOUS,
            credential_expires_at=datetime.now(UTC) + timedelta(days=30),
            provenance_reference=f"agent-reject:{uuid4().hex}",
            idempotency_key=f"agent-reject-{uuid4().hex}",
        ),
    )
    from request_engine.modules.tenancy.application.errors import (
        AgentGovernanceRevisionConflict,
    )

    with pytest.raises(AgentGovernanceRevisionConflict):
        await agent_commands.transition_agent_profile(
            actor,
            TransitionAgentProfileCommand(
                agent_principal_id=agent.principal_id,
                expected_revision=99,
                target_status=AgentProfileStatus.ACTIVE,
                provenance_reference=f"agent-reject-stale:{uuid4().hex}",
                idempotency_key=f"agent-reject-stale-{uuid4().hex}",
            ),
        )
    assert (
        _audit_rows(
            admin_conn,
            organization_id=organization_id,
            command_name="agent.suspend",
            aggregate_id=agent.principal_id,
        )
        == []
    )

    integration_commands = PostgresIntegrationGovernanceCommands(command_session_factory)
    integration = await integration_commands.provision_integration(
        actor,
        ProvisionIntegrationCommand(
            identity_authority_id=workload_authority_id,
            credential_expires_at=datetime.now(UTC) + timedelta(days=30),
            provenance_reference=f"integration-reject:{uuid4().hex}",
            idempotency_key=f"integration-reject-{uuid4().hex}",
        ),
    )
    from request_engine.modules.tenancy.application.errors import (
        IntegrationGovernanceRevisionConflict,
    )

    with pytest.raises(IntegrationGovernanceRevisionConflict):
        await integration_commands.rotate_integration_credential(
            actor,
            RotateIntegrationCredentialCommand(
                integration_principal_id=integration.principal_id,
                expected_revision=99,
                credential_expires_at=datetime.now(UTC) + timedelta(days=30),
                provenance_reference=f"integration-reject-stale:{uuid4().hex}",
                idempotency_key=f"integration-reject-stale-{uuid4().hex}",
            ),
        )
    assert (
        _audit_rows(
            admin_conn,
            organization_id=organization_id,
            command_name="integration_credential_rotate",
            aggregate_id=integration.credential_id,
        )
        == []
    )

    staff_commands = PostgresStaffMembershipCommands(command_session_factory)
    invite_authority_id, invite_identity_id, _credential_id = native_identity(admin_conn)
    staff = await staff_commands.invite_native_staff(
        actor,
        InviteNativeStaffCommand(
            identity_authority_id=invite_authority_id,
            native_identity_id=invite_identity_id,
            provenance_reference=f"staff-reject:{uuid4().hex}",
            idempotency_key=f"staff-reject-{uuid4().hex}",
        ),
    )
    from request_engine.modules.tenancy.application.errors import (
        StaffMembershipRevisionConflict,
    )

    with pytest.raises(StaffMembershipRevisionConflict):
        await staff_commands.transition_staff_membership(
            actor,
            TransitionStaffMembershipCommand(
                membership_id=staff.membership_id,
                expected_revision=99,
                target_status=StaffMembershipTargetStatus.ACTIVE,
                provenance_reference=f"staff-reject-stale:{uuid4().hex}",
                idempotency_key=f"staff-reject-stale-{uuid4().hex}",
            ),
        )
    assert (
        _audit_rows(
            admin_conn,
            organization_id=organization_id,
            command_name="staff.manage_membership",
            aggregate_id=staff.membership_id,
        )
        == []
    )


@pytest.mark.asyncio
async def test_identity_audit_row_is_tenant_isolated_and_append_only(
    admin_conn: PgConnection,
    app_role_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    organization_id, _party_id, controller_id, _authority_id = provision_root(admin_conn)
    foreign_organization_id, _foreign_party, _foreign_controller, _foreign_authority = (
        provision_root(admin_conn)
    )
    invite_authority_id, invite_identity_id, _credential_id = native_identity(admin_conn)
    actor = _actor(
        admin_conn,
        organization_id=organization_id,
        principal_id=controller_id,
        capabilities=_STAFF_CAPABILITIES,
    )
    staff_commands = PostgresStaffMembershipCommands(command_session_factory)
    invited = await staff_commands.invite_native_staff(
        actor,
        InviteNativeStaffCommand(
            identity_authority_id=invite_authority_id,
            native_identity_id=invite_identity_id,
            provenance_reference=f"staff-audit-rls:{uuid4().hex}",
            idempotency_key=f"staff-audit-rls-{uuid4().hex}",
        ),
    )
    audit_id = admin_conn.execute(
        """
        SELECT id FROM request_engine.audit_records
         WHERE organization_id = %s AND command_name = 'staff.invite'
           AND aggregate_id = %s
        """,
        (organization_id, invited.membership_id),
    ).fetchone()
    assert audit_id is not None
    audit_id = cast(UUID, audit_id[0])

    app_role_conn.autocommit = True
    app_role_conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    assert app_role_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records WHERE id = %s",
        (audit_id,),
    ).fetchone() == (1,)
    app_role_conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(foreign_organization_id),),
    )
    assert app_role_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records WHERE id = %s",
        (audit_id,),
    ).fetchone() == (0,)

    with pytest.raises(Error) as update_error:
        app_role_conn.execute(
            "UPDATE request_engine.audit_records SET details = '{\"rewritten\":true}'::jsonb "
            "WHERE id = %s",
            (audit_id,),
        )
    assert update_error.value.sqlstate == "42501"
    with pytest.raises(Error) as delete_error:
        app_role_conn.execute(
            "DELETE FROM request_engine.audit_records WHERE id = %s",
            (audit_id,),
        )
    assert delete_error.value.sqlstate == "42501"

    original = admin_conn.execute(
        "SELECT details FROM request_engine.audit_records WHERE id = %s",
        (audit_id,),
    ).fetchone()
    assert original is not None
    assert original[0]["action"] == "invite"
