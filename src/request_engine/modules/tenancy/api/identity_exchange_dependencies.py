"""Trust-boundary checks specific to the first S0d identity proof."""

from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeOperatorRequired,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind


def require_operator_document_witness(actor: ActorContext) -> None:
    """Fail closed when a raw integration/system actor asserts an in-person witness."""

    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise IdentityExchangeOperatorRequired(
            "operator_document_witness requires an effective human operator"
        )
