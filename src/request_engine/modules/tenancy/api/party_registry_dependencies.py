"""Shared inbound HTTP dependencies for the party registry routes.

`source_kind` is derived server-side from the effective authenticated actor:
a human principal is an operator; an integration/system principal acting
without an admitted acting-operator relay is the subject (§9.1). The
acting-operator relay is resolved upstream in the platform security stack, so
a relayed bot arrives here already as the operator actor. Platform and
technical-caller attribution come from `ActorContext.platform` and
`ActorContext.technical_principal_id`. No attribution value is ever read from
a request body or derived from a capability key.
"""

from typing import Annotated

from fastapi import Header

from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.security.context import ActorContext, PrincipalKind

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]


def source_kind(actor: ActorContext) -> PartySourceKind:
    """Derive authority attribution from the effective principal's kind."""

    if actor.principal_kind is PrincipalKind.HUMAN:
        return PartySourceKind.OPERATOR
    return PartySourceKind.SUBJECT
