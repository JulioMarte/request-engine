"""Operator/bot attribution derives from the authenticated principal's kind.

`registered_via` is a pure function of `ActorContext.principal_kind`: HUMAN
principals are operators, integration/system principals are bots. These proofs
turn red if the derivation ever keys on a capability key again — a human
principal without `appointments.subject_override` is still an operator.
"""

from uuid import uuid4

import pytest

from request_engine.modules.tenancy.api.party_registry_dependencies import registered_via
from request_engine.modules.tenancy.contracts.party_registry import RegisteredVia
from request_engine.platform.security.context import ActorContext, PrincipalKind


def _actor(principal_kind: PrincipalKind, *capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(capabilities),
        principal_kind=principal_kind,
    )


@pytest.mark.parametrize(
    ("principal_kind", "expected_via"),
    [
        (PrincipalKind.HUMAN, RegisteredVia.OPERATOR),
        (PrincipalKind.INTEGRATION, RegisteredVia.BOT),
        (PrincipalKind.SYSTEM, RegisteredVia.BOT),
    ],
)
def test_registered_via_derives_from_principal_kind(
    principal_kind: PrincipalKind, expected_via: RegisteredVia
) -> None:
    assert registered_via(_actor(principal_kind, "parties.register")) is expected_via


def test_human_kind_without_override_authority_is_still_an_operator() -> None:
    """The old capability-keyed derivation would have attributed a bot here."""

    actor = _actor(PrincipalKind.HUMAN, "parties.register")
    assert "appointments.subject_override" not in actor.capabilities
    assert registered_via(actor) is RegisteredVia.OPERATOR
