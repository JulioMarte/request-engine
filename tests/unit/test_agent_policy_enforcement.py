from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Request

from request_engine.platform.security.agent_policy import (
    AgentBudgetExceeded,
    AgentPolicyDenied,
    AgentPolicySnapshot,
    AgentRiskDenied,
)
from request_engine.platform.security.agent_policy_http import AgentPolicyActorResolver
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.operation_risk import (
    OperationRiskClass,
    risk_severity,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]


class _StaticActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        return self.actor


class _StubPolicyReader:
    def __init__(self, policy: AgentPolicySnapshot | None) -> None:
        self.policy = policy
        self.calls = 0
        self.requested_organization_id: UUID | None = None
        self.requested_principal_id: UUID | None = None

    async def read_policy(
        self, *, organization_id: UUID, principal_id: UUID
    ) -> AgentPolicySnapshot | None:
        self.calls += 1
        self.requested_organization_id = organization_id
        self.requested_principal_id = principal_id
        return self.policy


class _StubBudgetEnforcer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def consume_mutation(
        self, *, organization_id: UUID, principal_id: UUID, limit: int
    ) -> None:
        self.calls.append(
            {
                "organization_id": organization_id,
                "principal_id": principal_id,
                "limit": limit,
            }
        )


def _request(capability_key: str | None, *, marked: bool = True) -> Request:
    scope: dict[str, object] = {"type": "http", "headers": []}
    if capability_key is not None or marked:
        scope["route"] = (
            SimpleNamespace(request_engine_capability=capability_key)
            if capability_key is not None
            else SimpleNamespace()
        )
    return Request(scope)


def _agent_actor(*capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        principal_kind=PrincipalKind.AGENT,
        capabilities=frozenset(capabilities),
    )


def _policy(
    risk_ceiling: OperationRiskClass,
    *,
    allowed: frozenset[str] | None = None,
    denied: frozenset[str] = frozenset(),
    limit: int = 10,
) -> AgentPolicySnapshot:
    return AgentPolicySnapshot(
        allowed_capabilities=allowed
        if allowed is not None
        else frozenset({"appointments.reschedule"}),
        denied_capabilities=denied,
        risk_ceiling=risk_ceiling,
        max_mutations_per_minute=limit,
        policy_revision=3,
    )


@pytest.mark.asyncio
async def test_human_actor_passes_through_without_policy_reads() -> None:
    human = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"appointments.book"}),
    )
    reader = _StubPolicyReader(_policy(OperationRiskClass.DESTRUCTIVE))
    resolver = AgentPolicyActorResolver(_StaticActorResolver(human), reader)

    actor = await resolver.resolve_actor(_request("appointments.book"))

    assert actor is human
    assert actor.agent_policy is None
    assert reader.calls == 0


@pytest.mark.asyncio
async def test_agent_without_policy_fails_closed() -> None:
    reader = _StubPolicyReader(None)
    resolver = AgentPolicyActorResolver(_StaticActorResolver(_agent_actor()), reader)

    with pytest.raises(AgentPolicyDenied):
        await resolver.resolve_actor(_request("appointments.reschedule"))

    assert reader.calls == 1


@pytest.mark.asyncio
async def test_unmarked_route_fails_closed_for_agent() -> None:
    reader = _StubPolicyReader(_policy(OperationRiskClass.DESTRUCTIVE))
    resolver = AgentPolicyActorResolver(_StaticActorResolver(_agent_actor()), reader)

    with pytest.raises(AgentPolicyDenied):
        await resolver.resolve_actor(_request(None))


@pytest.mark.asyncio
async def test_unknown_capability_key_fails_closed_for_agent() -> None:
    reader = _StubPolicyReader(_policy(OperationRiskClass.DESTRUCTIVE))
    resolver = AgentPolicyActorResolver(_StaticActorResolver(_agent_actor()), reader)

    with pytest.raises(AgentPolicyDenied):
        await resolver.resolve_actor(_request("not.a.capability"))


@pytest.mark.asyncio
async def test_effective_capabilities_intersect_allowed_and_remove_denied() -> None:
    actor = _agent_actor("appointments.reschedule", "appointments.book", "parties.register")
    policy = _policy(
        OperationRiskClass.REVERSIBLE_WRITE,
        allowed=frozenset({"appointments.reschedule", "appointments.book", "queue.join"}),
        denied=frozenset({"appointments.book"}),
    )
    budget = _StubBudgetEnforcer()
    reader = _StubPolicyReader(policy)
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader, budget)

    resolved = await resolver.resolve_actor(_request("appointments.reschedule"))

    assert resolved.capabilities == frozenset({"appointments.reschedule"})
    assert resolved.agent_policy is policy
    assert len(budget.calls) == 1
    assert budget.calls[0]["limit"] == policy.max_mutations_per_minute


@pytest.mark.asyncio
async def test_risk_above_ceiling_is_denied() -> None:
    actor = _agent_actor("appointments.book")
    reader = _StubPolicyReader(
        _policy(OperationRiskClass.LOW_IMPACT_WRITE, allowed=frozenset({"appointments.book"}))
    )
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader)

    with pytest.raises(AgentRiskDenied):
        await resolver.resolve_actor(_request("appointments.book"))


@pytest.mark.asyncio
async def test_authority_change_is_banned_regardless_of_ceiling() -> None:
    actor = _agent_actor("staff.manage_authority")
    reader = _StubPolicyReader(
        _policy(OperationRiskClass.DESTRUCTIVE, allowed=frozenset({"staff.manage_authority"}))
    )
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader)

    with pytest.raises(AgentRiskDenied):
        await resolver.resolve_actor(_request("staff.manage_authority"))


@pytest.mark.asyncio
async def test_unclassified_command_is_denied_for_agent() -> None:
    actor = _agent_actor("queue.call_next")
    reader = _StubPolicyReader(
        _policy(OperationRiskClass.DESTRUCTIVE, allowed=frozenset({"queue.call_next"}))
    )
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader)

    with pytest.raises(AgentRiskDenied):
        await resolver.resolve_actor(_request("queue.call_next"))


@pytest.mark.asyncio
async def test_query_capability_defaults_to_read_and_passes_at_read_ceiling() -> None:
    actor = _agent_actor("appointments.find_slots")
    reader = _StubPolicyReader(
        _policy(OperationRiskClass.READ, allowed=frozenset({"appointments.find_slots"}))
    )
    budget = _StubBudgetEnforcer()
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader, budget)

    resolved = await resolver.resolve_actor(_request("appointments.find_slots"))

    assert resolved.capabilities == frozenset({"appointments.find_slots"})
    assert resolved.agent_policy is reader.policy
    assert budget.calls == []


@pytest.mark.asyncio
async def test_budget_is_not_consumed_when_capability_is_denied_by_policy() -> None:
    actor = _agent_actor("appointments.book")
    reader = _StubPolicyReader(
        _policy(
            OperationRiskClass.DESTRUCTIVE,
            allowed=frozenset({"appointments.book"}),
            denied=frozenset({"appointments.book"}),
        )
    )
    budget = _StubBudgetEnforcer()
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader, budget)

    resolved = await resolver.resolve_actor(_request("appointments.book"))

    assert resolved.capabilities == frozenset()
    assert budget.calls == []


@pytest.mark.asyncio
async def test_budget_is_not_consumed_when_capability_is_ungranted() -> None:
    actor = _agent_actor()
    reader = _StubPolicyReader(
        _policy(OperationRiskClass.DESTRUCTIVE, allowed=frozenset({"appointments.reschedule"}))
    )
    budget = _StubBudgetEnforcer()
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader, budget)

    resolved = await resolver.resolve_actor(_request("appointments.reschedule"))

    assert resolved.capabilities == frozenset()
    assert budget.calls == []


@pytest.mark.asyncio
async def test_budget_exhaustion_propagates() -> None:
    class _ExhaustedBudget:
        async def consume_mutation(
            self, *, organization_id: UUID, principal_id: UUID, limit: int
        ) -> None:
            raise AgentBudgetExceeded("agent mutation budget for the current minute is exhausted")

    actor = _agent_actor("appointments.reschedule")
    reader = _StubPolicyReader(_policy(OperationRiskClass.REVERSIBLE_WRITE))
    resolver = AgentPolicyActorResolver(_StaticActorResolver(actor), reader, _ExhaustedBudget())

    with pytest.raises(AgentBudgetExceeded):
        await resolver.resolve_actor(_request("appointments.reschedule"))


def test_agent_policy_capabilities_exist_in_registry() -> None:
    policy_read = capability_definition("agent.policy.read")
    manage_policy = capability_definition("agent.manage_policy")

    assert policy_read is not None
    assert policy_read.kind.value == "query"
    assert manage_policy is not None
    assert manage_policy.kind.value == "command"
    assert manage_policy.revision.value == "required"


def test_effective_risk_class_defaults_and_explicit_classifications() -> None:
    query = capability_definition("appointments.find_slots")
    unclassified_command = capability_definition("queue.call_next")
    booking = capability_definition("appointments.book")
    authority = capability_definition("staff.manage_authority")

    assert query is not None and query.effective_risk_class is OperationRiskClass.READ
    assert unclassified_command is not None and unclassified_command.effective_risk_class is None
    assert booking is not None
    assert booking.effective_risk_class is OperationRiskClass.EXTERNAL_COMMITMENT
    assert authority is not None
    assert authority.effective_risk_class is OperationRiskClass.AUTHORITY_CHANGE


def test_risk_severity_ordering_matches_documented_classes() -> None:
    order = (
        OperationRiskClass.READ,
        OperationRiskClass.LOW_IMPACT_WRITE,
        OperationRiskClass.REVERSIBLE_WRITE,
        OperationRiskClass.EXTERNAL_COMMITMENT,
        OperationRiskClass.SENSITIVE_DATA,
        OperationRiskClass.FINANCIAL,
        OperationRiskClass.DESTRUCTIVE,
        OperationRiskClass.AUTHORITY_CHANGE,
    )

    severities = [risk_severity(risk) for risk in order]
    assert severities == sorted(severities)
    assert len(set(severities)) == len(severities)
