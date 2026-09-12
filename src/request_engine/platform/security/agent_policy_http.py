from __future__ import annotations

from dataclasses import replace

from fastapi import Request

from request_engine.platform.security.agent_policy import (
    AgentBudgetEnforcer,
    AgentPolicyDenied,
    AgentPolicyReader,
    AgentRiskDenied,
)
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import CapabilityKind
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import ActorResolver
from request_engine.platform.security.operation_risk import OperationRiskClass, risk_severity


class AgentPolicyActorResolver:
    """Enforce the least-privilege tool/risk ceiling for AGENT Principals.

    Applied outside delegated resolution, the policy read is fresh per request,
    effective authority is the granted ∩ allowed − denied intersection, risk
    above the ceiling and every AUTHORITY_CHANGE operation are denied, and the
    mutation budget is consumed only for granted command capabilities.
    Unmarked routes and missing policies fail closed.
    """

    def __init__(
        self,
        delegate: ActorResolver,
        reader: AgentPolicyReader,
        budget: AgentBudgetEnforcer | None = None,
    ) -> None:
        self._delegate = delegate
        self._reader = reader
        self._budget = budget

    async def resolve_actor(self, request: Request) -> ActorContext:
        actor = await self._delegate.resolve_actor(request)
        if actor.principal_kind is not PrincipalKind.AGENT:
            return actor
        policy = await self._reader.read_policy(
            organization_id=actor.organization_id,
            principal_id=actor.principal_id,
        )
        if policy is None:
            raise AgentPolicyDenied(
                "agent has no tool/risk policy; the least-privilege default denies every operation"
            )
        route = request.scope.get("route")
        capability_key = getattr(route, "request_engine_capability", None)
        definition = capability_definition(capability_key) if capability_key is not None else None
        if definition is None:
            raise AgentPolicyDenied("operation is not agent-admissible for AGENT Principals")
        effective = frozenset(
            key
            for key in actor.capabilities
            if key in policy.allowed_capabilities and key not in policy.denied_capabilities
        )
        risk = definition.effective_risk_class
        if risk is None:
            raise AgentRiskDenied(
                "operation risk for capability "
                f"{definition.key!r} is unclassified for agent execution"
            )
        if risk is OperationRiskClass.AUTHORITY_CHANGE or risk_severity(risk) > risk_severity(
            policy.risk_ceiling
        ):
            raise AgentRiskDenied(f"capability {definition.key!r} exceeds the agent risk ceiling")
        if definition.kind is CapabilityKind.COMMAND and definition.key in effective:
            if self._budget is None:
                raise AgentPolicyDenied("agent budget enforcement is not composed")
            await self._budget.consume_mutation(
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                limit=policy.max_mutations_per_minute,
            )
        return replace(actor, capabilities=effective, agent_policy=policy)


__all__ = ["AgentPolicyActorResolver"]
