"""Shared inbound HTTP dependencies for the party registry routes.

`registered_via` is derived server-side from the authenticated principal's
subject-override authority (operator) versus its absence (bot); it is never
read from a request body.
"""

from typing import Annotated

from fastapi import Header

from request_engine.modules.tenancy.contracts.party_registry import RegisteredVia
from request_engine.platform.security.context import ActorContext

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=250),
]

_SUBJECT_OVERRIDE_PERMISSION = "appointments.subject_override"


def registered_via(actor: ActorContext) -> RegisteredVia:
    """Derive attribution from the principal's operator override authority."""

    if actor.allows(_SUBJECT_OVERRIDE_PERMISSION):
        return RegisteredVia.OPERATOR
    return RegisteredVia.BOT
