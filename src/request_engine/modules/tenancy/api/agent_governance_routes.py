from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from request_engine.modules.tenancy.api.agent_governance_models import (
    AgentAuthorityReplaceBody,
    AgentAuthorityReplaceView,
    AgentProfileTransitionBody,
    AgentProfileTransitionView,
    AgentProvisionBody,
    AgentProvisionView,
)
from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.agent_governance import (
    AgentGovernanceCommands,
    ProvisionAgentCommand,
    ReplaceAgentAuthorityCommand,
    TransitionAgentProfileCommand,
)
from request_engine.modules.tenancy.application.errors import (
    AgentGovernanceForbidden,
    AgentGovernanceInputInvalid,
)
from request_engine.modules.tenancy.domain.agent_governance import AgentProfileStatus
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability


def add_agent_governance_routes(
    router: APIRouter,
    *,
    commands: AgentGovernanceCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    def authorize(actor: ActorContext, capability: str) -> None:
        require_capability(actor, capability)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise AgentGovernanceForbidden("agent governance commands require a HUMAN actor")

    async def provision_agent(
        body: AgentProvisionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> AgentProvisionView:
        authorize(actor, "agent.provision")
        try:
            result = await commands.provision_agent(
                actor,
                ProvisionAgentCommand(
                    identity_authority_id=body.identity_authority_id,
                    display_name=body.display_name,
                    purpose=body.purpose,
                    sponsor_principal_id=body.sponsor_principal_id,
                    operating_mode=body.operating_mode,
                    credential_expires_at=body.credential_expires_at,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise AgentGovernanceInputInvalid(str(exc)) from None
        return AgentProvisionView(
            principal_id=result.principal_id,
            workload_identity_id=result.workload_identity_id,
            credential_id=result.credential_id,
            binding_id=result.binding_id,
            profile_revision=result.profile_revision,
            workload_token=result.workload_token,
        )

    async def replace_authority(
        agent_principal_id: UUID,
        body: AgentAuthorityReplaceBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> AgentAuthorityReplaceView:
        authorize(actor, "agent.manage_authority")
        try:
            revision = await commands.replace_agent_authority(
                actor,
                ReplaceAgentAuthorityCommand(
                    agent_principal_id=agent_principal_id,
                    expected_authority_revision=body.expected_authority_revision,
                    desired_capabilities=tuple(body.desired_capabilities),
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise AgentGovernanceInputInvalid(str(exc)) from None
        return AgentAuthorityReplaceView(authority_revision=revision)

    async def transition_profile(
        agent_principal_id: UUID,
        body: AgentProfileTransitionBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> AgentProfileTransitionView:
        authorize(actor, "agent.suspend")
        try:
            revision = await commands.transition_agent_profile(
                actor,
                TransitionAgentProfileCommand(
                    agent_principal_id=agent_principal_id,
                    expected_revision=body.expected_revision,
                    target_status=AgentProfileStatus(body.target_status),
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise AgentGovernanceInputInvalid(str(exc)) from None
        return AgentProfileTransitionView(profile_revision=revision)

    add_capability_route(
        router,
        "",
        provision_agent,
        capability="agent.provision",
        methods=["POST"],
        operation_id="agent_provision",
        response_model=AgentProvisionView,
        status_code=status.HTTP_201_CREATED,
    )
    add_capability_route(
        router,
        "/{agent_principal_id}/authority",
        replace_authority,
        capability="agent.manage_authority",
        methods=["PUT"],
        operation_id="agent_manage_authority",
        response_model=AgentAuthorityReplaceView,
    )
    add_capability_route(
        router,
        "/{agent_principal_id}/status",
        transition_profile,
        capability="agent.suspend",
        methods=["PUT"],
        operation_id="agent_suspend",
        response_model=AgentProfileTransitionView,
    )
