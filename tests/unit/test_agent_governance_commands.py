from dataclasses import fields
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.tenancy.adapters.db.agent_governance_commands import (
    PostgresAgentGovernanceCommands,
)
from request_engine.modules.tenancy.application.commands.agent_governance import (
    ProvisionAgentCommand,
    ProvisionAgentResult,
    ReplaceAgentAuthorityCommand,
    TransitionAgentProfileCommand,
)
from request_engine.modules.tenancy.application.errors import AgentGovernanceForbidden
from request_engine.modules.tenancy.domain.agent_governance import (
    AgentOperatingMode,
    AgentProfileStatus,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind


def _human_actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"agent.provision", "agent.manage_authority", "agent.suspend"}),
        principal_kind=PrincipalKind.HUMAN,
    )


def _agent_actor() -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"agent.provision"}),
        principal_kind=PrincipalKind.AGENT,
    )


def _commands() -> PostgresAgentGovernanceCommands:
    return PostgresAgentGovernanceCommands(cast(SessionFactory, object()))


def _provision_command() -> ProvisionAgentCommand:
    return ProvisionAgentCommand(
        identity_authority_id=uuid4(),
        display_name="Dispatch Agent",
        purpose="Automate intake triage",
        sponsor_principal_id=uuid4(),
        operating_mode=AgentOperatingMode.AUTONOMOUS,
        credential_expires_at=datetime.now(UTC),
        provenance_reference="agent-provision:test",
        idempotency_key="provision-test",
    )


@pytest.mark.asyncio
async def test_agent_governance_rejects_non_human_actor_before_any_execution() -> None:
    commands = _commands()
    actor = _agent_actor()

    with pytest.raises(AgentGovernanceForbidden, match="HUMAN actor"):
        await commands.provision_agent(actor, _provision_command())
    with pytest.raises(AgentGovernanceForbidden, match="HUMAN actor"):
        await commands.replace_agent_authority(
            actor,
            ReplaceAgentAuthorityCommand(
                agent_principal_id=uuid4(),
                expected_authority_revision=1,
                desired_capabilities=("requests.submit",),
                provenance_reference="agent-authority:test",
                idempotency_key="authority-test",
            ),
        )
    with pytest.raises(AgentGovernanceForbidden, match="HUMAN actor"):
        await commands.transition_agent_profile(
            actor,
            TransitionAgentProfileCommand(
                agent_principal_id=uuid4(),
                expected_revision=1,
                target_status=AgentProfileStatus.SUSPENDED,
                provenance_reference="agent-suspend:test",
                idempotency_key="suspend-test",
            ),
        )


@pytest.mark.asyncio
async def test_agent_authority_rejects_non_operational_and_noncanonical_keys() -> None:
    commands = _commands()
    actor = _human_actor()

    for capabilities, match in (
        (("agent.provision",), "not operational"),
        (("organization.provision",), "not operational"),
        (("future.agent.superuser",), "unknown or non-canonical"),
        (("requests.submit", "requests.submit"), "duplicates"),
    ):
        with pytest.raises(ValueError, match=match):
            await commands.replace_agent_authority(
                actor,
                ReplaceAgentAuthorityCommand(
                    agent_principal_id=uuid4(),
                    expected_authority_revision=1,
                    desired_capabilities=capabilities,
                    provenance_reference="agent-authority:test",
                    idempotency_key="authority-test",
                ),
            )


@pytest.mark.asyncio
async def test_agent_provisioning_rejects_invalid_input_before_db_access() -> None:
    commands = _commands()
    actor = _human_actor()

    for provenance in ("   ", "x" * 501):
        with pytest.raises(ValueError, match="between 1 and 500"):
            await commands.provision_agent(
                actor,
                ProvisionAgentCommand(
                    identity_authority_id=uuid4(),
                    display_name="Dispatch Agent",
                    purpose="Automate intake triage",
                    sponsor_principal_id=uuid4(),
                    operating_mode=AgentOperatingMode.AUTONOMOUS,
                    credential_expires_at=datetime.now(UTC),
                    provenance_reference=provenance,
                    idempotency_key="provision-test",
                ),
            )
    with pytest.raises(ValueError, match="idempotency_key is required"):
        await commands.provision_agent(
            actor,
            ProvisionAgentCommand(
                identity_authority_id=uuid4(),
                display_name="Dispatch Agent",
                purpose="Automate intake triage",
                sponsor_principal_id=uuid4(),
                operating_mode=AgentOperatingMode.AUTONOMOUS,
                credential_expires_at=datetime.now(UTC),
                provenance_reference="agent-provision:test",
                idempotency_key="   ",
            ),
        )


@pytest.mark.asyncio
async def test_agent_transition_rejects_pending_target_and_stale_revisions() -> None:
    commands = _commands()
    actor = _human_actor()

    with pytest.raises(ValueError, match="active, suspended, or revoked"):
        await commands.transition_agent_profile(
            actor,
            TransitionAgentProfileCommand(
                agent_principal_id=uuid4(),
                expected_revision=1,
                target_status=AgentProfileStatus.PENDING,
                provenance_reference="agent-suspend:test",
                idempotency_key="suspend-test",
            ),
        )
    with pytest.raises(ValueError, match="expected_revision must be positive"):
        await commands.transition_agent_profile(
            actor,
            TransitionAgentProfileCommand(
                agent_principal_id=uuid4(),
                expected_revision=0,
                target_status=AgentProfileStatus.SUSPENDED,
                provenance_reference="agent-suspend:test",
                idempotency_key="suspend-test",
            ),
        )


def test_provisioning_result_hides_the_one_time_workload_token() -> None:
    token = f"{uuid4()}.one-time-secret-value"
    result = ProvisionAgentResult(
        principal_id=uuid4(),
        workload_identity_id=uuid4(),
        credential_id=uuid4(),
        binding_id=uuid4(),
        profile_revision=1,
        workload_token=token,
    )

    assert "workload_token" not in repr(result)
    assert token not in repr(result)
    token_field = next(f for f in fields(result) if f.name == "workload_token")
    assert token_field.repr is False
