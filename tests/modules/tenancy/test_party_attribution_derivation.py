"""Source-kind attribution derives from the effective actor's principal kind.

`source_kind` is a pure function of the effective `ActorContext`: HUMAN
principals are operators; integration/system principals acting for themselves
are subjects (docs/v3/38 §9.1). A relayed bot arrives at the routes as the
admitted operator actor (HUMAN), so its writes attribute to the operator.
These proofs turn red if the derivation ever keys on a capability key or on
the declared platform again.
"""

from dataclasses import replace
from uuid import uuid4

import pytest

from request_engine.modules.tenancy.api.party_registry_dependencies import source_kind
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.security.context import ActorContext, PrincipalKind


def _actor(principal_kind: PrincipalKind, *capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(capabilities),
        principal_kind=principal_kind,
    )


@pytest.mark.parametrize(
    ("principal_kind", "expected_kind"),
    [
        (PrincipalKind.HUMAN, PartySourceKind.OPERATOR),
        (PrincipalKind.INTEGRATION, PartySourceKind.SUBJECT),
        (PrincipalKind.SYSTEM, PartySourceKind.SUBJECT),
    ],
)
def test_source_kind_derives_from_principal_kind(
    principal_kind: PrincipalKind, expected_kind: PartySourceKind
) -> None:
    assert source_kind(_actor(principal_kind, "parties.register")) is expected_kind


def test_human_kind_without_relay_permission_is_still_an_operator() -> None:
    """The old capability-keyed derivation would have attributed a bot here."""

    actor = _actor(PrincipalKind.HUMAN, "parties.register")
    assert "platform.acting_for_operator" not in actor.capabilities
    assert source_kind(actor) is PartySourceKind.OPERATOR


def test_relayed_bot_effective_actor_attributes_to_the_operator() -> None:
    """After admission the effective actor is the operator (HUMAN)."""

    effective = replace(
        _actor(PrincipalKind.HUMAN, "parties.register"),
        platform="whatsapp_bot",
        technical_principal_id=uuid4(),
    )
    assert effective.principal_kind is PrincipalKind.HUMAN
    assert source_kind(effective) is PartySourceKind.OPERATOR
