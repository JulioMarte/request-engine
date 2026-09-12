from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.delegation import (
    DelegationForeign,
    DelegationInvalid,
    DelegationReader,
    resolve_delegated_capabilities,
)
from request_engine.platform.security.http import ActorResolver

DELEGATION_HEADER = "X-RE-Delegation-ID"


class DelegatedAgentActorResolver:
    """Resolve bounded delegated execution for AGENT Principals.

    When a request carries the delegation header, the materialized actor's
    standing authority is replaced by the intersection-resolved delegated
    authority and the delegation attribution is preserved on the ActorContext.
    Requests without the header resolve exactly as before.
    """

    def __init__(self, delegate: ActorResolver, reader: DelegationReader) -> None:
        self._delegate = delegate
        self._reader = reader

    async def resolve_actor(self, request: Request) -> ActorContext:
        actor = await self._delegate.resolve_actor(request)
        raw_value = request.headers.get(DELEGATION_HEADER)
        if raw_value is None:
            return actor
        try:
            delegation_id = UUID(raw_value.strip())
        except ValueError as exc:
            raise DelegationInvalid("delegation reference is malformed") from exc
        delegation = await self._reader.read_delegation(
            organization_id=actor.organization_id,
            delegation_id=delegation_id,
        )
        if delegation is None:
            raise DelegationInvalid("delegation does not exist in this tenant")
        if delegation.delegate_principal_id != actor.principal_id:
            raise DelegationForeign("delegation does not name the authenticated agent")
        if actor.principal_kind.value != "agent":
            raise DelegationInvalid("only AGENT Principals may execute under a delegation")
        delegator_delegable = await self._reader.read_delegator_delegable_capabilities(
            organization_id=actor.organization_id,
            principal_id=delegation.delegator_principal_id,
        )
        effective = resolve_delegated_capabilities(
            delegation=delegation,
            delegator_delegable=delegator_delegable,
            now=datetime.now(UTC),
        )
        return replace(
            actor,
            capabilities=effective,
            delegation_id=delegation.delegation_id,
        )


__all__ = ["DELEGATION_HEADER", "DelegatedAgentActorResolver"]
