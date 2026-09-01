"""Acting-operator relay admission for trusted integration callers (§9.1).

An integration/system principal (bot platform) may execute operator-directed
mutations only when it presents the `X-RE-Acting-Operator` header and holds the
`platform.acting_for_operator` admission permission. The referenced principal
must resolve, through the deployment operator port, to an active human
principal of the same organization; the resolved effective actor carries the
operator's capabilities and principal identity (authorization and idempotency)
while `technical_principal_id` preserves the caller for attribution. The bot
cannot launder authority the operator does not have.

`X-RE-Platform` records the executing surface verbatim (<= 64 chars); it is
never an authorization input. A HUMAN caller's relay header is ignored.
"""

from dataclasses import replace
from typing import Protocol
from uuid import UUID

from fastapi import Request
from fastapi.exceptions import RequestValidationError

from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import ActorResolver, CapabilityRequired

PLATFORM_HEADER = "X-RE-Platform"
ACTING_OPERATOR_HEADER = "X-RE-Acting-Operator"
ACTING_FOR_OPERATOR_PERMISSION = "platform.acting_for_operator"
_MAX_PLATFORM_LENGTH = 64


class OperatorActorResolver(Protocol):
    """Deployment port resolving one admitted acting-operator principal.

    Implementations authenticate against authoritative principal truth and
    return the operator's ActorContext only when the principal exists and is
    active; anything else returns None and the relay fails closed.
    """

    async def resolve_operator_actor(
        self, organization_id: UUID, principal_id: UUID
    ) -> ActorContext | None: ...


def _header_error(header: str, message: str, value: str) -> RequestValidationError:
    return RequestValidationError(
        [{"loc": ("header", header), "msg": message, "type": "value_error", "input": value}]
    )


def validated_platform(request: Request) -> str | None:
    """Return the declared platform surface, or None when the header is absent."""

    raw = request.headers.get(PLATFORM_HEADER)
    if raw is None:
        return None
    platform = raw.strip()
    if not platform or len(platform) > _MAX_PLATFORM_LENGTH:
        raise _header_error(
            PLATFORM_HEADER,
            f"must be a non-empty surface of at most {_MAX_PLATFORM_LENGTH} characters",
            raw,
        )
    return platform


def validated_acting_operator(request: Request) -> UUID | None:
    """Return the referenced acting-operator principal, or None when absent."""

    raw = request.headers.get(ACTING_OPERATOR_HEADER)
    if raw is None:
        return None
    try:
        return UUID(raw.strip())
    except ValueError:
        raise _header_error(ACTING_OPERATOR_HEADER, "must be a valid principal UUID", raw) from None


class ActingOperatorActorResolver:
    """Resolve the effective actor behind an acting-operator relay request."""

    def __init__(
        self, delegate: ActorResolver, operator_actors: OperatorActorResolver | None
    ) -> None:
        self._delegate = delegate
        self._operator_actors = operator_actors

    async def resolve_actor(self, request: Request) -> ActorContext:
        actor = await self._delegate.resolve_actor(request)
        platform = validated_platform(request)
        acting_operator = validated_acting_operator(request)
        if actor.principal_kind is PrincipalKind.HUMAN or acting_operator is None:
            return replace(actor, platform=platform)
        if not actor.allows(ACTING_FOR_OPERATOR_PERMISSION):
            raise CapabilityRequired(ACTING_FOR_OPERATOR_PERMISSION)
        operator = await self._admitted_operator(actor.organization_id, acting_operator)
        return replace(
            operator,
            platform=platform,
            acting_operator_principal_id=operator.principal_id,
            technical_principal_id=actor.principal_id,
        )

    async def _admitted_operator(self, organization_id: UUID, principal_id: UUID) -> ActorContext:
        if self._operator_actors is None:
            raise CapabilityRequired(ACTING_FOR_OPERATOR_PERMISSION)
        operator = await self._operator_actors.resolve_operator_actor(organization_id, principal_id)
        if (
            operator is None
            or operator.organization_id != organization_id
            or operator.principal_id != principal_id
            or operator.principal_kind is not PrincipalKind.HUMAN
        ):
            raise CapabilityRequired(ACTING_FOR_OPERATOR_PERMISSION)
        return operator
