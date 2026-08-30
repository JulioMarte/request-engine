from datetime import datetime
from uuid import UUID

import pytest

from request_engine.modules.discovery.contracts.commands import (
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
)
from request_engine.modules.operational_copilot.errors import (
    CopilotPolicyRejected,
    UnsupportedCopilotIntent,
)
from request_engine.modules.operational_copilot.lowering import lower_copilot_intent
from request_engine.modules.operational_copilot.parser import parse_copilot_intent
from request_engine.modules.operational_copilot.policy import validate_copilot_intent

from .support import parse_canonical_intent

ORG = UUID("11111111-1111-1111-1111-111111111111")
PRINCIPAL = UUID("22222222-2222-2222-2222-222222222222")
AUTHORITY = UUID("66666666-6666-6666-6666-666666666666")
OFFERING = UUID("99999999-9999-9999-9999-999999999999")
LOCATION = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
RESOURCE = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PUBLICATION = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
CTX_AUTHORITY = CopilotContext(ORG, PRINCIPAL, "copilot:publish:1", AUTHORITY)
CTX = CopilotContext(ORG, PRINCIPAL, "copilot:publish:1")
START = "2026-09-01T08:00:00+00:00"
END = "2026-09-30T20:00:00+00:00"


def test_publish_parses_all_optional_clauses_and_lowers() -> None:
    text = (
        f"publish offering {OFFERING} at location {LOCATION} for discovery "
        f"starting {START} ending {END} with resource {RESOURCE} visibility public"
    )
    intent = parse_canonical_intent(text)
    assert intent == PublishDiscoverySupplyIntent(
        OFFERING,
        LOCATION,
        datetime.fromisoformat(START),
        datetime.fromisoformat(END),
        RESOURCE,
        "public",
    )
    command = lower_copilot_intent(CTX_AUTHORITY, validate_copilot_intent(CTX_AUTHORITY, intent))
    assert isinstance(command, PublishDiscoverySupplyCommand)
    assert command.authority_party_id == AUTHORITY
    assert command.provider_visibility == "public"
    assert command.idempotency_key == CTX_AUTHORITY.idempotency_key


def test_publish_defaults_to_hidden_visibility() -> None:
    text = f"publish offering {OFFERING} at location {LOCATION} for discovery starting {START}"
    intent = parse_canonical_intent(text)
    assert intent == PublishDiscoverySupplyIntent(OFFERING, LOCATION, datetime.fromisoformat(START))


def test_publish_policy_rejects_public_without_resource_and_bad_visibility() -> None:
    public_without_resource = PublishDiscoverySupplyIntent(
        OFFERING, LOCATION, datetime.fromisoformat(START), provider_visibility="public"
    )
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX_AUTHORITY, public_without_resource)
    unknown = PublishDiscoverySupplyIntent(
        OFFERING, LOCATION, datetime.fromisoformat(START), provider_visibility="internal"
    )
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX_AUTHORITY, unknown)


def test_publish_requires_trusted_authority_context() -> None:
    text = (
        f"publish offering {OFFERING} at location {LOCATION} for discovery "
        f"starting {START} with resource {RESOURCE} visibility public"
    )
    intent = parse_canonical_intent(text)
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX, intent)


def test_revoke_parses_and_lowers_with_trusted_authority() -> None:
    text = f"revoke discovery publication {PUBLICATION} at revision 4"
    intent = parse_canonical_intent(text)
    assert intent == RevokeDiscoveryPublicationIntent(PUBLICATION, 4)
    command = lower_copilot_intent(CTX_AUTHORITY, validate_copilot_intent(CTX_AUTHORITY, intent))
    assert isinstance(command, RevokeDiscoveryPublicationCommand)
    assert command.authority_party_id == AUTHORITY
    assert command.expected_revision == 4


def test_natural_language_cannot_supply_authority() -> None:
    text = (
        f"publish offering {OFFERING} at location {LOCATION} for discovery "
        f"starting {START} with authority {AUTHORITY}"
    )
    with pytest.raises(UnsupportedCopilotIntent):
        parse_copilot_intent(text)


def test_publish_replay_lowers_deterministically() -> None:
    text = f"revoke discovery publication {PUBLICATION} at revision 4"
    intent = parse_canonical_intent(text)
    validated = validate_copilot_intent(CTX_AUTHORITY, intent)
    assert lower_copilot_intent(CTX_AUTHORITY, validated) == lower_copilot_intent(
        CTX_AUTHORITY, validated
    )
