from uuid import UUID

import pytest

from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.errors import (
    AmbiguousCopilotIntent,
    CopilotPolicyRejected,
    UnsupportedCopilotIntent,
)
from request_engine.modules.operational_copilot.lowering import lower_copilot_intent
from request_engine.modules.operational_copilot.parser import parse_copilot_intent
from request_engine.modules.operational_copilot.policy import validate_copilot_intent
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)

from .support import parse_canonical_intent

ORG = UUID("11111111-1111-1111-1111-111111111111")
PRINCIPAL = UUID("22222222-2222-2222-2222-222222222222")
QUEUE = UUID("33333333-3333-3333-3333-333333333333")
PROPOSAL = UUID("44444444-4444-4444-4444-444444444444")
RESERVATION = UUID("55555555-5555-5555-5555-555555555555")
CTX = CopilotContext(ORG, PRINCIPAL, "copilot:replay:1")


def test_create_proposal_parses_validates_and_lowers() -> None:
    intent = parse_canonical_intent(f"propose recovery for queue {QUEUE} over 5 days")
    assert intent == CreateRecoveryProposalIntent(QUEUE, 5)

    command = lower_copilot_intent(CTX, validate_copilot_intent(CTX, intent))
    assert isinstance(command, CreateRecoveryProposalCommand)
    assert command.service_queue_id == QUEUE
    assert command.idempotency_key == CTX.idempotency_key


def test_execute_parses_exact_modifiers_and_lowers() -> None:
    text = (
        f"execute recovery proposal {PROPOSAL} for reservation {RESERVATION} "
        "source source-fp proposal proposal-fp allow subject override "
        "without notification"
    )
    intent = parse_canonical_intent(text)
    assert intent == ExecuteRecoveryIntent(
        PROPOSAL, RESERVATION, "source-fp", "proposal-fp", True, False
    )

    command = lower_copilot_intent(CTX, validate_copilot_intent(CTX, intent))
    assert isinstance(command, ExecuteRecoveryCommand)
    assert command.allow_subject_override is True
    assert command.notify is False


def test_replay_lowers_deterministically() -> None:
    intent = parse_canonical_intent(f"propose recovery for queue {QUEUE}")
    validated = validate_copilot_intent(CTX, intent)
    assert lower_copilot_intent(CTX, validated) == lower_copilot_intent(CTX, validated)


def test_ambiguous_and_unsupported_input_fail_closed() -> None:
    with pytest.raises(AmbiguousCopilotIntent):
        parse_copilot_intent("propose recovery and execute recovery")
    with pytest.raises(UnsupportedCopilotIntent):
        parse_copilot_intent(f"delete queue {QUEUE}")


def test_policy_rejects_out_of_bounds_horizon_and_empty_key() -> None:
    intent = CreateRecoveryProposalIntent(QUEUE, 31)
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CTX, intent)
    with pytest.raises(CopilotPolicyRejected):
        validate_copilot_intent(CopilotContext(ORG, PRINCIPAL, ""), intent)
