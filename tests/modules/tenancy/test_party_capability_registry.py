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
OPERATOR_CORRECTIONS = (
    "parties.add_administrative_identifier",
    "parties.rename",
    "parties.add_document",
    "parties.deactivate_contact_point",
    "parties.deactivate",
)
OPERATOR_QUERIES = ("parties.lookup_administrative_identifier", "parties.read_revisions")


@pytest.mark.parametrize(
    "key",
    (
        "parties.register",
        "parties.add_contact_point",
        "parties.confirm_contact_point",
        *OPERATOR_CORRECTIONS,
    ),
)
def test_party_commands_are_public_idempotent_commands_without_revision(key: str) -> None:
    definition = capability_definition(key)
    assert definition is not None
    assert definition.kind is CapabilityKind.COMMAND
    assert definition.exposure is CapabilityExposure.PUBLIC
    assert definition.idempotency is IdempotencyPolicy.REQUIRED
    assert definition.revision is RevisionPolicy.NONE


@pytest.mark.parametrize("key", ("parties.lookup", *OPERATOR_QUERIES))
def test_party_queries_are_public_and_non_idempotent(key: str) -> None:
    definition = capability_definition(key)
    assert definition is not None
    assert definition.kind is CapabilityKind.QUERY
    assert definition.exposure is CapabilityExposure.PUBLIC
    assert definition.idempotency is IdempotencyPolicy.NONE


def test_rollback_identity_is_a_public_idempotent_command() -> None:
    definition = capability_definition("parties.rollback_identity")
    assert definition is not None
    assert definition.kind is CapabilityKind.COMMAND
    assert definition.exposure is CapabilityExposure.PUBLIC
    assert definition.idempotency is IdempotencyPolicy.REQUIRED


def test_bot_grant_subset_does_not_satisfy_operator_only_capabilities() -> None:
    """Creation/lookup grants never satisfy operator-only mutation or read grants."""

    for granted in BOT_CAPABILITY_SUBSET:
        assert not grant_satisfies(granted, "parties.confirm_contact_point")
        for correction in OPERATOR_CORRECTIONS:
            assert not grant_satisfies(granted, correction)
        for query in OPERATOR_QUERIES:
            assert not grant_satisfies(granted, query)
        assert not grant_satisfies(granted, "parties.rollback_identity")
    assert grant_satisfies("parties.confirm_contact_point", "parties.confirm_contact_point")
    for correction in OPERATOR_CORRECTIONS:
        assert grant_satisfies(correction, correction)
    for query in OPERATOR_QUERIES:
        assert grant_satisfies(query, query)
    assert grant_satisfies("parties.rollback_identity", "parties.rollback_identity")
