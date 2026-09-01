"""Acting-operator relay admission at the platform security boundary.

The relay fails closed (docs/v3/38 §9.1): a caller without
`platform.acting_for_operator` is 403, an operator that does not resolve to an
active HUMAN principal of the same organization is 403, and a HUMAN caller's
relay header is ignored. A composition with no operator port is deployment
misconfiguration, not a permission denial: it raises the typed
`OperatorResolutionUnavailable` instead of a 403. When admitted, the
effective actor carries the operator's capabilities and principal identity
(authorization and idempotency) while `technical_principal_id` preserves the
caller.
"""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi import Request

from request_engine.platform.security.acting_operator import (
    ACTING_FOR_OPERATOR_PERMISSION,
    ActingOperatorActorResolver,
    OperatorResolutionUnavailable,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired

ORG_ID = uuid4()
OPERATOR_ID = uuid4()
BOT_ID = uuid4()


def _request(*, acting: UUID | None = None, platform: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if acting is not None:
        headers.append((b"x-re-acting-operator", str(acting).encode()))
    if platform is not None:
        headers.append((b"x-re-platform", platform.encode()))
    return Request({"type": "http", "headers": headers, "method": "POST", "path": "/"})


def _actor(
    principal_kind: PrincipalKind = PrincipalKind.INTEGRATION,
    *capabilities: str,
    principal_id: UUID = BOT_ID,
) -> ActorContext:
    return ActorContext(
        organization_id=ORG_ID,
        principal_id=principal_id,
        capabilities=frozenset(capabilities),
        principal_kind=principal_kind,
    )


def _operator_actor(*capabilities: str) -> ActorContext:
    return _actor(PrincipalKind.HUMAN, *capabilities, principal_id=OPERATOR_ID)


class _StaticDelegate:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


class _StaticOperatorActors:
    def __init__(self, operator: ActorContext | None) -> None:
        self._operator = operator

    async def resolve_operator_actor(
        self, organization_id: UUID, principal_id: UUID
    ) -> ActorContext | None:
        del organization_id, principal_id
        return self._operator


_DEFAULT_OPERATOR = _operator_actor("parties.register")


def _resolver(
    actor: ActorContext, operator: ActorContext | None = _DEFAULT_OPERATOR
) -> ActingOperatorActorResolver:
    return ActingOperatorActorResolver(_StaticDelegate(actor), _StaticOperatorActors(operator))


@pytest.mark.asyncio
async def test_relay_without_admission_permission_fails_closed() -> None:
    actor = _actor(PrincipalKind.INTEGRATION, "parties.register")
    with pytest.raises(CapabilityRequired) as caught:
        await _resolver(actor).resolve_actor(_request(acting=OPERATOR_ID))
    assert caught.value.capability == ACTING_FOR_OPERATOR_PERMISSION


@pytest.mark.asyncio
async def test_admitted_relay_resolves_effective_operator_actor() -> None:
    actor = _actor(PrincipalKind.INTEGRATION, ACTING_FOR_OPERATOR_PERMISSION)
    resolved = await _resolver(actor).resolve_actor(
        _request(acting=OPERATOR_ID, platform="whatsapp_bot")
    )
    assert resolved.principal_id == OPERATOR_ID
    assert resolved.organization_id == ORG_ID
    assert resolved.allows("parties.register")
    assert resolved.technical_principal_id == BOT_ID
    assert resolved.acting_operator_principal_id == OPERATOR_ID
    assert resolved.platform == "whatsapp_bot"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operator",
    [
        None,
        _actor(PrincipalKind.HUMAN, "parties.register", principal_id=uuid4()),
        replace(_actor(PrincipalKind.SYSTEM, "parties.register"), principal_id=OPERATOR_ID),
    ],
)
async def test_unresolvable_or_foreign_or_non_human_operator_fails_closed(
    operator: ActorContext | None,
) -> None:
    actor = _actor(PrincipalKind.INTEGRATION, ACTING_FOR_OPERATOR_PERMISSION)
    with pytest.raises(CapabilityRequired):
        await _resolver(actor, operator).resolve_actor(_request(acting=OPERATOR_ID))


@pytest.mark.asyncio
async def test_relay_without_operator_port_is_deployment_misconfiguration() -> None:
    actor = _actor(PrincipalKind.INTEGRATION, ACTING_FOR_OPERATOR_PERMISSION)
    resolver = ActingOperatorActorResolver(_StaticDelegate(actor), None)
    with pytest.raises(OperatorResolutionUnavailable):
        await resolver.resolve_actor(_request(acting=OPERATOR_ID))


@pytest.mark.asyncio
async def test_human_caller_ignores_the_relay_header() -> None:
    resolved = await _resolver(_operator_actor("parties.register")).resolve_actor(
        _request(acting=uuid4(), platform="reception_web")
    )
    assert resolved.principal_id == OPERATOR_ID
    assert resolved.technical_principal_id is None
    assert resolved.platform == "reception_web"
