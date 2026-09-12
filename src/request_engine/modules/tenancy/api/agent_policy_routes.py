from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from request_engine.modules.tenancy.api.agent_policy_models import (
    AgentPolicyReplaceBody,
    AgentPolicyView,
)
from request_engine.modules.tenancy.api.party_registry_dependencies import IdempotencyKey
from request_engine.modules.tenancy.application.commands.agent_policy import (
    AgentPolicyCommands,
    ReplaceAgentPolicyCommand,
)
from request_engine.modules.tenancy.application.errors import (
    AgentPolicyForbidden,
    AgentPolicyInputInvalid,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import require_capability
from request_engine.platform.security.operation_risk import OperationRiskClass


def add_agent_policy_routes(
    router: APIRouter,
    *,
    commands: AgentPolicyCommands,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    def authorize(actor: ActorContext, capability: str) -> None:
        require_capability(actor, capability)
        if actor.principal_kind is not PrincipalKind.HUMAN:
            raise AgentPolicyForbidden("agent policy operations require a HUMAN actor")

    async def read_agent_policy(
        agent_principal_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> AgentPolicyView:
        authorize(actor, "agent.policy.read")
        try:
            policy = await commands.read_policy(actor, agent_principal_id)
        except ValueError as exc:
            raise AgentPolicyInputInvalid(str(exc)) from None
        return AgentPolicyView(
            agent_principal_id=policy.agent_principal_id,
            allowed_capabilities=list(policy.allowed_capabilities),
            denied_capabilities=list(policy.denied_capabilities),
            risk_ceiling=policy.risk_ceiling,
            max_mutations_per_minute=policy.max_mutations_per_minute,
            policy_revision=policy.policy_revision,
        )

    async def replace_agent_policy(
        agent_principal_id: UUID,
        body: AgentPolicyReplaceBody,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        idempotency_key: IdempotencyKey,
    ) -> AgentPolicyView:
        authorize(actor, "agent.manage_policy")
        try:
            risk_ceiling = OperationRiskClass(body.risk_ceiling)
        except ValueError:
            raise AgentPolicyInputInvalid(
                "risk_ceiling is not a known operation risk class"
            ) from None
        try:
            policy_revision = await commands.replace_policy(
                actor,
                ReplaceAgentPolicyCommand(
                    agent_principal_id=agent_principal_id,
                    allowed_capabilities=tuple(body.allowed_capabilities),
                    denied_capabilities=tuple(body.denied_capabilities),
                    risk_ceiling=risk_ceiling,
                    max_mutations_per_minute=body.max_mutations_per_minute,
                    provenance_reference=body.provenance_reference,
                    idempotency_key=idempotency_key,
                ),
            )
        except ValueError as exc:
            raise AgentPolicyInputInvalid(str(exc)) from None
        return AgentPolicyView(
            agent_principal_id=agent_principal_id,
            allowed_capabilities=body.allowed_capabilities,
            denied_capabilities=body.denied_capabilities,
            risk_ceiling=risk_ceiling,
            max_mutations_per_minute=body.max_mutations_per_minute,
            policy_revision=policy_revision,
        )

    add_capability_route(
        router,
        "/{agent_principal_id}/policy",
        read_agent_policy,
        capability="agent.policy.read",
        methods=["GET"],
        operation_id="agent_policy_read",
        response_model=AgentPolicyView,
        owner="tenancy",
    )
    add_capability_route(
        router,
        "/{agent_principal_id}/policy",
        replace_agent_policy,
        capability="agent.manage_policy",
        methods=["PUT"],
        operation_id="agent_policy_replace",
        response_model=AgentPolicyView,
        owner="tenancy",
    )
