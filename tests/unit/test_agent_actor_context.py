from uuid import UUID, uuid4

import pytest
from fastapi import Request

from request_engine.platform.security.acting_operator import (
    ACTING_OPERATOR_HEADER,
    ActingOperatorActorResolver,
    AgentActingOperatorRelayForbidden,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind

pytestmark = [pytest.mark.unit, pytest.mark.security]


class _StaticActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        return self.actor


class _UnexpectedOperatorResolver:
    async def resolve_operator_actor(
        self, organization_id: UUID, principal_id: UUID
    ) -> ActorContext | None:
        raise AssertionError("agent relay must fail before resolving a human operator")


def _request_with_acting_operator(principal_id: UUID) -> Request:
    raw_headers = [(ACTING_OPERATOR_HEADER.lower().encode(), str(principal_id).encode())]
    return Request({"type": "http", "headers": raw_headers})


def test_agent_is_a_first_class_principal_kind() -> None:
    assert PrincipalKind.AGENT.value == "agent"


def test_actor_context_preserves_agent_subject_and_delegation_attribution() -> None:
    organization_id = uuid4()
    agent_id = uuid4()
    human_id = uuid4()
    delegation_id = uuid4()

    actor = ActorContext(
        organization_id=organization_id,
        principal_id=agent_id,
        principal_kind=PrincipalKind.AGENT,
        capabilities=frozenset({"appointments.reschedule"}),
        subject_principal_id=human_id,
        delegation_id=delegation_id,
        authority_revision=7,
        interaction_id="task-42",
    )

    assert actor.principal_id == agent_id
    assert actor.subject_principal_id == human_id
    assert actor.delegation_id == delegation_id
    assert actor.authority_revision == 7
    assert actor.interaction_id == "task-42"


@pytest.mark.asyncio
async def test_agent_cannot_use_legacy_acting_operator_relay() -> None:
    organization_id = uuid4()
    human_id = uuid4()
    agent = ActorContext(
        organization_id=organization_id,
        principal_id=uuid4(),
        principal_kind=PrincipalKind.AGENT,
        capabilities=frozenset({"platform.acting_for_operator"}),
    )
    resolver = ActingOperatorActorResolver(_StaticActorResolver(agent), _UnexpectedOperatorResolver())

    with pytest.raises(AgentActingOperatorRelayForbidden):
        await resolver.resolve_actor(_request_with_acting_operator(human_id))


def test_actor_context_rejects_stale_or_ambiguous_attribution_shapes() -> None:
    principal_id = uuid4()
    with pytest.raises(ValueError, match="authority_revision"):
        ActorContext(
            organization_id=uuid4(),
            principal_id=principal_id,
            capabilities=frozenset(),
            authority_revision=0,
        )
    with pytest.raises(ValueError, match="subject_principal_id"):
        ActorContext(
            organization_id=uuid4(),
            principal_id=principal_id,
            capabilities=frozenset(),
            subject_principal_id=principal_id,
        )
