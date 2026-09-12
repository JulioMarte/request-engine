"""Acting-operator relay admission for trusted integration callers (§9.1).

An integration/system principal (bot platform) may execute operator-directed
mutations only when it presents the ``X-RE-Acting-Operator`` header and holds
``platform.acting_for_operator``. The referenced Principal must resolve to an
active HUMAN of the same Organization. The effective context intentionally
uses the human's authority while ``technical_principal_id`` preserves the
trusted relay identity.

First-class AGENT Principals are deliberately excluded from this legacy relay.
An AGENT must act under its own standing authority or an explicit bounded
DelegationGrant; it may not select a human and become that human through this
header. This keeps actor-vs-subject attribution intact for agentic execution.
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


class OperatorResolutionUnavailable(Exception):
    """The deployment provides no operator resolution for the relay port."""


class AgentActingOperatorRelayForbidden(Exception):
    """A first-class agent attempted to use the legacy human-impersonating relay."""


class OperatorActorResolver(Protocol):
    """Deployment port resolving one admitted acting-operator principal."""

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
    """Resolve the effective actor behind an admitted legacy relay request."""

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
        if actor.principal_kind is PrincipalKind.AGENT:
            raise AgentActingOperatorRelayForbidden()
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
            raise OperatorResolutionUnavailable()
        operator = await self._operator_actors.resolve_operator_actor(organization_id, principal_id)
        if (
            operator is None
            or operator.organization_id != organization_id
            or operator.principal_id != principal_id
            or operator.principal_kind is not PrincipalKind.HUMAN
        ):
            raise CapabilityRequired(ACTING_FOR_OPERATOR_PERMISSION)
        return operator
