import pytest

from request_engine.platform.security.capabilities import (
    capability_definition,
    grant_satisfies,
)
from request_engine.platform.security.capability_types import (
    CapabilityExposure,
    CapabilityKind,
    IdempotencyPolicy,
    RevisionPolicy,
)

BOT_CAPABILITY_SUBSET = ("parties.register", "parties.add_contact_point", "parties.lookup")


@pytest.mark.parametrize(
    "key",
    ("parties.register", "parties.add_contact_point", "parties.confirm_contact_point"),
)
def test_party_commands_are_public_idempotent_commands_without_revision(key: str) -> None:
    definition = capability_definition(key)
    assert definition is not None
    assert definition.kind is CapabilityKind.COMMAND
    assert definition.exposure is CapabilityExposure.PUBLIC
    assert definition.idempotency is IdempotencyPolicy.REQUIRED
    assert definition.revision is RevisionPolicy.NONE


def test_party_lookup_is_a_public_query() -> None:
    definition = capability_definition("parties.lookup")
    assert definition is not None
    assert definition.kind is CapabilityKind.QUERY
    assert definition.exposure is CapabilityExposure.PUBLIC
    assert definition.idempotency is IdempotencyPolicy.NONE


def test_bot_grant_subset_does_not_satisfy_confirm_contact_point() -> None:
    """The confirm gate is grant-based: creation/lookup grants never satisfy it."""

    for granted in BOT_CAPABILITY_SUBSET:
        assert not grant_satisfies(granted, "parties.confirm_contact_point")
    assert grant_satisfies("parties.confirm_contact_point", "parties.confirm_contact_point")
