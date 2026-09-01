"""Shared inbound HTTP dependencies for the party registry routes.

`registered_via` is derived server-side from the authenticated principal's
kind: a human principal is an operator, an integration/system principal is a
bot. It is never read from a request body and never derived from a capability
key.
"""

from typing import Annotated

from fastapi import Header

from request_engine.modules.tenancy.contracts.party_registry import RegisteredVia
from request_engine.platform.security.context import ActorContext, PrincipalKind

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def registered_via(actor: ActorContext) -> RegisteredVia:
    """Derive attribution from the authenticated principal's kind."""

    if actor.principal_kind is PrincipalKind.HUMAN:
        return RegisteredVia.OPERATOR
    return RegisteredVia.BOT
